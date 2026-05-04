//! JSON rule evaluation core for Tarka (parity with `decision_api.json_rules`).
//! Parsed packs are cached by content hash (AST cache).

use chrono::{DateTime, NaiveDateTime, TimeZone, Utc};
use parking_lot::Mutex;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use regex::Regex;
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, LazyLock};
use std::time::{Duration, Instant};

const MAX_FIELD_LEN: usize = 128;
const MAX_VALUE_LEN: usize = 1024;
const MAX_RULES_PER_PACK: usize = 200;
const MAX_CONDITIONS_PER_RULE: usize = 20;
const MAX_EVAL_TIME: Duration = Duration::from_millis(50);
const MAX_REGEX_PATTERN_LEN: usize = 256;

static ACTIVE_PACKS_JSON: LazyLock<Mutex<Option<Arc<String>>>> =
    LazyLock::new(|| Mutex::new(None));
static PARSED_CACHE: LazyLock<Mutex<HashMap<String, Arc<Vec<Arc<ParsedPack>>>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

struct ParsedPack {
    source_file: String,
    rules: Vec<Rule>,
    tag_rules: Vec<TagRule>,
    canary_percent: Option<f64>,
    effective_at: Option<DateTime<Utc>>,
}

struct Rule {
    id: String,
    when: Vec<Condition>,
    tags: Vec<String>,
    score_delta: f64,
}

struct TagRule {
    id: String,
    any_tag: Vec<String>,
    tags: Vec<String>,
    score_delta: f64,
}

struct Condition {
    op: String,
    field: String,
    value: Value,
}

fn json_f64(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_i64().map(|i| i as f64))
        .or_else(|| v.as_u64().map(|u| u as f64))
}

/// Approximate ``str(v)`` for JSON scalars (rule DSL parity for ``contains`` / display).
fn json_str_pythonish(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::Null => "None".to_string(),
        _ => v.to_string(),
    }
}

fn parse_effective_at(raw: &str) -> Option<DateTime<Utc>> {
    let s = raw.trim();
    if s.is_empty() {
        return None;
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
        return Some(dt.with_timezone(&Utc));
    }
    let normalized = if let Some(stripped) = s.strip_suffix('Z') {
        format!("{stripped}+00:00")
    } else {
        s.to_string()
    };
    DateTime::parse_from_rfc3339(&normalized)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|| {
            NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S")
                .ok()
                .map(|n| Utc.from_utc_datetime(&n))
        })
}

fn pack_experiment_bucket(tenant_id: &str, entity_id: &str, pack_key: &str) -> i32 {
    let raw = format!("{tenant_id}|{entity_id}|{pack_key}");
    let h = Sha256::digest(raw.as_bytes());
    let prefix: [u8; 4] = h[..4].try_into().unwrap_or([0; 4]);
    let n = u32::from_be_bytes(prefix) % 100;
    n as i32
}

fn pack_should_apply(
    pack: &ParsedPack,
    tenant_id: &str,
    entity_id: &str,
    evaluation_mode: &str,
) -> bool {
    if evaluation_mode == "simulation" {
        return true;
    }
    if evaluation_mode == "challenger" {
        if let Some(eff) = pack.effective_at {
            if Utc::now() < eff {
                return false;
            }
        }
        return true;
    }
    if let Some(eff) = pack.effective_at {
        if Utc::now() < eff {
            return false;
        }
    }
    let cp = match pack.canary_percent {
        Some(p) => p,
        None => return true,
    };
    if cp >= 100.0 {
        return true;
    }
    if cp <= 0.0 {
        return false;
    }
    let key = if !pack.source_file.is_empty() {
        pack.source_file.as_str()
    } else {
        "pack"
    };
    let bucket = pack_experiment_bucket(tenant_id, entity_id, key);
    (bucket as f64) < cp
}

