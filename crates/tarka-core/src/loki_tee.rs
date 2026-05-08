//! Optional fan-out of JSON log lines to Grafana Loki (HTTP push).
//!
//! Activated when `TARKA_LOKI_PUSH_URL` or `LOKI_PUSH_URL` is a non-empty `http(s)` URL.
//! Uses a bounded `sync_channel` with `try_send` for backpressure, a background worker with
//! batching, bounded HTTP timeouts, retries with exponential backoff + jitter, and stderr
//! diagnostics when drops or exhaustion occur.

use std::io::{self, Write};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{sync_channel, Receiver, SyncSender, TrySendError};
use std::sync::{Mutex, OnceLock};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde_json::json;

const DEFAULT_QUEUE: usize = 4096;
const DEFAULT_BATCH_MAX: usize = 50;
const DEFAULT_HTTP_TIMEOUT: Duration = Duration::from_secs(5);
const DEFAULT_MAX_ATTEMPTS: u32 = 5;
const DEFAULT_BACKOFF_BASE: Duration = Duration::from_millis(80);
const DEFAULT_BACKOFF_CAP: Duration = Duration::from_secs(3);

fn push_url() -> Option<String> {
    let raw = std::env::var("TARKA_LOKI_PUSH_URL")
        .or_else(|_| std::env::var("LOKI_PUSH_URL"))
        .unwrap_or_default();
    let s = raw.trim().to_string();
    if s.is_empty() {
        return None;
    }
    if !s.starts_with("http://") && !s.starts_with("https://") {
        eprintln!("[loki_tee] invalid URL scheme (must be http/https): {s:?}");
        return None;
    }
    Some(s)
}

fn service_name() -> String {
    std::env::var("TARKA_SERVICE_NAME").unwrap_or_else(|_| "tarka-rust".to_string())
}

fn env_usize(key: &str, default: usize) -> usize {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_duration_secs(key: &str, default: Duration) -> Duration {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse::<f64>().ok())
        .map(|s| Duration::from_secs_f64(s.max(0.05)))
        .unwrap_or(default)
}

fn env_u32(key: &str, default: u32) -> u32 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

/// Writes JSON log lines to stdout and forwards complete lines to the Loki worker.
pub struct StdoutLokiTee {
    stdout: std::io::Stdout,
    pending: Vec<u8>,
    tx: SyncSender<String>,
    dropped: AtomicU64,
    last_drop_report: Mutex<Instant>,
}

impl StdoutLokiTee {
    pub fn new(tx: SyncSender<String>) -> Self {
        Self {
            stdout: std::io::stdout(),
            pending: Vec::with_capacity(512),
            tx,
            dropped: AtomicU64::new(0),
            last_drop_report: Mutex::new(Instant::now() - Duration::from_secs(3600)),
        }
    }

    fn drain_lines(&mut self) -> io::Result<()> {
        loop {
            let nl = match self.pending.iter().position(|b| *b == b'\n') {
                Some(i) => i,
                None => break,
            };
            let line_bytes: Vec<u8> = self.pending.drain(..=nl).collect();
            let trim_end = line_bytes.len().saturating_sub(1);
            let line = String::from_utf8_lossy(&line_bytes[..trim_end]).into_owned();
            match self.tx.try_send(line) {
                Ok(()) => {}
                Err(TrySendError::Full(_)) => self.record_drop(),
                Err(TrySendError::Disconnected(_)) => {}
            }
        }
        Ok(())
    }

    fn record_drop(&self) {
        let n = self.dropped.fetch_add(1, Ordering::Relaxed) + 1;
        let mut last = self.last_drop_report.lock().unwrap_or_else(|p| p.into_inner());
        if last.elapsed() > Duration::from_secs(60) {
            eprintln!("[loki_tee] dropped {n} log line(s); queue full");
            *last = Instant::now();
            self.dropped.store(0, Ordering::Relaxed);
        }
    }
}

impl Write for StdoutLokiTee {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.stdout.lock().write_all(buf)?;
        self.pending.extend_from_slice(buf);
        self.drain_lines()?;
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.stdout.lock().flush()
    }
}

/// Cloneable handle sharing one `Write` target (stdout or [`StdoutLokiTee`]) for `tracing-subscriber`.
#[derive(Clone)]
pub struct SharedDynWriter {
    inner: std::sync::Arc<std::sync::Mutex<Box<dyn Write + Send>>>,
}

impl SharedDynWriter {
    pub fn new(w: Box<dyn Write + Send>) -> Self {
        Self {
            inner: std::sync::Arc::new(std::sync::Mutex::new(w)),
        }
    }
}

