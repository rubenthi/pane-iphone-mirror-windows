use fs2::FileExt;
use notify::{RecursiveMode, Watcher};
use pane_companion::{
    AttributeBuffer, Notice, Preferences, category_label, parse_notice, request_attributes,
    xml_escape,
};
use serde::Deserialize;
use std::{
    collections::VecDeque,
    fs,
    path::{Path, PathBuf},
    time::Duration,
};
use tokio::sync::mpsc;
use windows::{
    Data::Xml::Dom::XmlDocument,
    Devices::{
        Bluetooth::{
            BluetoothCacheMode, BluetoothConnectionStatus, BluetoothLEDevice,
            GenericAttributeProfile::{
                GattCharacteristic, GattClientCharacteristicConfigurationDescriptorValue as Cccd,
                GattCommunicationStatus, GattDeviceService, GattSession, GattValueChangedEventArgs,
            },
        },
        Enumeration::DeviceInformation,
    },
    Foundation::TypedEventHandler,
    Media::Audio::{
        AudioPlaybackConnection, AudioPlaybackConnectionOpenResultStatus,
        AudioPlaybackConnectionState,
    },
    Storage::Streams::{DataReader, DataWriter},
    UI::Notifications::{ToastNotification, ToastNotificationManager},
    Win32::{
        Foundation::{CloseHandle, WAIT_TIMEOUT},
        System::{
            Threading::{OpenProcess, PROCESS_SYNCHRONIZE, WaitForSingleObject},
            WinRT::{RO_INIT_MULTITHREADED, RoInitialize},
        },
        UI::Shell::SetCurrentProcessExplicitAppUserModelID,
    },
    core::{GUID, HSTRING},
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const APP_ID: &str = "Pane.Desktop";
const ANCS: GUID = GUID::from_u128(0x7905f431_b5ce_4e99_a40f_4b1e122d00d0);
const SOURCE: GUID = GUID::from_u128(0x9fbf120d_6301_42d9_8c58_25e699a21dbd);
const CONTROL: GUID = GUID::from_u128(0x69d1d8f3_45e1_49a8_9821_9bbdfdaad9d9);
const DATA: GUID = GUID::from_u128(0x22eac6e9_24d6_4bb5_be44_b36ace7c7bfb);
#[derive(Default, Deserialize)]
struct Session {
    desktop_pid: u32,
    mirroring: bool,
    #[serde(default)]
    desktop_executable: String,
}
enum Event {
    Config,
    Tick,
    Notice(u64, Notice),
    Data(u64, Vec<u8>),
    Ble(u64, bool),
    Audio(u64),
    ParentExited(u32),
}
fn read<T: serde::de::DeserializeOwned + Default>(path: &Path) -> T {
    use std::io::Read;
    let mut bytes = Vec::new();
    let result = fs::File::open(path).and_then(|file| file.take(32769).read_to_end(&mut bytes));
    if result.is_err() || bytes.len() > 32768 {
        return T::default();
    }
    serde_json::from_slice(&bytes).unwrap_or_default()
}

fn alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    unsafe {
        match OpenProcess(PROCESS_SYNCHRONIZE, false, pid) {
            Ok(h) => {
                let active = WaitForSingleObject(h, 0) == WAIT_TIMEOUT;
                let _ = CloseHandle(h);
                active
            }
            Err(_) => false,
        }
    }
}
fn parent_exit(pid: u32, tx: mpsc::Sender<Event>) {
    // A detached, sleeping OS wait thread does not keep the Tokio runtime alive
    // when background mode is switched off while the desktop is still open.
    std::thread::spawn(move || {
        unsafe {
            if let Ok(h) = OpenProcess(PROCESS_SYNCHRONIZE, false, pid) {
                let _ = WaitForSingleObject(h, u32::MAX);
                let _ = CloseHandle(h);
            }
        }
        let _ = tx.blocking_send(Event::ParentExited(pid));
    });
}
#[derive(Default)]
struct Status {
    audio: String,
    notifications: String,
}
impl Status {
    fn save(&self, dir: &Path) {
        let body = serde_json::json!({"pid":std::process::id(),"audio":self.audio,"notifications":self.notifications});
        // This file contains state only, never notification titles, bodies or device IDs.
        if let Ok(bytes) = serde_json::to_vec(&body) {
            let _ = fs::write(dir.join("companion-status.json"), bytes);
        }
    }
}
async fn list(selector: HSTRING) -> Result<Vec<serde_json::Value>> {
    let devices = DeviceInformation::FindAllAsyncAqsFilter(&selector)?.await?;
    let mut out = Vec::new();
    for d in devices {
        out.push(serde_json::json!({"id":d.Id()?.to_string(),"name":d.Name()?.to_string()}));
    }
    Ok(out)
}
async fn devices() -> Result<()> {
    let audio = list(AudioPlaybackConnection::GetDeviceSelector()?).await?;
    let notifications = list(BluetoothLEDevice::GetDeviceSelectorFromPairingState(true)?).await?;
    println!(
        "{}",
        serde_json::json!({"audio":audio,"notifications":notifications})
    );
    Ok(())
}
fn register_toasts(executable: &str) -> Result<()> {
    use windows::Win32::{
        Foundation::PROPERTYKEY,
        System::{
            Com::{
                CLSCTX_INPROC_SERVER, CoCreateInstance, CoTaskMemFree, IPersistFile,
                StructuredStorage::PROPVARIANT,
            },
            Variant::VT_LPWSTR,
        },
        UI::Shell::{
            FOLDERID_Programs, IShellLinkW, KF_FLAG_DEFAULT, PropertiesSystem::IPropertyStore,
            SHGetKnownFolderPath, SHStrDupW, ShellLink,
        },
    };
    use windows::core::Interface;
    // An unpackaged desktop app needs a Start-menu shortcut carrying its AUMID.
    // Use the actual Pane executable, never the temporary PyInstaller directory.
    if !executable.is_empty() && Path::new(executable).is_file() {
        unsafe {
            let folder = SHGetKnownFolderPath(&FOLDERID_Programs, KF_FLAG_DEFAULT, None)?;
            let path = PathBuf::from(folder.to_string()?);
            CoTaskMemFree(Some(folder.0.cast()));
            fs::create_dir_all(&path)?;
            let link: IShellLinkW = CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER)?;
            link.SetPath(&HSTRING::from(executable))?;
            link.SetIconLocation(&HSTRING::from(executable), 0)?;
            link.SetDescription(windows::core::w!(
                "Pane — iPhone mirroring and notifications"
            ))?;
            let store: IPropertyStore = link.cast()?;
            let key = PROPERTYKEY {
                fmtid: GUID::from_u128(0x9f4c2855_9f79_4b39_a8d0_e1d42de1d5f3),
                pid: 5,
            };
            let mut value = PROPVARIANT::default();
            (*value.Anonymous.Anonymous).vt = VT_LPWSTR;
            (*value.Anonymous.Anonymous).Anonymous.pwszVal =
                SHStrDupW(windows::core::w!("Pane.Desktop"))?;
            store.SetValue(&key, &value)?;
            store.Commit()?;
            let file: IPersistFile = link.cast()?;
            file.Save(&HSTRING::from(path.join("Pane.lnk").as_os_str()), true)?;
        }
    }
    let hkcu = winreg::RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
    let (key, _) = hkcu.create_subkey(format!("Software\\Classes\\AppUserModelId\\{APP_ID}"))?;
    key.set_value("DisplayName", &"Pane")?;
    unsafe {
        SetCurrentProcessExplicitAppUserModelID(windows::core::w!("Pane.Desktop"))?;
    }
    Ok(())
}
fn toast(uid: u32, title: &str, body: &str) -> Result<()> {
    let xml = XmlDocument::new()?;
    xml.LoadXml(&HSTRING::from(format!("<toast><visual><binding template=\"ToastGeneric\"><text>{}</text><text>{}</text></binding></visual><audio silent=\"true\"/></toast>",xml_escape(title),xml_escape(body))))?;
    let n = ToastNotification::CreateToastNotification(&xml)?;
    n.SetTag(&HSTRING::from(uid.to_string()))?;
    n.SetGroup(&HSTRING::from("iPhone"))?;
    ToastNotificationManager::CreateToastNotifierWithId(&HSTRING::from(APP_ID))?.Show(&n)?;
    Ok(())
}
struct Audio {
    connection: AudioPlaybackConnection,
    token: i64,
    id: String,
    generation: u64,
}
impl Drop for Audio {
    fn drop(&mut self) {
        let _ = self.connection.RemoveStateChanged(self.token);
        let _ = self.connection.Close();
    }
}
async fn audio_open(id: &str, generation: u64, tx: mpsc::Sender<Event>) -> Result<Audio> {
    let connection = AudioPlaybackConnection::TryCreateFromId(&HSTRING::from(id))?;
    let token = connection.StateChanged(&TypedEventHandler::<
        AudioPlaybackConnection,
        windows::core::IInspectable,
    >::new(move |sender, _| {
        if sender.is_some() {
            let _ = tx.try_send(Event::Audio(generation));
        }
        Ok(())
    }))?;
    let result = Audio {
        connection,
        token,
        id: id.into(),
        generation,
    };
    result.connection.StartAsync()?.await?;
    let opened = result.connection.OpenAsync()?.await?;
    if opened.Status()? != AudioPlaybackConnectionOpenResultStatus::Success {
        return Err("Bluetooth audio could not open. Pair the iPhone and select this PC in the iPhone audio output menu.".into());
    }
    Ok(result)
}
struct Ancs {
    device: BluetoothLEDevice,
    service: GattDeviceService,
    session: GattSession,
    source: GattCharacteristic,
    data: GattCharacteristic,
    control: GattCharacteristic,
    source_token: Option<i64>,
    data_token: Option<i64>,
    connection_token: Option<i64>,
    generation: u64,
    id: String,
}
impl Drop for Ancs {
    fn drop(&mut self) {
        if let Some(t) = self.source_token {
            let _ = self.source.RemoveValueChanged(t);
        }
        if let Some(t) = self.data_token {
            let _ = self.data.RemoveValueChanged(t);
        }
        if let Some(t) = self.connection_token {
            let _ = self.device.RemoveConnectionStatusChanged(t);
        }
        let _ = self.session.SetMaintainConnection(false);
        let _ = self.session.Close();
        let _ = self.service.Close();
        let _ = self.device.Close();
    }
}
async fn characteristic(service: &GattDeviceService, id: GUID) -> Result<GattCharacteristic> {
    let r = service
        .GetCharacteristicsForUuidWithCacheModeAsync(id, BluetoothCacheMode::Uncached)?
        .await?;
    if r.Status()? != GattCommunicationStatus::Success {
        return Err("iPhone notification access was denied.".into());
    }
    let list = r.Characteristics()?;
    if list.Size()? != 1 {
        return Err("iPhone notification service is incomplete.".into());
    }
    Ok(list.GetAt(0)?)
}
fn bytes(args: &GattValueChangedEventArgs) -> windows::core::Result<Vec<u8>> {
    let reader = DataReader::FromBuffer(&args.CharacteristicValue()?)?;
    let size = reader.UnconsumedBufferLength()?;
    if size > 2048 {
        return Ok(Vec::new());
    }
    let mut bytes = vec![0; size as usize];
    reader.ReadBytes(&mut bytes)?;
    Ok(bytes)
}
async fn ancs_open(id: &str, generation: u64, tx: mpsc::Sender<Event>) -> Result<Ancs> {
    let device = BluetoothLEDevice::FromIdAsync(&HSTRING::from(id))?.await?;
    let services = device
        .GetGattServicesForUuidWithCacheModeAsync(ANCS, BluetoothCacheMode::Uncached)?
        .await?;
    if services.Status()? != GattCommunicationStatus::Success || services.Services()?.Size()? != 1 {
        let _ = device.Close();
        return Err("On iPhone, enable Share System Notifications for this PC in Bluetooth settings, then reconnect.".into());
    }
    let service = services.Services()?.GetAt(0)?;
    let session = GattSession::FromDeviceIdAsync(&device.BluetoothDeviceId()?)?.await?;
    let source = characteristic(&service, SOURCE).await?;
    let data = characteristic(&service, DATA).await?;
    let control = characteristic(&service, CONTROL).await?;
    let mut result = Ancs {
        device,
        service,
        session,
        source,
        data,
        control,
        source_token: None,
        data_token: None,
        connection_token: None,
        generation,
        id: id.into(),
    };
    let source_tx = tx.clone();
    result.source_token = Some(result.source.ValueChanged(&TypedEventHandler::<
        GattCharacteristic,
        GattValueChangedEventArgs,
    >::new(move |_, args| {
        if let Some(args) = args.as_ref()
            && let Some(n) = parse_notice(&bytes(args)?)
        {
            let _ = source_tx.try_send(Event::Notice(generation, n));
        }
        Ok(())
    }))?);
    let data_tx = tx.clone();
    result.data_token = Some(result.data.ValueChanged(&TypedEventHandler::<
        GattCharacteristic,
        GattValueChangedEventArgs,
    >::new(move |_, args| {
        if let Some(args) = args.as_ref() {
            let _ = data_tx.try_send(Event::Data(generation, bytes(args)?));
        }
        Ok(())
    }))?);
    result.connection_token =
        Some(result.device.ConnectionStatusChanged(&TypedEventHandler::<
            BluetoothLEDevice,
            windows::core::IInspectable,
        >::new(move |sender, _| {
            if let Some(sender) = sender.as_ref() {
                let _ = tx.try_send(Event::Ble(
                    generation,
                    sender.ConnectionStatus()? == BluetoothConnectionStatus::Connected,
                ));
            }
            Ok(())
        }))?);
    // The guard releases every registered handler if setup fails or is cancelled.
    result.session.SetMaintainConnection(true)?;
    for c in [&result.data, &result.source] {
        if c.WriteClientCharacteristicConfigurationDescriptorAsync(Cccd::Notify)?
            .await?
            != GattCommunicationStatus::Success
        {
            return Err(
                "Allow Bluetooth notification access on your iPhone, then try again.".into(),
            );
        }
    }
    Ok(result)
}
impl Ancs {
    async fn request(&self, uid: u32) -> Result<()> {
        let writer = DataWriter::new()?;
        writer.WriteBytes(&request_attributes(uid))?;
        if self
            .control
            .WriteValueAsync(&writer.DetachBuffer()?)?
            .await?
            != GattCommunicationStatus::Success
        {
            return Err("Notification details were unavailable.".into());
        }
        Ok(())
    }
}
struct Request {
    notice: Notice,
    buffer: AttributeBuffer,
    deadline: tokio::time::Instant,
}
async fn worker(dir: PathBuf) -> Result<()> {
    fs::create_dir_all(&dir)?;
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(dir.join("companion.lock"))?;
    if lock.try_lock_exclusive().is_err() {
        return Ok(());
    }
    let (tx, mut rx) = mpsc::channel(64);
    let config_changed = std::sync::Arc::new(tokio::sync::Notify::new());
    let config_signal = config_changed.clone();
    let mut watcher = notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
        if let Ok(e) = event
            && e.paths.iter().any(|p| {
                matches!(
                    p.file_name().and_then(|n| n.to_str()),
                    Some("preferences.json" | "session.json")
                )
            })
        {
            config_signal.notify_one();
        }
    })?;
    watcher.watch(&dir, RecursiveMode::NonRecursive)?;
    let mut status = Status::default();
    let mut prefs: Preferences = read(&dir.join("preferences.json"));
    let mut session: Session = read(&dir.join("session.json"));
    // Audio remains available if Windows blocks notification registration.
    if prefs.notifications_enabled {
        let _ = register_toasts(&session.desktop_executable);
    }
    if alive(session.desktop_pid) {
        parent_exit(session.desktop_pid, tx.clone());
    } else {
        session.desktop_pid = 0;
        session.mirroring = false;
    }
    let mut audio: Option<Audio> = None;
    let mut ancs: Option<Ancs> = None;
    let mut generation = 0u64;
    let mut audio_generation = 0u64;
    let mut configure = true;
    let mut queue: VecDeque<Notice> = VecDeque::new();
    let mut seen: VecDeque<u32> = VecDeque::new();
    let mut request: Option<Request> = None;
    let mut retry: Option<tokio::time::Instant> = None;
    loop {
        if configure {
            configure = false;
            retry = None;
            let want_audio = prefs.audio_enabled
                && session.mirroring
                && session.desktop_pid != 0
                && !prefs.audio_device_id.is_empty();
            let want_notifications = prefs.notifications_enabled
                && (session.desktop_pid != 0 || prefs.background_enabled)
                && !prefs.notification_device_id.is_empty();
            if !want_audio {
                audio = None;
                status.audio = if prefs.audio_device_id.is_empty() {
                    "Choose a paired iPhone for Bluetooth audio."
                } else {
                    "Bluetooth audio starts with mirroring."
                }
                .into();
            }
            if !want_notifications {
                ancs = None;
                request = None;
                queue.clear();
                status.notifications = if !prefs.notifications_enabled {
                    "Phone notifications are off."
                } else {
                    "Choose your paired iPhone and enable Share System Notifications."
                }
                .into();
            }
            if audio
                .as_ref()
                .is_some_and(|a| a.id != prefs.audio_device_id)
            {
                audio = None;
            }
            if ancs
                .as_ref()
                .is_some_and(|a| a.id != prefs.notification_device_id)
            {
                ancs = None;
                request = None;
                queue.clear();
                seen.clear();
            }
            if want_audio && audio.is_none() {
                audio_generation += 1;
                status.audio = "Connecting Bluetooth audio…".into();
                status.save(&dir);
                match tokio::time::timeout(
                    Duration::from_secs(15),
                    audio_open(&prefs.audio_device_id, audio_generation, tx.clone()),
                )
                .await
                {
                    Ok(Ok(a)) => {
                        audio = Some(a);
                        status.audio="Receiver connected. Select Zephyrus in the iPhone audio menu if needed.".into();
                    }
                    _ => {
                        status.audio="Audio not connected. Pair the iPhone, then select this PC in its audio output menu.".into();
                        retry = Some(tokio::time::Instant::now() + Duration::from_secs(30));
                    }
                }
            }
            if want_notifications && ancs.is_none() {
                generation += 1;
                status.notifications = "Connecting to iPhone notifications…".into();
                status.save(&dir);
                match tokio::time::timeout(
                    Duration::from_secs(15),
                    ancs_open(&prefs.notification_device_id, generation, tx.clone()),
                )
                .await
                {
                    Ok(Ok(a)) => {
                        ancs = Some(a);
                        status.notifications =
                            "Connected. Selected notifications will appear on this PC.".into();
                    }
                    _ => {
                        status.notifications="Waiting for iPhone. Enable Share System Notifications in its Bluetooth settings.".into();
                        retry = Some(tokio::time::Instant::now() + Duration::from_secs(30));
                    }
                }
            }
            status.save(&dir);
            if session.desktop_pid == 0 && !want_notifications {
                break;
            }
            if !want_audio && !want_notifications {
                break;
            }
        }
        if request.is_none()
            && prefs.show_previews
            && let (Some(a), Some(n)) = (&ancs, queue.pop_front())
            && prefs.accepts(n.category)
            && matches!(
                tokio::time::timeout(Duration::from_secs(5), a.request(n.uid)).await,
                Ok(Ok(()))
            )
        {
            request = Some(Request {
                notice: n,
                buffer: AttributeBuffer::default(),
                deadline: tokio::time::Instant::now() + Duration::from_secs(5),
            });
        }
        if request.is_none() && !queue.is_empty() {
            continue;
        }
        let deadline = request
            .as_ref()
            .map(|r| r.deadline)
            .into_iter()
            .chain(retry)
            .min();
        let timer = async {
            if let Some(d) = deadline {
                tokio::time::sleep_until(d).await
            } else {
                std::future::pending::<()>().await
            }
        };
        // Settings use a coalesced signal, separate from bounded Bluetooth data.
        // Disabling sharing cannot be dropped or blocked by a burst of alerts.
        let event = tokio::select! {
            biased;
            _ = config_changed.notified() => Event::Config,
            _ = timer => Event::Tick,
            event = rx.recv() => match event { Some(event) => event, None => break },
        };
        match event {
            Event::Tick => {
                if request
                    .as_ref()
                    .is_some_and(|r| r.deadline <= tokio::time::Instant::now())
                {
                    request = None;
                }
                if retry.is_some_and(|r| r <= tokio::time::Instant::now()) {
                    configure = true;
                }
            }
            Event::ParentExited(pid) if pid == session.desktop_pid => {
                session.desktop_pid = 0;
                session.mirroring = false;
                configure = true;
            }
            Event::Config => {
                let next: Session = read(&dir.join("session.json"));
                if next.desktop_pid != session.desktop_pid && alive(next.desktop_pid) {
                    parent_exit(next.desktop_pid, tx.clone());
                }
                session = next;
                if !alive(session.desktop_pid) {
                    session.desktop_pid = 0;
                    session.mirroring = false;
                }
                let next_prefs: Preferences = read(&dir.join("preferences.json"));
                if next_prefs != prefs {
                    request = None;
                    queue.clear();
                }
                prefs = next_prefs;
                if prefs.notifications_enabled {
                    let _ = register_toasts(&session.desktop_executable);
                }
                configure = true;
            }
            Event::Notice(g, n) if ancs.as_ref().is_some_and(|a| a.generation == g) => {
                if n.removed {
                    let _ = ToastNotificationManager::History().and_then(|h| {
                        h.RemoveGroupedTagWithId(
                            &HSTRING::from(n.uid.to_string()),
                            &HSTRING::from("iPhone"),
                            &HSTRING::from(APP_ID),
                        )
                    });
                    seen.retain(|id| *id != n.uid);
                    queue.retain(|x| x.uid != n.uid);
                    if request.as_ref().is_some_and(|r| r.notice.uid == n.uid) {
                        request = None;
                    }
                } else if prefs.accepts(n.category) && !seen.contains(&n.uid) {
                    seen.push_back(n.uid);
                    if seen.len() > 512 {
                        seen.pop_front();
                    }
                    if prefs.show_previews {
                        if queue.len() < 32 {
                            queue.push_back(n);
                        }
                    } else if toast(
                        n.uid,
                        category_label(n.category),
                        "Open your iPhone to view it.",
                    )
                    .is_err()
                    {
                        status.notifications = "Windows could not show notifications. Check notification permissions for Pane.".into();
                        status.save(&dir);
                    }
                }
            }
            Event::Data(g, data) if ancs.as_ref().is_some_and(|a| a.generation == g) => {
                if let Some(r) = &mut request {
                    match r.buffer.push(&data, r.notice.uid) {
                        Ok(Some((title, body))) => {
                            if prefs.show_previews
                                && prefs.accepts(r.notice.category)
                                && toast(r.notice.uid, &title, &body).is_err()
                            {
                                status.notifications =
                                    "Check Windows notification permissions for Pane.".into();
                                status.save(&dir);
                            }
                            request = None;
                        }
                        Err(_) => {
                            request = None;
                        }
                        _ => {}
                    }
                }
            }
            Event::Ble(g, connected) if ancs.as_ref().is_some_and(|a| a.generation == g) => {
                status.notifications = if connected {
                    "Connected. Selected notifications will appear on this PC."
                } else {
                    "iPhone disconnected. Waiting for Bluetooth to reconnect."
                }
                .into();
                status.save(&dir);
            }
            Event::Audio(g) if audio.as_ref().is_some_and(|a| a.generation == g) => {
                // Read current state: an earlier Closed event may have queued while OpenAsync finished.
                let open = audio.as_ref().and_then(|a| a.connection.State().ok())
                    == Some(AudioPlaybackConnectionState::Opened);
                status.audio = if open {
                    "Bluetooth audio receiver connected."
                } else {
                    "Bluetooth audio disconnected. Select this PC on the iPhone to reconnect."
                }
                .into();
                if !open {
                    audio = None;
                    retry = Some(tokio::time::Instant::now() + Duration::from_secs(30));
                }
                status.save(&dir);
            }
            _ => {}
        }
    }

    drop(ancs);
    drop(audio);
    let _ = fs::remove_file(dir.join("companion-status.json"));
    Ok(())
}
pub fn run() -> Result<()> {
    unsafe {
        RoInitialize(RO_INIT_MULTITHREADED)?;
    }
    let args: Vec<String> = std::env::args().collect();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_time()
        .build()?;
    if args.get(1).map(String::as_str) == Some("--devices") {
        return runtime.block_on(devices());
    }
    if args.get(1).map(String::as_str) == Some("--run")
        && let Some(path) = args.get(2)
    {
        return runtime.block_on(worker(PathBuf::from(path)));
    }
    Err("Use --devices or --run <Pane data directory>.".into())
}