fn match_condition(features: &serde_json::Map<String, Value>, condition: &Condition) -> bool {
    let op = condition.op.as_str();
    let key = &condition.field;
    if key.is_empty() || key.len() > MAX_FIELD_LEN {
        return false;
    }
    let actual = features.get(key);
    let expected = &condition.value;
    if !expected.is_null() && format!("{expected}").len() > MAX_VALUE_LEN {
        return false;
    }
    match op {
        "eq" => actual == Some(expected),
        "not_eq" => actual != Some(expected),
        "gte" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a >= e),
        "gt" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a > e),
        "lte" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a <= e),
        "lt" => actual
            .and_then(json_f64)
            .zip(json_f64(expected))
            .is_some_and(|(a, e)| a < e),
        "in" => expected
            .as_array()
            .is_some_and(|arr| arr.iter().any(|v| Some(v) == actual)),
        "not_in" => expected
            .as_array()
            .map(|arr| !arr.iter().any(|v| Some(v) == actual))
            .unwrap_or(true),
        // Python: str(expected) in str(actual or "")
        "contains" => {
            let exp = json_str_pythonish(expected);
            let act = json_str_pythonish(&actual.cloned().unwrap_or(Value::Null));
            !exp.is_empty() && act.contains(&exp)
        }
        "starts_with" => actual
            .and_then(|a| a.as_str())
            .is_some_and(|a| a.starts_with(expected.as_str().unwrap_or(""))),
        "ends_with" => actual
            .and_then(|a| a.as_str())
            .is_some_and(|a| a.ends_with(expected.as_str().unwrap_or(""))),
        "regex" => {
            let pattern = expected.as_str().unwrap_or("");
            if pattern.is_empty() || pattern.len() > MAX_REGEX_PATTERN_LEN {
                return false;
            }
            let escaped = regex::escape(pattern);
            let safe = format!(
                "(?i)^{}$",
                escaped.replace(r"\*", ".*").replace(r"\?", ".")
            );
            let act = format!("{}", actual.cloned().unwrap_or(Value::Null));
            Regex::new(&safe).map(|re| re.is_match(&act)).unwrap_or(false)
        }
        "is_true" => actual == Some(&Value::Bool(true)),
        "is_false" => actual == Some(&Value::Bool(false)),
        "exists" => actual.is_some(),
        "not_exists" => actual.is_none(),
        _ => false,
    }
}

#[derive(Clone, Serialize)]
struct TelEvent {
    pack_file: String,
    rule_id: String,
    kind: String,
}

fn evaluate_pack(
    pack: &ParsedPack,
    features: &serde_json::Map<String, Value>,
    redis_tags: &[String],
) -> (Vec<String>, Vec<String>, f64, Option<String>, Vec<TelEvent>) {
    let mut hits = Vec::new();
    let mut tags = Vec::new();
    let mut delta = 0.0;
    let mut telemetry: Vec<TelEvent> = Vec::new();
    let t0 = Instant::now();
    let pf_base = pack.source_file.clone();
    for rule in &pack.rules {
        if t0.elapsed() > MAX_EVAL_TIME {
            break;
        }
        if rule.when.is_empty() || rule.when.len() > MAX_CONDITIONS_PER_RULE {
            continue;
        }
        if rule.when.iter().all(|c| match_condition(features, c)) {
            hits.push(rule.id.clone());
            tags.extend(rule.tags.iter().cloned());
            delta += rule.score_delta;
            telemetry.push(TelEvent {
                pack_file: pf_base.clone(),
                rule_id: rule.id.clone(),
                kind: "rule".to_string(),
            });
        }
    }
    let redis_set: HashSet<&str> = redis_tags.iter().map(String::as_str).collect();
    for rule in pack.tag_rules.iter().take(MAX_RULES_PER_PACK) {
        if t0.elapsed() > MAX_EVAL_TIME {
            break;
        }
        let need: HashSet<&str> = rule.any_tag.iter().map(String::as_str).collect();
        if !need.is_empty() && need.iter().any(|t| redis_set.contains(t)) {
            let rid = if rule.id.is_empty() {
                "tagrule"
            } else {
                &rule.id
            };
            hits.push(rid.to_string());
            tags.extend(rule.tags.iter().cloned());
            delta += rule.score_delta;
            telemetry.push(TelEvent {
                pack_file: pf_base.clone(),
                rule_id: rid.to_string(),
                kind: "tag_rule".to_string(),
            });
        }
    }
    let src = pack.source_file.clone();
    let contributing = if hits.is_empty() {
        None
    } else {
        Some(src)
    };
    (hits, tags, delta, contributing, telemetry)
}

