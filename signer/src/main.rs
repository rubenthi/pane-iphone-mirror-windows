//! Pane's private JSON-lines signing worker. Never put credentials in argv or logs.
use std::{io::{self, BufRead, Write}, path::PathBuf, sync::{Mutex, atomic::{AtomicU8, Ordering}}, time::Duration};
use serde_json::{json, Value};
use rootcause::prelude::*;
use idevice::usbmuxd::{UsbmuxdAddr, UsbmuxdConnection};
use isideload::{
    anisette::{AnisetteProvider, remote_v3::RemoteV3AnisetteProvider},
    auth::apple_account::{AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse},
    dev::{developer_session::DeveloperSession, teams::DeveloperTeam},
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
        _ => "The signing helper could not start. Restart Pane and retry.",
    }
}

fn public_failure(stage: u8, details: &str) -> (&'static str, &'static str) {
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
    STAGE.store(5, Ordering::Relaxed);
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
    rustls::crypto::ring::default_provider().install_default().ok();
    if std::env::args().any(|a| a == "--version") { println!("pane-signer 2.1.0"); return; }
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
        let apple_code = apple_error_code(&details);
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
        for stage in 0..=5 { assert!(!failure_note(stage).contains("password")); }
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
}
