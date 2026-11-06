//! Pane's private JSON-lines signing worker. Never put credentials in argv or logs.
use std::{io::{self, BufRead, Write}, path::PathBuf, sync::Mutex};
use serde_json::{json, Value};
use rootcause::prelude::*;
use idevice::usbmuxd::{UsbmuxdAddr, UsbmuxdConnection};
use isideload::{
    anisette::remote_v3::{RemoteV3AnisetteProvider, DEFAULT_ANISETTE_V3_URL},
    auth::apple_account::{AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse},
    dev::{developer_session::DeveloperSession, teams::DeveloperTeam},
    sideload::{SideloaderBuilder, TeamSelection, builder::MaxCertsBehavior},
    util::{callbacks::{ExtensionsBehaviorCallbackBox, MaxCertsCallbackBox}, storage::SideloadingStorage},
};
static IPC: Mutex<()> = Mutex::new(());
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
async fn run() -> Result<(), Report> {
    rustls::crypto::ring::default_provider().install_default().ok();
    isideload::init()?;
    let request = read()?;
    let email = request["email"].as_str().ok_or_else(|| report!("Missing account"))?;
    let password = request["password"].as_str().ok_or_else(|| report!("Missing password"))?;
    let udid = request["udid"].as_str().ok_or_else(|| report!("Missing device"))?;
    let path = PathBuf::from(request["ipa"].as_str().ok_or_else(|| report!("Missing package"))?);
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
    let anisette = RemoteV3AnisetteProvider::new(DEFAULT_ANISETTE_V3_URL, Box::new(ProtectedStorage), "0".into())?;
    let mut account = AppleAccount::builder(email).anisette_provider(anisette).login(password, callback).await?;
    let session = DeveloperSession::from_account(&mut account).await?;
    let mut mux = UsbmuxdConnection::default().await?;
    let devices = mux.get_devices().await?;
    let device = devices.iter().find(|d| d.udid == udid && matches!(d.connection_type, idevice::usbmuxd::Connection::Usb)).ok_or_else(|| report!("Selected iPhone disconnected"))?;
    let provider = device.to_provider(UsbmuxdAddr::from_env_var()?, "Pane");
    emit(json!({"event":"status","note":"Preparing certificate and installing Pane. Keep USB connected…"}));
    let mut signer = SideloaderBuilder::<MaxCertsCallbackBox, ExtensionsBehaviorCallbackBox>::new(session, email.to_string())
        .team_selection(TeamSelection::PromptOnce(team))
        .max_certs_behavior(MaxCertsBehavior::Error)
        .storage(Box::new(ProtectedStorage)).machine_name("Pane".into()).build();
    signer.install_app(&provider, path, false, None::<fn(f32) -> std::future::Ready<()>>, None).await?;
    emit(json!({"event":"complete"})); Ok(())
}
#[tokio::main]
async fn main() {
    if std::env::args().any(|a| a == "--version") { println!("pane-signer 2.1.0"); return; }
    if let Err(_error) = run().await {
        // Upstream errors can contain authentication responses; never forward them to logs/UI.
        emit(json!({"event":"error","note":"Signing or installation failed. Check your Apple Account, verification code, USB connection and available developer certificates, then retry."}));
        std::process::exit(1);
    }
}
