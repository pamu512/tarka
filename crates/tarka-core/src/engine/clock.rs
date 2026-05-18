//! Pluggable wall-clock source for rule evaluation and evidence timestamps.
//!
//! Production uses [`SystemClock`] ([`SystemTime::now`]). **Replay mode** uses [`FixedClock`] so audits can
//! reproduce time-dependent rules (weekends, cut-offs) against a captured instant.

use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// Shared handle installed on [`super::trace::TraceContext`] and [`super::evaluator::Evaluator`].
pub type SharedClock = Arc<dyn Clock>;

/// Wall-clock abstraction ([`SystemTime`]) used for trace capture milliseconds and manifest headers.
pub trait Clock: Send + Sync {
    fn now(&self) -> SystemTime;
}

/// Live wall clock (production).
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> SystemTime {
        SystemTime::now()
    }
}

/// Deterministic clock for audit replay: [`Clock::now`] always returns the same [`SystemTime`].
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FixedClock(SystemTime);

impl FixedClock {
    pub fn new(instant: SystemTime) -> Self {
        Self(instant)
    }

    /// Interprets `ns_since_unix_epoch` as nanoseconds since [`UNIX_EPOCH`] (supports full `u128` range).
    pub fn from_unix_nanos(ns_since_unix_epoch: u128) -> Self {
        Self(unix_nanos_to_system_time(ns_since_unix_epoch))
    }
}

impl Clock for FixedClock {
    fn now(&self) -> SystemTime {
        self.0
    }
}

/// Default production clock installed when callers use [`super::trace::TraceContext::new`].
pub fn system_clock() -> SharedClock {
    Arc::new(SystemClock)
}

pub(crate) fn wall_clock_ms(clock: &dyn Clock) -> u64 {
    clock
        .now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Nanoseconds since Unix epoch for `clock.now()` (for evidence headers).
pub fn unix_nanos_for_clock(clock: &dyn Clock) -> u64 {
    clock
        .now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0)
}

fn unix_nanos_to_system_time(ns: u128) -> SystemTime {
    let d = duration_from_unix_nanos(ns);
    UNIX_EPOCH.checked_add(d).unwrap_or(UNIX_EPOCH)
}

fn duration_from_unix_nanos(ns: u128) -> Duration {
    const NS_PER_S: u128 = 1_000_000_000;
    let secs_u128 = ns / NS_PER_S;
    let nanos = (ns % NS_PER_S) as u32;
    let secs = secs_u128.try_into().unwrap_or(u64::MAX);
    Duration::new(secs, nanos)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fixed_round_trip_unix_ns() {
        let ns: u128 = 1_700_000_000_000_000_000;
        let c = FixedClock::from_unix_nanos(ns);
        assert_eq!(
            c.now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),
            ns
        );
    }
}
