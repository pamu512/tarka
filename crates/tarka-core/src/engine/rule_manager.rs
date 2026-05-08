//! Hot-reload compiled [`crate::compiler::RuleSet`] protobuf bundles from a watched directory (`.bin`).
//!
//! Requests call [`RuleManager::active_snapshot`] and hold the returned [`std::sync::Arc`] for their
//! duration. [`ArcSwap`] swaps the active snapshot atomically; in-flight requests keep the previous
//! [`Arc`] alive until they finish (RCU-style, no torn reads).
//!
//! # Dead-man's switch (fail-over)
//!
//! A failed load **never** panics and **never** leaves the engine without a coherent snapshot:
//!
//! - **Partial `.bin` corruption**: decodable bundles are merged; undecodable files are skipped.
//!   A **CRITICAL** alert records each failure (structured tracing + optional hook).
//! - **Total load failure** while a previous **audited** snapshot exists: the engine **retains**
//!   the last-known-good snapshot (no swap).
//! - **Total load failure** with **no** audited history (cold start): the engine activates a
//!   **fail-safe** snapshot — empty rule list with [`RuleAuditMode::FailSafeUnAudited`]. Downstream
//!   must treat decisions as permissive and **flag as un-audited** (contractual; see
//!   [`LoadedRuleSnapshot::audit_mode`]).
//!
//! CRITICAL alerts are emitted via `tracing` (`target = "tarka.rule_manager.critical"`,
//! field `alert_severity = "CRITICAL"`) and optionally through [`RuleManagerOptions::on_critical_alert`].

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::Duration;

use arc_swap::ArcSwap;
use notify::Watcher;
use prost::Message;
use thiserror::Error;
use tracing::{error, warn};

use crate::compiler::RuleSet;

/// Whether rules were loaded from trusted artifacts or the fail-safe path is active.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum RuleAuditMode {
    /// Rules came from successfully decoded bundles (possibly partial if some files failed).
    Audited,
    /// No valid audited bundle was ever loaded; engine is in permissive fail-open mode.
    /// Downstream **must** flag outcomes as un-audited and escalate monitoring.
    FailSafeUnAudited,
}

/// Immutable snapshot of all merged `*.bin` rule sets in the watched directory.
#[derive(Clone, Debug, PartialEq)]
pub struct LoadedRuleSnapshot {
    /// Single merged [`RuleSet`] (rules combined from every successfully decoded `.bin`, last writer wins on duplicate `id`).
    pub merged: RuleSet,
    /// Sorted paths that contributed to `merged` (for audit).
    pub source_paths: Vec<PathBuf>,
    /// Audit posture for downstream enforcement / reporting.
    pub audit_mode: RuleAuditMode,
}

impl LoadedRuleSnapshot {
    /// Fail-safe snapshot: no compiled rules; [`RuleAuditMode::FailSafeUnAudited`].
    /// Embedders should interpret “no blocking rules” plus un-audited as **allow with escalation**.
    pub fn fail_safe_unaudited() -> Self {
        Self {
            merged: RuleSet {
                version: 0,
                rules: Vec::new(),
            },
            source_paths: Vec::new(),
            audit_mode: RuleAuditMode::FailSafeUnAudited,
        }
    }

    fn audited(merged: RuleSet, source_paths: Vec<PathBuf>) -> Self {
        Self {
            merged,
            source_paths,
            audit_mode: RuleAuditMode::Audited,
        }
    }
}