/// Parse rule packs from JSON. When `exclude_shadow` is true, packs with mode `shadow` are skipped
/// (production / GitOps sync path). When false, shadow packs are included (adhoc / shadow evaluation).
fn parse_active_packs(arr: &[Value], exclude_shadow: bool) -> Vec<Arc<ParsedPack>> {
    let mut out = Vec::new();
    for v in arr {
        let version = v.get("version").and_then(|x| x.as_u64()).unwrap_or(0);
        if version != 1 {
            continue;
        }
        let mode = v.get("mode").and_then(|x| x.as_str()).unwrap_or("active");
        if mode == "disabled" {
            continue;
        }
        if exclude_shadow && mode == "shadow" {
            continue;
        }
        let source_file = v
            .get("_source_file")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string();
        let canary_percent = v.get("canary_percent").and_then(json_f64);
        let effective_at = v
            .get("effective_at")
            .and_then(|x| x.as_str())
            .and_then(parse_effective_at);
        let rules_json: &[Value] = match v.get("rules").and_then(|x| x.as_array()) {
            Some(r) => r.as_slice(),
            None => &[],
        };
        let mut rules = Vec::new();
        for rule in rules_json.iter().take(MAX_RULES_PER_PACK) {
            let rid = rule
                .get("id")
                .and_then(|x| x.as_str())
                .unwrap_or("unknown")
                .to_string();
            let when = match rule.get("when").and_then(|x| x.as_array()) {
                Some(w) if !w.is_empty() && w.len() <= MAX_CONDITIONS_PER_RULE => w,
                _ => continue,
            };
            let mut conds = Vec::new();
            let mut skip = false;
            for c in when {
                let op = c.get("op").and_then(|x| x.as_str()).unwrap_or("eq").to_string();
                let field = c.get("field").and_then(|x| x.as_str()).unwrap_or("").to_string();
                if field.is_empty() || field.len() > MAX_FIELD_LEN {
                    skip = true;
                    break;
                }
                let value = c.get("value").cloned().unwrap_or(Value::Null);
                conds.push(Condition { op, field, value });
            }
            if skip {
                continue;
            }
            let rule_tags: Vec<String> = rule
                .get("tags")
                .and_then(|x| x.as_array())
                .map(|a| {
                    a.iter()
                        .filter_map(|t| t.as_str().map(|s| s.to_string()))
                        .take(50)
                        .collect()
                })
                .unwrap_or_default();
            let score_delta = rule
                .get("score_delta")
                .and_then(json_f64)
                .unwrap_or(0.0);
            rules.push(Rule {
                id: rid,
                when: conds,
                tags: rule_tags,
                score_delta,
            });
        }
        let mut tag_rules = Vec::new();
        if let Some(tr) = v.get("tag_rules").and_then(|x| x.as_array()) {
            for rule in tr.iter().take(MAX_RULES_PER_PACK) {
                let rid = rule.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string();
                let any_tag: Vec<String> = rule
                    .get("any_tag")
                    .and_then(|x| x.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|t| t.as_str().map(|s| s.to_string()))
                            .take(50)
                            .collect()
                    })
                    .unwrap_or_default();
                let ttags: Vec<String> = rule
                    .get("tags")
                    .and_then(|x| x.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|t| t.as_str().map(|s| s.to_string()))
                            .take(50)
                            .collect()
                    })
                    .unwrap_or_default();
                let score_delta = rule.get("score_delta").and_then(json_f64).unwrap_or(0.0);
                tag_rules.push(TagRule {
                    id: rid,
                    any_tag,
                    tags: ttags,
                    score_delta,
                });
            }
        }
        out.push(Arc::new(ParsedPack {
            source_file,
            rules,
            tag_rules,
            canary_percent,
            effective_at,
        }));
    }
    out
}

