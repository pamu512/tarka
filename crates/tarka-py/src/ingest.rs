//! Token-bucket admission + bounded concurrency for evidence evaluation (PyO3 ingress).
//!
//! On Unix, the first use of the ingestion gate installs a **`SIGTERM` / `SIGINT`** handler: an atomic
//! flag stops new admissions while in-flight evaluations (guarded by `IngestGuard`) finish within
//! `SHUTDOWN_GRACE_SECS`, returning protobuf manifests to Python before process exit.
//!
//! Configuration is read once at process start (first use of the ingestion gate in ``tarka-py``).
//! When buffer capacity is `0`, all limiting is disabled.
//!
//! | Variable | Meaning | Default |
//! |----------|---------|---------|
//! | `TARKA_INGEST_BUFFER_CAPACITY` | Max concurrent evaluations (`0` = disable gate) | 256 |
//! | `TARKA_INGEST_TOKEN_REFILL_PER_SEC` | Sustained admission rate; `0` disables token bucket only | 500 |
//! | `TARKA_INGEST_TOKEN_BURST` | Governor burst (max tokens); must be ≥ 1 when limiter is enabled | 1000 |
//!
//! When in-flight work exceeds [`BUFFER_PRESSURE_PERCENT`]% of capacity, new admissions fail with
//! buffer backpressure (before the hard capacity bound).

use governor::{
    clock::{Clock, DefaultClock},
    middleware::NoOpMiddleware,
    state::InMemoryState,
    Quota, RateLimiter,
};
use serde::Serialize;
use std::fmt;
use std::num::NonZeroU32;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

/// Environment: max concurrent evaluations (`0` = disable gate entirely).
pub const ENV_BUFFER_CAPACITY: &str = "TARKA_INGEST_BUFFER_CAPACITY";
/// Environment: sustained admission rate in tokens per second (`0` = skip token bucket; buffer limits still apply).
pub const ENV_TOKEN_REFILL_PER_SEC: &str = "TARKA_INGEST_TOKEN_REFILL_PER_SEC";
/// Environment: maximum burst (bucket capacity) for the governor.
pub const ENV_TOKEN_BURST: &str = "TARKA_INGEST_TOKEN_BURST";

/// Default capacity when env is unset (256 concurrent evaluations).
pub const DEFAULT_BUFFER_CAPACITY: usize = 256;
/// Default refill rate: 500 evaluations started per second (sustained).
pub const DEFAULT_TOKEN_REFILL_PER_SEC: u32 = 500;
/// Default burst: up to 1000 concurrent admissions without waiting for refill.
pub const DEFAULT_TOKEN_BURST: u32 = 1000;

/// Fraction of buffer occupancy above which new admissions are rejected (80%).
pub const BUFFER_PRESSURE_PERCENT: u128 = 80;

/// Grace period after SIGTERM (Unix) to let in-flight evaluations finish so manifests reach Python.
pub const SHUTDOWN_GRACE_SECS: u64 = 10;

type GovLimiter = RateLimiter<
    governor::state::direct::NotKeyed,
    InMemoryState,
    DefaultClock,
    NoOpMiddleware,
>;

/// Admission denial prior to incrementing in-flight work.
#[derive(Debug)]
pub enum IngestDeny {
    BufferPressure {
        in_flight: usize,
        capacity: usize,
    },
    RateLimited {
        retry_after: Duration,
    },
    /// Process is shutting down (SIGTERM); new evaluations are not admitted so in-flight work can drain.
    ShuttingDown,
}

impl fmt::Display for IngestDeny {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            IngestDeny::BufferPressure {
                in_flight,
                capacity,
            } => write!(
                f,
                "buffer_pressure (in_flight={in_flight}, capacity={capacity}, threshold_percent={BUFFER_PRESSURE_PERCENT})"
            ),
            IngestDeny::RateLimited { retry_after } => {
                write!(f, "rate_limited (retry_after={retry_after:?})")
            }
            IngestDeny::ShuttingDown => {
                write!(f, "shutting_down (engine not accepting new evaluations)")
            }
        }
    }
}

/// RAII guard: decrements in-flight counter when dropped.
pub struct IngestGuard {
    gate: Arc<IngestGateInner>,
    active: bool,
}

impl Drop for IngestGuard {
    fn drop(&mut self) {
        if self.active && self.gate.capacity > 0 {
            self.gate.in_flight.fetch_sub(1, Ordering::AcqRel);
        }
    }
}

pub struct IngestGate {
    inner: Arc<IngestGateInner>,
}

