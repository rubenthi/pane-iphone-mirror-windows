//! Pane's private JSON-lines signing worker. Never put credentials in argv or logs.
use std::{io::{self, BufRead, Write}, path::PathBuf, sync::{Mutex, atomic::{AtomicU8, Ordering}}, time::Duration};
use serde_json::{json, Value};
use rootcause::prelude::*;
use idevice::usbmuxd::{UsbmuxdAddr, UsbmuxdConnection};
use isideload::{
    anisette::{AnisetteProvider, remote_v3::RemoteV3AnisetteProvider},
    auth::apple_account::{AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse},
    dev::{developer_session::DeveloperSession, teams::DeveloperTeam},
    dev::certificates::DevelopmentCertificate,
    sideload::{SideloaderBuilder, TeamSelection, builder::MaxCertsBehavior},
    util::{callbacks::{ExtensionsBehaviorCallbackBox, MaxCertsCallbackBox}, storage::SideloadingStorage},
};
static IPC: Mutex<()> = Mutex::new(());
const ANISETTE_URL: &str = "https://ani.iloader.app";
static STAGE: AtomicU8 = AtomicU8::new(0);

// Never return upstream error text: it may include account details or responses.
fn failure_note(stage: u8) -> &'static str {
    match stage {
        1 => "Could not connect to the signing support service at ani.iloader.app. Check internet access, VPN or firewall settings and try again. Your Apple Account has not been submitted.",
        2 => "Apple sign-in or verification failed. Check internet access and your Apple Account details, then retry. A previous Pane installation does not need to be deleted.",
        3 => "Signed in, but Apple Developer Services could not prepare your account. Check your developer agreements at developer.apple.com/account and try again later.",
        4 => "Apple sign-in succeeded, but the selected iPhone could not be reached over USB. Unlock it, check Trust This Computer and reconnect the cable.",
        5 => "Apple sign-in succeeded, but signing or USB installation failed. Check the selected team, available developer certificates and the iPhone connection. Keep existing signing data and retry.",
        6 => "Apple sign-in succeeded, but Pane could not open a trusted USB session. Unlock your iPhone, accept Trust This Computer if shown and reconnect USB.",
        7 => "Apple sign-in succeeded, but the developer team could not be selected. Check your developer account agreements and retry.",
        _ => "The signing helper could not start. Restart Pane and retry.",
    }
}

fn typed_apple_error_code(error: &Report) -> Option<i64> {
    error.iter_reports().find_map(|node| match node.downcast_current_context::<isideload::SideloadError>() {
        Some(isideload::SideloadError::AuthWithMessage(code, _) | isideload::SideloadError::DeveloperError(code, _)) => Some(*code),
        _ => None,
    })
}

fn installation_failure(details: &str) -> Option<(&'static str, &'static str)> {
    let details = details.to_ascii_lowercase();
    [
        ("maximum number of certificates reached", "certificate_limit", "Apple's development-certificate limit has been reached. Pane kept existing certificates. Recover the original signing key or review certificates in your developer account before choosing any revocation."),
        ("failed to retrieve certificate identity", "certificate", "Pane could not prepare its signing certificate. Saved signing keys have been kept. Check certificate availability and use the same Apple Account and team as before."),
        ("not enough available app ids", "app_id_limit", "Apple's available App ID limit has been reached. Reuse the same signing account and team; deleting the iPhone app does not release App IDs."),
        ("no developer teams available", "team", "Apple returned no developer team. Review your Apple developer account registration and agreements, then retry."),
        ("failed to start lockdown session", "usb_session", "Pane could not start a trusted USB session. Unlock the iPhone, confirm Trust This Computer if prompted and reconnect USB. Existing pairing records have been kept."),
        ("failed to get device pairing file", "usb_pairing", "The signing helper could not read the existing USB trust record. Unlock the iPhone and reconnect it to Apple Devices, then retry Pane. No pairing records were deleted."),
        ("failed to connect to device lockdown", "usb_lockdown", "The signing helper could not open the iPhone's USB connection. Unlock the iPhone, check the data cable and reconnect it."),
        ("failed to install app on device", "device_install", "Signing finished, but iOS did not complete installation. Keep the iPhone unlocked and check Developer Mode, available storage and any on-device prompt."),
        ("failed to sign app", "app_signing", "Pane could not sign the companion package. The saved signing data has been preserved."),
    ].into_iter().find_map(|(needle, code, note)| details.contains(needle).then_some((code, note)))
}