#[derive(Debug, Error)]
pub enum RuleManagerError {
    #[error("io error on rule directory {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("failed to decode RuleSet protobuf from {path}: {source}")]
    Decode {
        path: PathBuf,
        #[source]
        source: prost::DecodeError,
    },
    #[error("notify watcher error: {0}")]
    Notify(#[from] notify::Error),
}

/// Result of scanning a directory: merged successful bundles plus per-file errors (best-effort).
#[derive(Debug)]
pub struct DirectoryScanResult {
    pub merged: RuleSet,
    pub contributing_paths: Vec<PathBuf>,
    pub file_errors: Vec<(PathBuf, RuleManagerError)>,
}

/// Payload for CRITICAL operational alerts (structured logs + optional application hook).
#[derive(Clone, Debug)]
pub struct CriticalRuleLoadAlert {
    pub directory: PathBuf,
    pub summary: String,
    pub reason: CriticalAlertReason,
}

/// Classification for alerting / runbooks.
#[derive(Clone, Debug)]
#[non_exhaustive]
pub enum CriticalAlertReason {
    /// One or more `.bin` files could not be used; remaining bundles were merged when possible.
    PartialOrTotalDecodeFailures { errors: Vec<(PathBuf, String)> },
    /// Directory listing or top-level IO failed.
    DirectoryScanFailed { detail: String },
    /// Load did not yield an audited bundle; engine retained last-known-good.
    RetainedLastKnownGood { detail: String },
    /// Cold start or total loss of audited bundles; fail-safe snapshot is active.
    FailSafeActivated { detail: String },
}

impl CriticalRuleLoadAlert {
    /// Severity label for log collectors (ELK / Datadog); always `"CRITICAL"` for this type.
    pub const ALERT_SEVERITY: &'static str = "CRITICAL";
}

/// Outcome of [`RuleManager::reload_now`].
#[derive(Debug)]
pub enum ReloadOutcome {
    /// A new snapshot was stored (audited or fail-safe).
    Applied(Arc<LoadedRuleSnapshot>),
    /// Load failed; the previous [`Arc`] from [`RuleManager::active_snapshot`] is unchanged.
    Retained {
        previous: Arc<LoadedRuleSnapshot>,
        alert: CriticalRuleLoadAlert,
    },
}

/// Options for [`RuleManager::watch_directory_with_options`].
pub struct RuleManagerOptions {
    pub directory: PathBuf,
    /// Called for every CRITICAL rule-load incident (in addition to structured `tracing`).
    /// Use this to POST to an internal ops API with bounded timeouts in the callback.
    pub on_critical_alert: Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>>,
}

impl RuleManagerOptions {
    pub fn new(directory: impl Into<PathBuf>) -> Self {
        Self {
            directory: directory.into(),
            on_critical_alert: None,
        }
    }
}

/// Watches a directory for `*.bin` files and atomically publishes merged [`LoadedRuleSnapshot`] values.
pub struct RuleManager {
    dir: PathBuf,
    swap: Arc<ArcSwap<LoadedRuleSnapshot>>,
    /// Last snapshot that was stored with [`RuleAuditMode::Audited`] (for dead-man's retention).
    last_audited: Arc<Mutex<Option<Arc<LoadedRuleSnapshot>>>>,
    on_critical_alert: Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<()>>,
}

impl RuleManager {
    /// Load `*.bin` once and start a background watcher that reloads on changes (debounced).
    pub fn watch_directory(dir: impl Into<PathBuf>) -> Result<Self, RuleManagerError> {
        Self::watch_directory_with_options(RuleManagerOptions::new(dir))
    }

    /// Same as [`RuleManager::watch_directory`] with CRITICAL alert hooks.
    pub fn watch_directory_with_options(options: RuleManagerOptions) -> Result<Self, RuleManagerError> {
        let dir = options.directory;
        std::fs::create_dir_all(&dir).map_err(|e| RuleManagerError::Io {
            path: dir.clone(),
            source: e,
        })?;

        let last_audited: Arc<Mutex<Option<Arc<LoadedRuleSnapshot>>>> =
            Arc::new(Mutex::new(None));

        let swap: Arc<ArcSwap<LoadedRuleSnapshot>> =
            Arc::new(ArcSwap::new(initial_snapshot(
                &dir,
                Arc::clone(&last_audited),
                &options.on_critical_alert,
            )));

        let stop = Arc::new(AtomicBool::new(false));
        let swap_thread = Arc::clone(&swap);
        let dir_thread = dir.clone();
        let stop_thread = Arc::clone(&stop);
        let last_thread = Arc::clone(&last_audited);
        let hook_thread = options.on_critical_alert.clone();

        let join = Some(std::thread::spawn(move || {
            watch_loop(
                dir_thread,
                swap_thread,
                last_thread,
                hook_thread,
                stop_thread,
            );
        }));

        Ok(Self {
            dir,
            swap,
            last_audited,
            on_critical_alert: options.on_critical_alert,
            stop,
            join,
        })
    }