fn get_cached_parsed(json: &Arc<String>) -> Arc<Vec<Arc<ParsedPack>>> {
    let key = format!("{:x}", Sha256::digest(json.as_bytes()));
    {
        let cache = PARSED_CACHE.lock();
        if let Some(v) = cache.get(&key) {
            return v.clone();
        }
    }
    let parsed: Arc<Vec<Arc<ParsedPack>>> = match serde_json::from_str::<Vec<Value>>(json.as_str()) {
        Ok(arr) => Arc::new(parse_active_packs(&arr, true)),
        Err(_) => Arc::new(Vec::new()),
    };
    let mut cache = PARSED_CACHE.lock();
    cache.insert(key, parsed.clone());
    parsed
}

/// Replace cached JSON for active rule packs (same semantics as Python `_cached_packs` only).
#[pyfunction]
fn sync_packs_json(packs_json: String) -> PyResult<()> {
    let arr: Vec<Value> = serde_json::from_str(&packs_json).map_err(|e| {
        PyErr::new::<PyValueError, _>(format!("invalid packs JSON: {e}"))
    })?;
    let active: Vec<Value> = arr
        .into_iter()
        .filter(|v| {
            v.get("version").and_then(|x| x.as_u64()) == Some(1)
                && v.get("mode").and_then(|x| x.as_str()) != Some("disabled")
                && v.get("mode").and_then(|x| x.as_str()) != Some("shadow")
        })
        .collect();
    let s = serde_json::to_string(&active)
        .map_err(|e| PyErr::new::<PyValueError, _>(format!("serialize packs: {e}")))?;
    *ACTIVE_PACKS_JSON.lock() = Some(Arc::new(s));
    Ok(())
}

fn merge_tags_signal(
    redis_tags_json: &str,
    signal_tags_json: Option<&str>,
) -> Vec<String> {
    let mut redis_tags: Vec<String> = serde_json::from_str(redis_tags_json).unwrap_or_default();
    if let Some(st) = signal_tags_json {
        if let Ok(extra) = serde_json::from_str::<Vec<String>>(st) {
            let mut seen: HashSet<String> = redis_tags.iter().cloned().collect();
            for t in extra {
                if seen.insert(t.clone()) {
                    redis_tags.push(t);
                }
            }
        }
    }
    redis_tags
}

fn evaluate_parsed_slice(
    parsed: &[Arc<ParsedPack>],
    fmap: &serde_json::Map<String, Value>,
    redis_tags: &[String],
    tid: &str,
    eid: &str,
    mode: &str,
) -> serde_json::Value {
    let mut hits: Vec<String> = Vec::new();
    let mut tags: Vec<String> = Vec::new();
    let mut delta = 0.0;
    let mut contributing: Vec<String> = Vec::new();
    let mut telemetry: Vec<TelEvent> = Vec::new();

    for pack in parsed.iter() {
        if !pack_should_apply(pack, tid, eid, mode) {
            continue;
        }
        let (h, t, d, pf, tel) = evaluate_pack(pack, fmap, redis_tags);
        hits.extend(h);
        tags.extend(t);
        delta += d;
        telemetry.extend(tel);
        if let Some(p) = pf {
            contributing.push(p);
        }
    }
    contributing.sort();
    contributing.dedup();
    serde_json::json!({
        "rule_hits": hits,
        "tags": tags,
        "score_delta": delta,
        "contributing_pack_files": contributing,
        "telemetry": telemetry,
    })
}