pub(crate) struct IngestGateInner {
    capacity: usize,
    in_flight: AtomicUsize,
    /// When `false`, [`IngestGate::try_enter`] rejects so buffered in-flight work can drain to Python.
    accepting: AtomicBool,
    limiter: Option<Arc<GovLimiter>>,
    refill_per_sec: u32,
}

impl IngestGate {
    pub fn from_env_first_call() -> Self {
        Self {
            inner: Arc::new(load_gate_from_env()),
        }
    }

    pub(crate) fn inner_arc(&self) -> Arc<IngestGateInner> {
        Arc::clone(&self.inner)
    }

    /// Whether new evaluations are admitted (`false` after SIGTERM on Unix until process exit).
    pub fn accepting_new_requests(&self) -> bool {
        self.inner.accepting.load(Ordering::Acquire)
    }

    /// Try to admit one evaluation. On success, caller must hold [`IngestGuard`] until work completes.
    pub fn try_enter(&self) -> Result<IngestGuard, IngestDeny> {
        let g = &self.inner;
        if !g.accepting.load(Ordering::Acquire) {
            return Err(IngestDeny::ShuttingDown);
        }
        if g.capacity == 0 {
            return Ok(IngestGuard {
                gate: Arc::clone(g),
                active: false,
            });
        }

        if let Some(lim) = &g.limiter {
            match lim.check() {
                Ok(()) => {}
                Err(not_until) => {
                    let retry_after = retry_after_from_not_until(not_until);
                    return Err(IngestDeny::RateLimited { retry_after });
                }
            }
        }

        loop {
            let cur = g.in_flight.load(Ordering::Acquire);
            // Reject when strictly past high-water mark (80% of capacity).
            if (cur as u128) * 100 > (g.capacity as u128) * BUFFER_PRESSURE_PERCENT {
                return Err(IngestDeny::BufferPressure {
                    in_flight: cur,
                    capacity: g.capacity,
                });
            }
            if cur >= g.capacity {
                return Err(IngestDeny::BufferPressure {
                    in_flight: cur,
                    capacity: g.capacity,
                });
            }
            if g
                .in_flight
                .compare_exchange_weak(cur, cur + 1, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                return Ok(IngestGuard {
                    gate: Arc::clone(g),
                    active: true,
                });
            }
        }
    }

    /// Current in-flight count (for metrics/tests).
    pub fn in_flight(&self) -> usize {
        if self.inner.capacity == 0 {
            return 0;
        }
        self.inner.in_flight.load(Ordering::Relaxed)
    }

    pub fn capacity(&self) -> usize {
        self.inner.capacity
    }

    /// Sustained token refill rate (0 = token bucket disabled).
    pub fn token_refill_per_sec(&self) -> u32 {
        self.inner.refill_per_sec
    }
}

fn load_gate_from_env() -> IngestGateInner {
    let capacity = parse_usize_env(ENV_BUFFER_CAPACITY).unwrap_or(DEFAULT_BUFFER_CAPACITY);
    let refill = parse_u32_env(ENV_TOKEN_REFILL_PER_SEC).unwrap_or(DEFAULT_TOKEN_REFILL_PER_SEC);
    let burst = parse_u32_env(ENV_TOKEN_BURST).unwrap_or(DEFAULT_TOKEN_BURST);

    if capacity == 0 {
        return IngestGateInner {
            capacity: 0,
            in_flight: AtomicUsize::new(0),
            accepting: AtomicBool::new(true),
            limiter: None,
            refill_per_sec: refill,
        };
    }

    let limiter = if refill == 0 {
        None
    } else {
        let nz_refill = NonZeroU32::new(refill).expect("refill > 0 when limiter enabled");
        let nz_burst = NonZeroU32::new(burst.max(1)).expect("burst >= 1");
        let quota = Quota::per_second(nz_refill).allow_burst(nz_burst);
        Some(Arc::new(RateLimiter::direct(quota)))
    };

    IngestGateInner {
        capacity,
        in_flight: AtomicUsize::new(0),
        accepting: AtomicBool::new(true),
        limiter,
        refill_per_sec: refill,
    }
}

fn parse_usize_env(key: &str) -> Option<usize> {
    std::env::var_os(key).and_then(|v| v.into_string().ok()?.parse().ok())
}

fn parse_u32_env(key: &str) -> Option<u32> {
    std::env::var_os(key).and_then(|v| v.into_string().ok()?.parse().ok())
}

fn retry_after_from_not_until(
    n: governor::NotUntil<<DefaultClock as Clock>::Instant>,
) -> Duration {
    n.wait_time_from(DefaultClock::default().now())
}