    /// Snapshot at request start — hold this [`Arc`] until the request completes so reloads cannot
    /// invalidate in-flight evaluation state.
    #[must_use]
    pub fn active_snapshot(&self) -> Arc<LoadedRuleSnapshot> {
        self.swap.load_full()
    }

    /// Directory whose `.bin` files are merged.
    #[inline]
    pub fn watched_directory(&self) -> &Path {
        &self.dir
    }

    /// Last audited snapshot known to this manager (for health checks / debugging).
    pub fn last_audited_snapshot(&self) -> Option<Arc<LoadedRuleSnapshot>> {
        self.last_audited.lock().unwrap().clone()
    }

    /// Force a synchronous rescan with dead-man's switch semantics.
    pub fn reload_now(&self) -> ReloadOutcome {
        match scan_merge_directory(&self.dir) {
            Ok(scan) => {
                let last_guard = self.last_audited.lock().unwrap();
                let last_ref = last_guard.as_ref().map(|x| x.as_ref());
                match resolve_scan(&self.dir, scan, last_ref, &self.on_critical_alert) {
                    ScanResolution::Store(arc) => {
                        drop(last_guard);
                        if arc.audit_mode == RuleAuditMode::Audited {
                            *self.last_audited.lock().unwrap() = Some(Arc::clone(&arc));
                        }
                        self.swap.store(Arc::clone(&arc));
                        ReloadOutcome::Applied(arc)
                    }
                    ScanResolution::Retain(alert) => {
                        let prev = self.swap.load_full();
                        drop(last_guard);
                        ReloadOutcome::Retained {
                            previous: prev,
                            alert,
                        }
                    }
                }
            }
            Err(e) => {
                let alert = CriticalRuleLoadAlert {
                    directory: self.dir.clone(),
                    summary: "rule directory could not be scanned".to_string(),
                    reason: CriticalAlertReason::DirectoryScanFailed {
                        detail: e.to_string(),
                    },
                };
                emit_critical_alert(&self.on_critical_alert, &alert);
                ReloadOutcome::Retained {
                    previous: self.swap.load_full(),
                    alert,
                }
            }
        }
    }