fn public_failure(stage: u8, details: &str) -> (&'static str, &'static str) {
    if let Some(failure) = installation_failure(details) { return failure; }
    let details = details.to_ascii_lowercase();
    // Match fixed categories only; never interpolate error strings into output.
    if details.contains("invalidcertificate") || details.contains("unknownissuer") || details.contains("certificate verify") || details.contains("invalid peer certificate") {
        return ("tls", "A secure connection could not be verified. Check Windows date/time, trusted certificates and HTTPS inspection software. Pane will not disable certificate validation.");
    }
    if details.contains("429 too many") || details.contains("(429") {
        return ("rate_limited", "A signing service is limiting requests. Wait before trying again; do not repeatedly submit your password or verification code.");
    }
    if ["(502", "(503", "(504", "502 bad gateway", "503 service", "504 gateway"].iter().any(|status| details.contains(status)) {
        return ("service_unavailable", "A signing or Apple service is temporarily unavailable. Wait and try again; reinstalling Pane or deleting signing data will not fix a server outage.");
    }
    if details.contains("anisette") || details.contains("provisioning socket") {
        return ("anisette", "The signing support service could not provide authentication data. Check internet access, VPN/firewall settings and try again later. Your saved signing keys have been kept.");
    }
    if details.contains("timed out") || details.contains("dns") || details.contains("connection refused") || details.contains("error sending request") {
        return ("connection", "A signing connection failed. Check internet access, VPN/proxy and firewall settings, then retry. Your saved signing keys have been kept.");
    }
    ("stage_failed", failure_note(stage))
}

fn apple_error_code(details: &str) -> Option<i64> {
    // Only expose a numeric service error code, never its account-specific message.
    for marker in ["Auth error ", "Developer error "] {
        if let Some(tail) = details.split(marker).nth(1) {
            if let Some((number, _)) = tail.split_once(':') {
                if number.len() <= 12 { if let Ok(code) = number.parse() { return Some(code); } }
            }
        }
    }
    None
}

async fn check_service(url: &str) -> Result<isideload::anisette::AnisetteClientInfo, Report> {
    let provider = RemoteV3AnisetteProvider::new(url, Box::new(ProtectedStorage), "0".into())?;
    tokio::time::timeout(Duration::from_secs(20), provider.get_client_info()).await?
}
fn emit(v: Value) { println!("{v}"); let _ = io::stdout().flush(); }
fn read() -> Result<Value, Report> {
    let mut line = String::new();
    if io::stdin().lock().read_line(&mut line)? == 0 { return Err(report!("Pane closed the signing session")); }
    Ok(serde_json::from_str(&line)?)
}
fn ask(v: Value) -> Result<Value, Report> {
    let _lock = IPC.lock().map_err(|_| report!("Signing session lock failed"))?;
    emit(v); let reply = read()?;
    if reply.get("error").is_some() { return Err(report!("Pane could not access protected signing storage")); }
    Ok(reply)
}
struct ProtectedStorage;
impl SideloadingStorage for ProtectedStorage {
    fn store(&self, key: &str, value: &str) -> Result<(), Report> {
        ask(json!({"event":"store","key":key,"value":value}))?; Ok(())
    }
    fn retrieve(&self, key: &str) -> Result<Option<String>, Report> {
        let r = ask(json!({"event":"retrieve","key":key}))?;
        Ok(r["value"].as_str().map(String::from))
    }
}
fn team(teams: &Vec<DeveloperTeam>) -> Option<String> {
    let choices: Vec<Value> = teams.iter().map(|t| json!({"id":t.team_id,"name":t.name})).collect();
    let answer = ask(json!({"event":"prompt","kind":"team","choices":choices})).ok()?;
    let id = answer["value"].as_str()?;
    teams.iter().find(|t| t.team_id == id).map(|t| t.team_id.clone())
}

fn certificate_choices(certs: &[DevelopmentCertificate]) -> Vec<Value> {
    certs.iter().filter_map(|cert| {
        let serial = cert.serial_number.as_ref()?;
        Some(json!({"id":serial,"name":cert.machine_name.as_deref().or(cert.name.as_deref()).unwrap_or("Unnamed development certificate"),
            "serial":serial,"status":cert.status,"expires":cert.expiration_date.as_ref().map(|date| date.to_xml_format())}))
    }).collect()
}

fn approved_certificate(reply: &Value, choices: &[Value]) -> Option<Vec<String>> {
    if reply["confirmed"].as_bool() != Some(true) { return None; }
    let serial = reply["value"].as_str()?;
    choices.iter().any(|choice| choice["id"].as_str() == Some(serial))
        .then(|| vec![serial.to_string()])
}