#[derive(Serialize)]
pub struct BackpressurePayload<'a> {
    pub kind: &'a str,
    pub retry_after_ms: u64,
    pub reason_codes: [&'a str; 1],
}

pub fn backpressure_json(deny: &IngestDeny) -> String {
    let (kind, retry_after_ms, code) = match deny {
        IngestDeny::BufferPressure { .. } => (
            "buffer_pressure",
            50_u64,
            "tarka.ingest.buffer_pressure",
        ),
        IngestDeny::RateLimited { retry_after } => {
            let ms = retry_after.as_millis().min(u128::from(u64::MAX)) as u64;
            let ms = ms.max(1);
            ("rate_limited", ms, "tarka.ingest.rate_limited")
        }
        IngestDeny::ShuttingDown => (
            "shutting_down",
            0_u64,
            "tarka.ingest.shutting_down",
        ),
    };
    let payload = BackpressurePayload {
        kind,
        retry_after_ms,
        reason_codes: [code],
    };
    serde_json::to_string(&payload).unwrap_or_else(|_| {
        format!(
            "{{\"kind\":\"{kind}\",\"retry_after_ms\":{retry_after_ms},\"reason_codes\":[\"{code}\"]}}"
        )
    })
}

/// Install `SIGTERM` / `SIGINT` handlers (Unix): atomically stop new admissions, then wait up to
/// [`SHUTDOWN_GRACE_SECS`] so in-flight evaluations finish and return protobuf manifests to Python.
#[cfg(unix)]
pub(crate) fn spawn_shutdown_signal_handler(inner: Arc<IngestGateInner>) {
    if std::thread::Builder::new()
        .name("tarka-ingest-shutdown".into())
        .spawn(move || {
            let rt = match tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            {
                Ok(rt) => rt,
                Err(e) => {
                    eprintln!("tarka-py: failed to build tokio runtime for signal handler: {e}");
                    return;
                }
            };
            rt.block_on(run_shutdown_sequence(inner));
        })
        .is_err()
    {
        eprintln!("tarka-py: failed to spawn SIGTERM/SIGINT handler thread");
    }
}

#[cfg(not(unix))]
pub(crate) fn spawn_shutdown_signal_handler(_inner: Arc<IngestGateInner>) {}