    /// Stop the watcher thread (joins on drop).
    pub fn shutdown(mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}

impl Drop for RuleManager {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(j) = self.join.take() {
            let _ = j.join();
        }
    }
}

enum ScanResolution {
    Store(Arc<LoadedRuleSnapshot>),
    Retain(CriticalRuleLoadAlert),
}

fn initial_snapshot(
    dir: &Path,
    last_audited: Arc<Mutex<Option<Arc<LoadedRuleSnapshot>>>>,
    hook: &Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>>,
) -> Arc<LoadedRuleSnapshot> {
    match scan_merge_directory(dir) {
        Ok(scan) => match resolve_scan(dir, scan, None, hook) {
            ScanResolution::Store(arc) => {
                if arc.audit_mode == RuleAuditMode::Audited {
                    *last_audited.lock().unwrap() = Some(Arc::clone(&arc));
                }
                arc
            }
            // Defensive: initial load has no retention baseline; resolve_scan should only Store.
            ScanResolution::Retain(_) => Arc::new(LoadedRuleSnapshot::fail_safe_unaudited()),
        },
        Err(e) => {
            let alert = CriticalRuleLoadAlert {
                directory: dir.to_path_buf(),
                summary: "initial rule directory scan failed; activating fail-safe".to_string(),
                reason: CriticalAlertReason::DirectoryScanFailed {
                    detail: e.to_string(),
                },
            };
            emit_critical_alert(hook, &alert);
            Arc::new(LoadedRuleSnapshot::fail_safe_unaudited())
        }
    }
}

fn resolve_scan(
    directory: &Path,
    scan: DirectoryScanResult,
    last_audited_good: Option<&LoadedRuleSnapshot>,
    hook: &Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>>,
) -> ScanResolution {
    if is_audited_load(&scan) {
        if !scan.file_errors.is_empty() {
            let alert = CriticalRuleLoadAlert {
                directory: directory.to_path_buf(),
                summary: "one or more rule bundles skipped; merged remaining files".to_string(),
                reason: CriticalAlertReason::PartialOrTotalDecodeFailures {
                    errors: scan
                        .file_errors
                        .iter()
                        .map(|(p, e)| (p.clone(), e.to_string()))
                        .collect(),
                },
            };
            emit_critical_alert(hook, &alert);
        }
        let snap = Arc::new(LoadedRuleSnapshot::audited(scan.merged, scan.contributing_paths));
        return ScanResolution::Store(snap);
    }

    let detail = summarize_scan_failure(&scan);
    if last_audited_good.is_some() {
        let alert = CriticalRuleLoadAlert {
            directory: directory.to_path_buf(),
            summary: "rule reload failed; retaining last-known-good audited snapshot".to_string(),
            reason: CriticalAlertReason::RetainedLastKnownGood {
                detail,
            },
        };
        emit_critical_alert(hook, &alert);
        return ScanResolution::Retain(alert);
    }

    let alert = CriticalRuleLoadAlert {
        directory: directory.to_path_buf(),
        summary: "no audited rule bundle available; activating fail-safe (un-audited)".to_string(),
        reason: CriticalAlertReason::FailSafeActivated { detail },
    };
    emit_critical_alert(hook, &alert);
    ScanResolution::Store(Arc::new(LoadedRuleSnapshot::fail_safe_unaudited()))
}

fn is_audited_load(scan: &DirectoryScanResult) -> bool {
    if !scan.merged.rules.is_empty() {
        return true;
    }
    !scan.contributing_paths.is_empty() && scan.file_errors.is_empty()
}

fn summarize_scan_failure(scan: &DirectoryScanResult) -> String {
    if scan.file_errors.is_empty() {
        return "no rule bundles produced an audited RuleSet (empty directory or unusable inputs)".to_string();
    }
    format!(
        "{} file(s) failed to decode or read",
        scan.file_errors.len()
    )
}

fn emit_critical_alert(
    hook: &Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>>,
    alert: &CriticalRuleLoadAlert,
) {
    error!(
        target: "tarka.rule_manager.critical",
        alert_severity = CriticalRuleLoadAlert::ALERT_SEVERITY,
        directory = %alert.directory.display(),
        summary = %alert.summary,
        reason = ?alert.reason,
        "rule_load_critical_alert"
    );
    if let Some(h) = hook {
        h(alert.clone());
    }
}

fn watch_loop(
    dir: PathBuf,
    swap: Arc<ArcSwap<LoadedRuleSnapshot>>,
    last_audited: Arc<Mutex<Option<Arc<LoadedRuleSnapshot>>>>,
    hook: Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>>,
    stop: Arc<AtomicBool>,
) {
    let (tx, rx) = std::sync::mpsc::channel();

    let mut watcher = match notify::recommended_watcher(move |res| {
        let _ = tx.send(res);
    }) {
        Ok(w) => w,
        Err(e) => {
            warn!(target: "tarka.rule_manager", "notify watcher failed to start: {e}");
            return;
        }
    };

    if let Err(e) = watcher.watch(&dir, notify::RecursiveMode::NonRecursive) {
        warn!(
            target: "tarka.rule_manager",
            "notify watch failed on {}: {e}",
            dir.display()
        );
        return;
    }

    loop {
        if stop.load(Ordering::SeqCst) {
            break;
        }
        match rx.recv_timeout(Duration::from_millis(400)) {
            Ok(Ok(_event)) => {
                debounce_rescan(&rx);
                match scan_merge_directory(&dir) {
                    Ok(scan) => {
                        let last_ref = last_audited.lock().unwrap();
                        let last_good = last_ref.as_ref().map(|x| x.as_ref());
                        match resolve_scan(&dir, scan, last_good, &hook) {
                            ScanResolution::Store(arc) => {
                                drop(last_ref);
                                if arc.audit_mode == RuleAuditMode::Audited {
                                    *last_audited.lock().unwrap() = Some(Arc::clone(&arc));
                                }
                                swap.store(arc);
                            }
                            ScanResolution::Retain(_) => {
                                // swap unchanged; alert already emitted inside resolve_scan
                            }
                        }
                    }
                    Err(e) => {
                        let alert = CriticalRuleLoadAlert {
                            directory: dir.clone(),
                            summary: "rule directory scan failed during watch".to_string(),
                            reason: CriticalAlertReason::DirectoryScanFailed {
                                detail: e.to_string(),
                            },
                        };
                        emit_critical_alert(&hook, &alert);
                    }
                }
            }
            Ok(Err(e)) => {
                warn!(target: "tarka.rule_manager", "notify stream error: {e}");
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}

/// Drain rapid-fire notify events then reload once (coalesces editor saves).
fn debounce_rescan(rx: &std::sync::mpsc::Receiver<Result<notify::Event, notify::Error>>) {
    std::thread::sleep(Duration::from_millis(75));
    loop {
        match rx.recv_timeout(Duration::from_millis(0)) {
            Ok(Ok(_)) | Ok(Err(_)) => continue,
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => break,
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
}

/// Best-effort directory scan: merges every decodable `*.bin`; file-level failures are collected.
pub fn scan_merge_directory(dir: &Path) -> Result<DirectoryScanResult, RuleManagerError> {
    let mut paths: Vec<PathBuf> = std::fs::read_dir(dir)
        .map_err(|e| RuleManagerError::Io {
            path: dir.to_path_buf(),
            source: e,
        })?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("bin"))
        .collect();
    paths.sort();

    let mut version_max: u32 = 0;
    let mut by_id: HashMap<String, crate::compiler::CompiledRule> = HashMap::new();
    let mut contributing_paths: Vec<PathBuf> = Vec::new();
    let mut file_errors: Vec<(PathBuf, RuleManagerError)> = Vec::new();

    for path in &paths {
        let bytes = match std::fs::read(path) {
            Ok(b) => b,
            Err(e) => {
                file_errors.push((
                    path.clone(),
                    RuleManagerError::Io {
                        path: path.clone(),
                        source: e,
                    },
                ));
                continue;
            }
        };
        match RuleSet::decode(bytes.as_slice()) {
            Ok(rs) => {
                version_max = version_max.max(rs.version);
                contributing_paths.push(path.clone());
                for rule in rs.rules {
                    by_id.insert(rule.id.clone(), rule);
                }
            }
            Err(e) => {
                file_errors.push((
                    path.clone(),
                    RuleManagerError::Decode {
                        path: path.clone(),
                        source: e,
                    },
                ));
            }
        }
    }

    contributing_paths.sort();

    let mut merged_rules: Vec<crate::compiler::CompiledRule> = by_id.into_values().collect();
    merged_rules.sort_by(|a, b| a.id.cmp(&b.id));

    Ok(DirectoryScanResult {
        merged: RuleSet {
            version: version_max,
            rules: merged_rules,
        },
        contributing_paths,
        file_errors,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Barrier;

    fn encode_rs(id: &str, ver: u32) -> Vec<u8> {
        let rs = RuleSet {
            version: ver,
            rules: vec![crate::compiler::CompiledRule {
                id: id.into(),
                expression: None,
            }],
        };
        let mut buf = Vec::new();
        rs.encode(&mut buf).unwrap();
        buf
    }

    #[test]
    fn merge_prefers_later_file_on_duplicate_id() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("a.bin"), encode_rs("dup", 1)).unwrap();
        std::fs::write(dir.path().join("z.bin"), encode_rs("dup", 2)).unwrap();
        let scan = scan_merge_directory(dir.path()).unwrap();
        assert_eq!(scan.merged.version, 2);
        assert_eq!(scan.merged.rules.len(), 1);
        assert_eq!(scan.merged.rules[0].id, "dup");
        assert_eq!(scan.contributing_paths.len(), 2);
    }

    #[test]
    fn corrupt_bin_skipped_good_retained() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("good.bin"), encode_rs("ok", 1)).unwrap();
        std::fs::write(dir.path().join("bad.bin"), b"not protobuf".to_vec()).unwrap();
        let scan = scan_merge_directory(dir.path()).unwrap();
        assert_eq!(scan.merged.rules.len(), 1);
        assert_eq!(scan.file_errors.len(), 1);
        assert!(is_audited_load(&scan));
    }

    #[test]
    fn resolve_retains_last_good_when_all_corrupt() {
        let dir = tempfile::tempdir().unwrap();
        let good = LoadedRuleSnapshot::audited(
            RuleSet {
                version: 7,
                rules: vec![crate::compiler::CompiledRule {
                    id: "x".into(),
                    expression: None,
                }],
            },
            vec![dir.path().join("legacy.bin")],
        );
        std::fs::write(dir.path().join("bad.bin"), b"nope").unwrap();
        let scan = scan_merge_directory(dir.path()).unwrap();
        assert!(!is_audited_load(&scan));
        let hook: Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>> = None;
        match resolve_scan(dir.path(), scan, Some(&good), &hook) {
            ScanResolution::Retain(_) => {}
            _ => panic!("expected retain"),
        }
    }

    #[test]
    fn resolve_failsafe_when_no_good_history() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("bad.bin"), b"nope").unwrap();
        let scan = scan_merge_directory(dir.path()).unwrap();
        let hook: Option<Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync>> = None;
        match resolve_scan(dir.path(), scan, None, &hook) {
            ScanResolution::Store(arc) => {
                assert_eq!(arc.audit_mode, RuleAuditMode::FailSafeUnAudited);
            }
            _ => panic!("expected fail-safe store"),
        }
    }

    #[test]
    fn critical_hook_invoked_on_partial() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("good.bin"), encode_rs("ok", 1)).unwrap();
        std::fs::write(dir.path().join("bad.bin"), b"x").unwrap();
        let scan = scan_merge_directory(dir.path()).unwrap();
        let count = Arc::new(AtomicUsize::new(0));
        let c2 = Arc::clone(&count);
        let hook: Arc<dyn Fn(CriticalRuleLoadAlert) + Send + Sync> =
            Arc::new(move |_a| {
                c2.fetch_add(1, Ordering::SeqCst);
            });
        match resolve_scan(dir.path(), scan, None, &Some(hook)) {
            ScanResolution::Store(arc) => {
                assert_eq!(arc.audit_mode, RuleAuditMode::Audited);
            }
            _ => panic!("expected store"),
        }
        assert_eq!(count.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn active_snapshot_survives_swap() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join("r.bin"), encode_rs("only", 1)).unwrap();