impl Write for SharedDynWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let mut g = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        g.write(buf)
    }

    fn flush(&mut self) -> io::Result<()> {
        let mut g = self.inner.lock().unwrap_or_else(|p| p.into_inner());
        g.flush()
    }
}

struct WorkerGuard {
    _keepalive: SyncSender<String>,
    _handle: JoinHandle<()>,
}

fn post_with_retries(url: &str, body: &[u8]) {
    let timeout = env_duration_secs("TARKA_LOKI_HTTP_TIMEOUT_S", DEFAULT_HTTP_TIMEOUT);
    let max_attempts = env_u32("TARKA_LOKI_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS);
    let base = env_duration_secs("TARKA_LOKI_BACKOFF_BASE_S", DEFAULT_BACKOFF_BASE);
    let cap = env_duration_secs("TARKA_LOKI_BACKOFF_CAP_S", DEFAULT_BACKOFF_CAP);

    let mut last_err: Option<String> = None;
    for attempt in 1..=max_attempts {
        let resp = ureq::post(url)
            .timeout(timeout)
            .set("Content-Type", "application/json; charset=utf-8")
            .send_bytes(body);
        match resp {
            Ok(r) => {
                let status = r.status();
                if (200..300).contains(&status) {
                    return;
                }
                let preview = r.into_string().unwrap_or_default();
                last_err = Some(format!("HTTP {status}: {preview}"));
                if (400..500).contains(&status) && status != 429 {
                    eprintln!("[loki_tee] non-retryable HTTP {status}; giving up");
                    return;
                }
            }
            Err(e) => {
                last_err = Some(e.to_string());
            }
        }
        if attempt >= max_attempts {
            break;
        }
        let exp = base.as_secs_f64() * 2_f64.powi(attempt.saturating_sub(1) as i32);
        let sleep_s = exp.min(cap.as_secs_f64());
        let jitter = rand_simple() * sleep_s * 0.25;
        std::thread::sleep(Duration::from_secs_f64(sleep_s + jitter));
    }
    eprintln!(
        "[loki_tee] exhausted retries posting to Loki url={url:?} last_err={last_err:?}"
    );
}

fn rand_simple() -> f64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(12345);
    ((nanos % 1000) as f64) / 1000.0
}

fn worker_loop(rx: Receiver<String>, url: String, service: String, batch_max: usize) {
    let mut pending: Vec<String> = Vec::new();
    loop {
        let got_line = match rx.recv_timeout(Duration::from_millis(250)) {
            Ok(line) => {
                pending.push(line);
                true
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => false,
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        };
        let should_flush =
            !pending.is_empty() && (pending.len() >= batch_max || !got_line);
        if should_flush {
            flush_batch(&url, &service, &mut pending);
        }
    }
    if !pending.is_empty() {
        flush_batch(&url, &service, &mut pending);
    }
}

fn flush_batch(url: &str, service: &str, pending: &mut Vec<String>) {
    if pending.is_empty() {
        return;
    }
    let base_ns = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let values: Vec<Vec<String>> = pending
        .iter()
        .enumerate()
        .map(|(i, line)| vec![(base_ns + i as u128).to_string(), line.clone()])
        .collect();
    let body = json!({
        "streams": [{
            "stream": {"job": "tarka", "service": service, "component": "rust"},
            "values": values,
        }]
    });
    let encoded = match serde_json::to_vec(&body) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("[loki_tee] serialize push body failed: {e}");
            pending.clear();
            return;
        }
    };
    post_with_retries(url, &encoded);
    pending.clear();
}

static LOKI_GUARD: OnceLock<WorkerGuard> = OnceLock::new();

/// When `TARKA_LOKI_PUSH_URL` / `LOKI_PUSH_URL` is set, returns a writer that tees to Loki.
/// Otherwise returns plain stdout.
pub fn stdout_or_loki_tee() -> Box<dyn Write + Send> {
    let Some(url) = push_url() else {
        return Box::new(std::io::stdout());
    };

    let q_cap = env_usize("TARKA_LOKI_QUEUE_MAX", DEFAULT_QUEUE).max(64);
    let batch_max = env_usize("TARKA_LOKI_BATCH_MAX", DEFAULT_BATCH_MAX).clamp(1, 200);
    let service = service_name();

    let (tx, rx) = sync_channel::<String>(q_cap);
    let tee_tx = tx.clone();

    let url_clone = url.clone();
    let handle = std::thread::spawn(move || {
        worker_loop(rx, url_clone, service, batch_max);
    });

    let guard = WorkerGuard {
        _keepalive: tx,
        _handle: handle,
    };
    let _ = LOKI_GUARD.set(guard);

    Box::new(StdoutLokiTee::new(tee_tx))
}