#[cfg(unix)]
async fn run_shutdown_sequence(inner: Arc<IngestGateInner>) {
    use tokio::signal::unix::{signal, SignalKind};

    let mut sigterm = match signal(SignalKind::terminate()) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("tarka-py: register SIGTERM failed: {e}");
            return;
        }
    };
    let mut sigint = match signal(SignalKind::interrupt()) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("tarka-py: register SIGINT failed: {e}");
            return;
        }
    };

    tokio::select! {
        _ = sigterm.recv() => {}
        _ = sigint.recv() => {}
    }

    inner.accepting.store(false, Ordering::SeqCst);
    eprintln!(
        "tarka-py: shutdown signal received; draining in-flight evaluations for up to {SHUTDOWN_GRACE_SECS}s (EvidenceManifest → Python)"
    );

    let grace = Duration::from_secs(SHUTDOWN_GRACE_SECS);
    let start = std::time::Instant::now();

    loop {
        let inflight = inner.in_flight.load(Ordering::Acquire);
        if inflight == 0 {
            eprintln!("tarka-py: in-flight evaluations drained");
            break;
        }
        if start.elapsed() >= grace {
            eprintln!(
                "tarka-py: shutdown grace elapsed with {inflight} evaluation(s) still in-flight"
            );
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

#[cfg(test)]
impl IngestGate {
    fn set_accepting_for_test(&self, accepting: bool) {
        self.inner
            .accepting
            .store(accepting, Ordering::SeqCst);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Barrier, Mutex};

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn gate_disabled_when_capacity_zero() {
        let _lock = ENV_LOCK.lock().expect("env test lock");
        std::env::remove_var(ENV_TOKEN_REFILL_PER_SEC);
        std::env::remove_var(ENV_TOKEN_BURST);
        std::env::set_var(ENV_BUFFER_CAPACITY, "0");
        let inner = load_gate_from_env();
        std::env::remove_var(ENV_BUFFER_CAPACITY);
        assert_eq!(inner.capacity, 0);
        let gate = IngestGate {
            inner: Arc::new(inner),
        };
        let g = gate.try_enter().expect("enter");
        drop(g);
    }

    #[test]
    fn buffer_pressure_at_high_water() {
        let _lock = ENV_LOCK.lock().expect("env test lock");
        std::env::set_var(ENV_TOKEN_REFILL_PER_SEC, "0");
        std::env::remove_var(ENV_TOKEN_BURST);
        std::env::set_var(ENV_BUFFER_CAPACITY, "10");
        let inner = load_gate_from_env();
        std::env::remove_var(ENV_BUFFER_CAPACITY);
        std::env::remove_var(ENV_TOKEN_REFILL_PER_SEC);
        // threshold: in_flight * 100 > 10 * 80 => > 8, so 9+ rejects
        let gate = IngestGate {
            inner: Arc::new(inner),
        };
        let mut guards = Vec::new();
        for _ in 0..8 {
            guards.push(gate.try_enter().expect("admit"));
        }
        assert_eq!(gate.in_flight(), 8);
        let ninth = gate.try_enter().expect("ninth should succeed (80% not exceeded)");
        guards.push(ninth);
        assert_eq!(gate.in_flight(), 9);
        let err = gate.try_enter().err().expect("tenth should hit buffer pressure");
        match err {
            IngestDeny::BufferPressure { .. } => {}
            IngestDeny::RateLimited { .. } => panic!("unexpected rate limit"),
            IngestDeny::ShuttingDown => panic!("unexpected shutdown"),
        }
        drop(guards);
        assert_eq!(gate.in_flight(), 0);
    }

    #[test]
    fn token_bucket_blocks_sustain_burst() {
        let _lock = ENV_LOCK.lock().expect("env test lock");
        std::env::set_var(ENV_BUFFER_CAPACITY, "10000");
        std::env::set_var(ENV_TOKEN_REFILL_PER_SEC, "2");
        std::env::set_var(ENV_TOKEN_BURST, "3");
        let inner = load_gate_from_env();
        std::env::remove_var(ENV_BUFFER_CAPACITY);
        std::env::remove_var(ENV_TOKEN_REFILL_PER_SEC);
        std::env::remove_var(ENV_TOKEN_BURST);
        let gate = IngestGate {
            inner: Arc::new(inner),
        };
        let _g1 = gate.try_enter().expect("1");
        let _g2 = gate.try_enter().expect("2");
        let _g3 = gate.try_enter().expect("3");
        let err = gate.try_enter().err().expect("4th should rate limit");
        match err {
            IngestDeny::RateLimited { .. } => {}
            other => panic!("expected rate limit got {other}"),
        }
    }

    #[test]
    fn shutting_down_rejects_new_admissions() {
        let _lock = ENV_LOCK.lock().expect("env test lock");
        std::env::set_var(ENV_TOKEN_REFILL_PER_SEC, "0");
        std::env::remove_var(ENV_TOKEN_BURST);
        std::env::set_var(ENV_BUFFER_CAPACITY, "10");
        let inner = load_gate_from_env();
        std::env::remove_var(ENV_BUFFER_CAPACITY);
        std::env::remove_var(ENV_TOKEN_REFILL_PER_SEC);
        let gate = IngestGate {
            inner: Arc::new(inner),
        };
        gate.set_accepting_for_test(false);
        let err = gate.try_enter().err().expect("must reject");
        assert!(matches!(err, IngestDeny::ShuttingDown));
        let json = backpressure_json(&err);
        assert!(json.contains("shutting_down"));
    }

    #[test]
    fn concurrent_admissions_respect_capacity() {
        let _lock = ENV_LOCK.lock().expect("env test lock");
        std::env::set_var(ENV_TOKEN_REFILL_PER_SEC, "0");
        std::env::set_var(ENV_BUFFER_CAPACITY, "5");
        std::env::remove_var(ENV_TOKEN_BURST);
        let inner = load_gate_from_env();
        std::env::remove_var(ENV_BUFFER_CAPACITY);
        std::env::remove_var(ENV_TOKEN_REFILL_PER_SEC);
        let gate = Arc::new(IngestGate {
            inner: Arc::new(inner),
        });
        let barrier = Arc::new(Barrier::new(20));
        let mut handles = vec![];
        for _ in 0..20 {
            let g = Arc::clone(&gate);
            let b = Arc::clone(&barrier);
            handles.push(std::thread::spawn(move || {
                b.wait();
                g.try_enter()
            }));
        }
        let mut oks = 0_u32;
        let mut errs = 0_u32;
        for h in handles {
            match h.join().expect("join") {
                Ok(_) => oks += 1,
                Err(_) => errs += 1,
            }
        }
        assert!(
            oks <= 5,
            "never more than capacity concurrent admissions without release"
        );
        assert!(errs > 0, "some threads should fail admission");
    }
}