        let swap: Arc<ArcSwap<LoadedRuleSnapshot>> = Arc::new(ArcSwap::new(Arc::new(
            LoadedRuleSnapshot::audited(scan_merge_directory(dir.path()).unwrap().merged, vec![]),
        )));

        let old = swap.load_full();
        assert_eq!(old.merged.rules.len(), 1);

        std::fs::write(dir.path().join("r.bin"), encode_rs("only", 99)).unwrap();
        let scan = scan_merge_directory(dir.path()).unwrap();
        swap.store(Arc::new(LoadedRuleSnapshot::audited(scan.merged, scan.contributing_paths)));

        assert_eq!(old.merged.version, 1);
        let new = swap.load_full();
        assert_eq!(new.merged.version, 99);
    }

    #[test]
    fn concurrent_readers_hold_old_arc() {
        let swap: Arc<ArcSwap<LoadedRuleSnapshot>> = Arc::new(ArcSwap::new(Arc::new(
            LoadedRuleSnapshot::audited(
                RuleSet {
                    version: 0,
                    rules: vec![],
                },
                vec![],
            ),
        )));
        let barrier = Arc::new(Barrier::new(2));
        let b2 = Arc::clone(&barrier);
        let swap_t = Arc::clone(&swap);
        let h = std::thread::spawn(move || {
            let snap = swap_t.load_full();
            b2.wait();
            std::thread::sleep(Duration::from_millis(50));
            assert_eq!(snap.merged.version, 0);
        });

        barrier.wait();
        swap.store(Arc::new(LoadedRuleSnapshot::audited(
            RuleSet {
                version: 42,
                rules: vec![],
            },
            vec![],
        )));

        h.join().unwrap();
        assert_eq!(swap.load_full().merged.version, 42);
    }
}