#[pyfunction]
fn rust_engine_cache_stats() -> PyResult<(usize, bool)> {
    let n = PARSED_CACHE.lock().len();
    let synced = ACTIVE_PACKS_JSON.lock().is_some();
    Ok((n, synced))
}

#[pyfunction]
fn evaluate_json_rules_rust(
    features_json: String,
    redis_tags_json: String,
    tenant_id: String,
    entity_id: String,
    evaluation_mode: String,
    signal_tags_json: Option<String>,
) -> PyResult<String> {
    let packs_arc = {
        let g = ACTIVE_PACKS_JSON.lock();
        g.clone().ok_or_else(|| {
            PyErr::new::<PyValueError, _>("sync_packs_json must be called before evaluate")
        })?
    };
    let parsed = get_cached_parsed(&packs_arc);

    let features: Value = serde_json::from_str(&features_json)
        .map_err(|e| PyErr::new::<PyValueError, _>(format!("features json: {e}")))?;
    let fmap = features
        .as_object()
        .cloned()
        .unwrap_or_else(|| serde_json::Map::new());

    let st_ref = signal_tags_json.as_deref();
    let redis_tags = merge_tags_signal(&redis_tags_json, st_ref);

    let tid = tenant_id.trim();
    let tid = if tid.is_empty() { "default" } else { tid };
    let eid = entity_id.trim();
    let eid = if eid.is_empty() { "default" } else { eid };
    let mode = match evaluation_mode.as_str() {
        "production" | "simulation" | "challenger" => evaluation_mode.as_str(),
        _ => "production",
    };

    let out = evaluate_parsed_slice(&parsed, &fmap, &redis_tags, tid, eid, mode);
    serde_json::to_string(&out).map_err(|e| PyErr::new::<PyValueError, _>(e.to_string()))
}

/// Evaluate caller-supplied packs (e.g. shadow / recommendation preview) without touching global sync state.
#[pyfunction]
fn evaluate_adhoc_packs_rust(
    packs_json: String,
    features_json: String,
    redis_tags_json: String,
    tenant_id: String,
    entity_id: String,
    evaluation_mode: String,
    signal_tags_json: Option<String>,
) -> PyResult<String> {
    let arr: Vec<Value> = serde_json::from_str(&packs_json)
        .map_err(|e| PyErr::new::<PyValueError, _>(format!("packs json: {e}")))?;
    let parsed: Vec<Arc<ParsedPack>> = parse_active_packs(&arr, false);

    let features: Value = serde_json::from_str(&features_json)
        .map_err(|e| PyErr::new::<PyValueError, _>(format!("features json: {e}")))?;
    let fmap = features
        .as_object()
        .cloned()
        .unwrap_or_else(|| serde_json::Map::new());

    let st_ref = signal_tags_json.as_deref();
    let redis_tags = merge_tags_signal(&redis_tags_json, st_ref);

    let tid = tenant_id.trim();
    let tid = if tid.is_empty() { "default" } else { tid };
    let eid = entity_id.trim();
    let eid = if eid.is_empty() { "default" } else { eid };
    let mode = match evaluation_mode.as_str() {
        "production" | "simulation" | "challenger" => evaluation_mode.as_str(),
        _ => "production",
    };

    let out = evaluate_parsed_slice(&parsed, &fmap, &redis_tags, tid, eid, mode);
    serde_json::to_string(&out).map_err(|e| PyErr::new::<PyValueError, _>(e.to_string()))
}

#[pymodule]
fn tarka_rule_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sync_packs_json, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_json_rules_rust, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_adhoc_packs_rust, m)?)?;
    m.add_function(wrap_pyfunction!(rust_engine_cache_stats, m)?)?;
    Ok(())
}