async fn choose_certificate(certs: Vec<DevelopmentCertificate>) -> Result<Option<Vec<String>>, Report> {
    let choices = certificate_choices(&certs);
    if choices.is_empty() { return Ok(None); }
    let reply = ask(json!({"event":"prompt","kind":"certificate","choices":choices}))?;
    Ok(approved_certificate(&reply, &choices))
}
async fn run() -> Result<(), Report> {
    rustls::crypto::ring::default_provider().install_default().ok();
    isideload::init()?;
    let request = read()?;
    let email = request["email"].as_str().ok_or_else(|| report!("Missing account"))?;
    let password = request["password"].as_str().ok_or_else(|| report!("Missing password"))?;
    let udid = request["udid"].as_str().ok_or_else(|| report!("Missing device"))?;
    let path = PathBuf::from(request["ipa"].as_str().ok_or_else(|| report!("Missing package"))?);
    STAGE.store(1, Ordering::Relaxed);
    emit(json!({"event":"status","note":"Connecting to signing support service…"}));
    check_service(ANISETTE_URL).await?;
    STAGE.store(2, Ordering::Relaxed);
    emit(json!({"event":"status","note":"Signing in to Apple…"}));
    let callback = async |params: TwoFactorCallbackParams| {
        let numbers: Vec<Value> = params.numbers.iter().map(|n| json!({"id":n.id,"name":n.number_with_dial_code})).collect();
        let r = ask(json!({"event":"prompt","kind":"verification","sms":params.sms,"retry":params.unknown,"choices":numbers}))?;
        let value = r["value"].as_str().unwrap_or("");
        Ok(match value {
            "resend" => TwoFactorCallbackResponse::ResendCode,
            "devices" => TwoFactorCallbackResponse::SendToDevices,
            v if v.starts_with("sms:") => TwoFactorCallbackResponse::SendSms(v[4..].parse()?),
            v => TwoFactorCallbackResponse::SubmitCode(v.to_string()),
        })
    };
    let anisette = RemoteV3AnisetteProvider::new(ANISETTE_URL, Box::new(ProtectedStorage), "0".into())?;
    let mut account = AppleAccount::builder(email).anisette_provider(anisette)
        .err_429_retries(None).login(password, callback).await?;
    STAGE.store(3, Ordering::Relaxed);
    let session = DeveloperSession::from_account(&mut account).await?;
    STAGE.store(4, Ordering::Relaxed);
    let mut mux = UsbmuxdConnection::default().await?;
    let devices = mux.get_devices().await?;
    let device = devices.iter().find(|d| d.udid == udid && matches!(d.connection_type, idevice::usbmuxd::Connection::Usb)).ok_or_else(|| report!("Selected iPhone disconnected"))?;
    let provider = device.to_provider(UsbmuxdAddr::from_env_var()?, "Pane");
    STAGE.store(6, Ordering::Relaxed);
    isideload::util::device::IdeviceInfo::from_device(&provider).await?;
    STAGE.store(7, Ordering::Relaxed);
    emit(json!({"event":"status","note":"Selecting Apple developer team…"}));
    let mut signer = SideloaderBuilder::<MaxCertsCallbackBox, ExtensionsBehaviorCallbackBox>::new(session, email.to_string())
        .team_selection(TeamSelection::PromptOnce(team))
        .max_certs_behavior(MaxCertsBehavior::Prompt(Box::new(|certs| Box::pin(choose_certificate(certs)))))
        .storage(Box::new(ProtectedStorage)).machine_name("Pane".into()).build();
    signer.get_team().await?;
    STAGE.store(5, Ordering::Relaxed);
    emit(json!({"event":"status","note":"Preparing certificate and installing Pane. Keep USB connected…"}));
    signer.install_app(&provider, path, false, None::<fn(f32) -> std::future::Ready<()>>, None).await?;
    emit(json!({"event":"complete"})); Ok(())
}
#[tokio::main]
async fn main() {
    rustls::crypto::ring::default_provider().install_default().ok();
    if std::env::args().any(|a| a == "--version") { println!("pane-signer 2.1.0"); return; }
    if std::env::args().any(|a| a == "--check-device") {
        // Read existing USB trust only: no pairing, sign-in, registration or install.
        let result: Result<(), Report> = async {
            let addr = UsbmuxdAddr::from_env_var()?;
            let mut mux = addr.connect(0).await?;
            let devices = mux.get_devices().await?;
            let usb: Vec<_> = devices.iter().filter(|d| matches!(d.connection_type, idevice::usbmuxd::Connection::Usb)).collect();
            if usb.len() != 1 { return Err(report!("Connect exactly one USB iPhone for diagnostics")); }
            let provider = usb[0].to_provider(addr, "Pane");
            isideload::util::device::IdeviceInfo::from_device(&provider).await?;
            Ok(())
        }.await;
        match result {
            Ok(()) => emit(json!({"event":"diagnostic","service":"Trusted USB session","reachable":true})),
            Err(error) => {
                let (code, note) = public_failure(6, &format!("{error:?}"));
                emit(json!({"event":"diagnostic","service":"Trusted USB session","reachable":false,"code":code,"note":note}));
            }
        }
        return;
    }
    if std::env::args().any(|a| a == "--check-services") {
        // Credential-free diagnostics using the same TLS/HTTP stack as signing.
        for url in [ANISETTE_URL, "https://ani.jkcoxson.com"] {
            match check_service(url).await {
                Ok(info) => {
                    emit(json!({"event":"diagnostic","service":url,"reachable":true,"legacy_xcode_identity":info.client_info.contains("com.apple.dt.Xcode")}));
                    if url == ANISETTE_URL {
                        let result = tokio::time::timeout(Duration::from_secs(20), isideload::auth::grandslam::GrandSlam::new(info, false, None)).await;
                        emit(json!({"event":"diagnostic","service":"Apple sign-in discovery","reachable":matches!(result, Ok(Ok(_)))}));
                    }
                }
                Err(_) => emit(json!({"event":"diagnostic","service":url,"reachable":false})),
            }
        }
        return;
    }
    if let Err(error) = run().await {
        // Upstream errors can contain authentication responses; never forward them to logs/UI.
        let stage = STAGE.load(Ordering::Relaxed);
        let details = format!("{error:?}");
        let (code, note) = public_failure(stage, &details);
        let apple_code = typed_apple_error_code(&error).or_else(|| apple_error_code(&details));
        let note = match apple_code { Some(value) => format!("{note} Apple error: {value}."), None => note.to_string() };
        emit(json!({"event":"error","note":note,"code":code,"stage":stage,"appleCode":apple_code}));
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn failures_identify_the_failed_stage_without_upstream_details() {
        assert!(failure_note(1).contains("has not been submitted"));
        assert!(failure_note(4).contains("sign-in succeeded"));
        assert!(failure_note(5).contains("Keep existing signing data"));
        for stage in 0..=7 { assert!(!failure_note(stage).contains("password")); }
    }
    #[test]
    fn public_errors_never_echo_private_upstream_details() {
        for (detail, expected) in [("HTTP (503 Service Unavailable) private@example.com secret", "service_unavailable"), ("anisette secret", "anisette"), ("error sending request secret", "connection"), ("invalid peer certificate secret", "tls"), ("429 Too Many Requests secret", "rate_limited"), ("private429@example.com secret503", "stage_failed")] {
            let (code, note) = public_failure(2, detail);
            assert_eq!(code, expected);
            assert!(!note.contains("secret"));
            assert!(!note.contains("private@example.com"));
        }
    }
    #[test]
    fn only_numeric_apple_error_codes_are_public() {
        assert_eq!(apple_error_code("Auth error -22406: private@example.com secret"), Some(-22406));
        assert_eq!(apple_error_code("Developer error 35: secret"), Some(35));
        assert_eq!(apple_error_code("Auth error private@example.com: secret"), None);
    }
    #[test]
    fn typed_service_codes_and_installation_contexts_are_safe() {
        let error: Report = isideload::SideloadError::DeveloperError(7460, "private@example.com secret".into()).into();
        assert_eq!(typed_apple_error_code(&error), Some(7460));
        assert_eq!(public_failure(5, "Maximum number of certificates reached secret").0, "certificate_limit");
        assert_eq!(public_failure(5, "Failed to start lockdown session private@example.com").0, "usb_session");
        assert_eq!(public_failure(5, "Failed to install app on device secret").0, "device_install");
        assert_eq!(public_failure(5, "Not enough available app IDs. secret").0, "app_id_limit");
        assert_eq!(public_failure(7, "No developer teams available secret").0, "team");
    }
    #[test]
    fn certificate_revocation_requires_explicit_approval_of_one_listed_serial() {
        let choices = vec![json!({"id":"old-pane"}), json!({"id":"another-app"})];
        assert_eq!(approved_certificate(&json!({"value":"old-pane","confirmed":true}), &choices), Some(vec!["old-pane".into()]));
        assert_eq!(approved_certificate(&json!({"value":"old-pane"}), &choices), None);
        assert_eq!(approved_certificate(&json!({"value":"old-pane","confirmed":false}), &choices), None);
        assert_eq!(approved_certificate(&json!({"value":"unlisted","confirmed":true}), &choices), None);
    }
    #[test]
    fn certificate_review_exposes_metadata_only() {
        let cert: DevelopmentCertificate = serde_json::from_value(json!({"serialNumber":"known","name":"Developer","machineName":"Pane","machineId":"not-exposed"})).unwrap();
        let choices = certificate_choices(&[cert]);
        assert_eq!(choices[0]["id"], "known");
        assert_eq!(choices[0]["name"], "Pane");
        assert!(choices[0].get("certContent").is_none());
        assert!(!choices[0].to_string().contains("not-exposed"));
    }
}
