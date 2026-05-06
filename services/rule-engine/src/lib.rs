//! JSON rule evaluation core for Tarka (parity with `decision_api.json_rules`).
//! Parsed packs are cached by content hash (AST cache).
#![allow(clippy::type_complexity)]

mod error;
mod json_ast;
mod logging_bridge;

use chrono::{DateTime, NaiveDateTime, TimeZone, Utc};
use error::{json_parse_err, json_serialize_err, TarkaEngineError};
use logging_bridge::ensure_tracing_installed;
pub use logging_bridge::LOGGER_BRIDGE;
use parking_lot::Mutex;
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use regex::Regex;
use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::sync::{Arc, LazyLock};
use std::time::{Duration, Instant};
use tracing::instrument;

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

create_exception!(
    tarka_rule_engine,
    JsonAstMalformedError,
    PyException,
    "JSON rule AST failed structural validation (args[0] is JSON detail)"
);
create_exception!(
    tarka_rule_engine,
    ASTValidationError,
    PyValueError,
    "AST validation failed (args[0] is JSON detail with rule_id and ast_node_index)"
);
create_exception!(
    tarka_rule_engine,
    RegexCompilationError,
    PyValueError,
    "Regex compilation failed for a rule condition or AST node"
);
create_exception!(
    tarka_rule_engine,
    JsonEngineError,
    PyValueError,
    "Invalid JSON input to the rule engine"
);
create_exception!(
    tarka_rule_engine,
    RuleEnginePanic,
    PyRuntimeError,
    "Rule engine internal invariant violated (should not occur if inputs are valid)"
);
create_exception!(
    tarka_rule_engine,
    EvaluationBudgetExceeded,
    PyRuntimeError,
    "Rule evaluation exceeded the configured time budget (args[0] is JSON detail with rule_id)"
);

fn engine_err_to_py(e: &TarkaEngineError) -> PyErr {
    let payload = e.json_payload_string();
    match e {
        TarkaEngineError::AstValidation { .. } => ASTValidationError::new_err(payload),
        TarkaEngineError::RegexCompilation { .. } => RegexCompilationError::new_err(payload),
        TarkaEngineError::JsonParse { .. } | TarkaEngineError::JsonSerialize { .. } => {
            JsonEngineError::new_err(payload)
        }
        TarkaEngineError::InternalInvariant { .. } => RuleEnginePanic::new_err(payload),
        TarkaEngineError::EngineNotInitialized => JsonEngineError::new_err(payload),
        TarkaEngineError::EvaluationBudget { .. } => EvaluationBudgetExceeded::new_err(payload),
    }
}

fn ast_malformed_py_err(m: &json_ast::AstMalformed) -> PyErr {
    let payload = serde_json::json!({
        "code": m.code,
        "message": m.message,
        "path": m.path,
        "rule_id": m.rule_id,
        "ast_node_index": m.ast_node_index,
    })
    .to_string();
    JsonAstMalformedError::new_err(payload)
}

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
    when_ast: Option<json_ast::AstNode>,
    tags: Vec<String>,
    score_delta: f64,
}

struct TagRule {
    id: String,
    any_tag: Vec<String>,
    tags: Vec<String>,
    score_delta: f64,
}

pub(crate) struct Condition {
    op: String,
    field: String,
    value: Value,
    regex_compiled: Option<Arc<Regex>>,
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
    let prefix: [u8; 4] = h[..4].try_into().unwrap_or_default();
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

fn build_safe_regex_pattern(pattern: &str) -> String {
    let escaped = regex::escape(pattern);
    format!("(?i)^{}$", escaped.replace(r"\*", ".*").replace(r"\?", "."))
}

fn compile_regex_for_rule(
    pattern: &str,
    rule_id: &str,
    ast_node_index: Option<usize>,
) -> Result<Arc<Regex>, TarkaEngineError> {
    if pattern.is_empty() || pattern.len() > MAX_REGEX_PATTERN_LEN {
        return Err(TarkaEngineError::RegexCompilation {
            rule_id: rule_id.to_string(),
            ast_node_index,
            pattern_len: pattern.len(),
            message: "pattern empty or exceeds MAX_REGEX_PATTERN_LEN".to_string(),
        });
    }
    let safe = build_safe_regex_pattern(pattern);
    Regex::new(&safe).map_err(|e| TarkaEngineError::RegexCompilation {
        rule_id: rule_id.to_string(),
        ast_node_index,
        pattern_len: pattern.len(),
        message: e.to_string(),
    })
    .map(Arc::new)
}

#[instrument(skip(features, condition), level = "debug")]
pub(crate) fn match_condition(features: &serde_json::Map<String, Value>, condition: &Condition) -> bool {
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
        "not_in" => match expected.as_array() {
            Some(arr) => !arr.iter().any(|v| Some(v) == actual),
            None => true,
        },
        "contains" => {
            let exp = json_str_pythonish(expected);
            let act = json_str_pythonish(&actual.cloned().unwrap_or(Value::Null));
            !exp.is_empty() && act.contains(&exp)
        }
        "starts_with" => {
            let suf = expected.as_str().unwrap_or("");
            actual
                .and_then(|a| a.as_str())
                .is_some_and(|a| a.starts_with(suf))
        }
        "ends_with" => {
            let suf = expected.as_str().unwrap_or("");
            actual
                .and_then(|a| a.as_str())
                .is_some_and(|a| a.ends_with(suf))
        }
        "regex" => {
            let act = format!("{}", actual.cloned().unwrap_or(Value::Null));
            match &condition.regex_compiled {
                Some(re) => re.is_match(&act),
                None => false,
            }
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

fn rule_when_matches(rule: &Rule, features: &serde_json::Map<String, Value>) -> bool {
    if let Some(ast) = &rule.when_ast {
        return json_ast::eval_ast(ast, features);
    }
    !rule.when.is_empty()
        && rule.when.len() <= MAX_CONDITIONS_PER_RULE
        && rule.when.iter().all(|c| match_condition(features, c))
}

fn evaluate_pack(
    pack: &ParsedPack,
    features: &serde_json::Map<String, Value>,
    redis_tags: &[String],
) -> Result<(Vec<String>, Vec<String>, f64, Option<String>, Vec<TelEvent>), TarkaEngineError> {
    let mut hits = Vec::new();
    let mut tags = Vec::new();
    let mut delta = 0.0;
    let mut telemetry: Vec<TelEvent> = Vec::new();
    let t0 = Instant::now();
    let pf_base = pack.source_file.clone();
    for rule in &pack.rules {
        if t0.elapsed() > MAX_EVAL_TIME {
            return Err(TarkaEngineError::EvaluationBudget {
                rule_id: rule.id.clone(),
                ast_node_index: None,
                message: format!("evaluate_pack exceeded {:?}", MAX_EVAL_TIME),
            });
        }
        if !rule_when_matches(rule, features) {
            continue;
        }
        hits.push(rule.id.clone());
        tags.extend(rule.tags.iter().cloned());
        delta += rule.score_delta;
        telemetry.push(TelEvent {
            pack_file: pf_base.clone(),
            rule_id: rule.id.clone(),
            kind: "rule".to_string(),
        });
    }
    let redis_set: HashSet<&str> = redis_tags.iter().map(String::as_str).collect();
    for rule in pack.tag_rules.iter().take(MAX_RULES_PER_PACK) {
        if t0.elapsed() > MAX_EVAL_TIME {
            return Err(TarkaEngineError::EvaluationBudget {
                rule_id: rule.id.clone(),
                ast_node_index: None,
                message: format!("tag_rule pass exceeded {:?}", MAX_EVAL_TIME),
            });
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
    Ok((hits, tags, delta, contributing, telemetry))
}

/// Parse rule packs from JSON. When `exclude_shadow` is true, packs with mode `shadow` are skipped
/// (production / GitOps sync path). When false, shadow packs are included (adhoc / shadow evaluation).
fn parse_active_packs(arr: &[Value], exclude_shadow: bool) -> Result<Vec<Arc<ParsedPack>>, TarkaEngineError> {
    let mut out = Vec::new();
    for v in arr {
        let version_ok = match v.get("version").and_then(|x| x.as_u64()) {
            Some(1) => true,
            Some(_) | None => false,
        };
        if !version_ok {
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
            let when_arr = rule.get("when").and_then(|x| x.as_array());
            let has_flat = when_arr.map(|w| !w.is_empty()).unwrap_or(false);
            let has_ast = rule
                .get("when_ast")
                .map(|v| !v.is_null())
                .unwrap_or(false);
            if has_flat && has_ast {
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

            if has_ast {
                let raw = match rule.get("when_ast") {
                    Some(rv) => rv,
                    None => continue,
                };
                let ast =
                    json_ast::parse_ast_strict_in_rule(raw, "when_ast", rid.as_str()).map_err(TarkaEngineError::from)?;
                rules.push(Rule {
                    id: rid,
                    when: Vec::new(),
                    when_ast: Some(ast),
                    tags: rule_tags,
                    score_delta,
                });
                continue;
            }

            let when = match when_arr {
                Some(w) if !w.is_empty() && w.len() <= MAX_CONDITIONS_PER_RULE => w,
                _ => continue,
            };
            let mut conds = Vec::new();
            let mut skip = false;
            for c in when {
                let op = c
                    .get("op")
                    .and_then(|x| x.as_str())
                    .unwrap_or("eq")
                    .to_string();
                let field = c.get("field").and_then(|x| x.as_str()).unwrap_or("").to_string();
                if field.is_empty() || field.len() > MAX_FIELD_LEN {
                    skip = true;
                    break;
                }
                let value = c.get("value").cloned().unwrap_or(Value::Null);
                let regex_compiled = if op == "regex" {
                    let pat = value.as_str().ok_or_else(|| TarkaEngineError::RegexCompilation {
                        rule_id: rid.clone(),
                        ast_node_index: None,
                        pattern_len: 0,
                        message: "regex condition requires string value".to_string(),
                    })?;
                    Some(compile_regex_for_rule(pat, rid.as_str(), None)?)
                } else {
                    None
                };
                conds.push(Condition {
                    op,
                    field,
                    value,
                    regex_compiled,
                });
            }
            if skip {
                continue;
            }
            rules.push(Rule {
                id: rid,
                when: conds,
                when_ast: None,
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
    Ok(out)
}

fn get_cached_parsed(json: &Arc<String>) -> Result<Arc<Vec<Arc<ParsedPack>>>, TarkaEngineError> {
    let key = format!("{:x}", Sha256::digest(json.as_bytes()));
    {
        let cache = PARSED_CACHE.lock();
        if let Some(v) = cache.get(&key) {
            return Ok(v.clone());
        }
    }
    let arr: Vec<Value> = serde_json::from_str(json.as_str()).map_err(|e| json_parse_err("packs_cache", e))?;
    let parsed_vec = parse_active_packs(&arr, true)?;
    let parsed: Arc<Vec<Arc<ParsedPack>>> = Arc::new(parsed_vec);
    let mut cache = PARSED_CACHE.lock();
    cache.insert(key, parsed.clone());
    Ok(parsed)
}

/// Replace cached JSON for active rule packs (same semantics as Python `_cached_packs` only).
#[pyfunction]
fn sync_packs_json(packs_json: String) -> PyResult<()> {
    let arr: Vec<Value> = serde_json::from_str(&packs_json)
        .map_err(|e| engine_err_to_py(&json_parse_err("sync_packs_json", e)))?;
    let active: Vec<Value> = arr
        .into_iter()
        .filter(|v| {
            v.get("version").and_then(|x| x.as_u64()) == Some(1)
                && v.get("mode").and_then(|x| x.as_str()) != Some("disabled")
                && v.get("mode").and_then(|x| x.as_str()) != Some("shadow")
        })
        .collect();
    let s = serde_json::to_string(&active)
        .map_err(|e| engine_err_to_py(&json_serialize_err("sync_packs_json", e)))?;
    *ACTIVE_PACKS_JSON.lock() = Some(Arc::new(s));
    Ok(())
}

fn merge_tags_signal(
    redis_tags_json: &str,
    signal_tags_json: Option<&str>,
) -> Result<Vec<String>, TarkaEngineError> {
    let mut redis_tags: Vec<String> =
        serde_json::from_str(redis_tags_json).map_err(|e| json_parse_err("redis_tags", e))?;
    if let Some(st) = signal_tags_json {
        let extra: Vec<String> =
            serde_json::from_str(st).map_err(|e| json_parse_err("signal_tags", e))?;
        let mut seen: HashSet<String> = redis_tags.iter().cloned().collect();
        for t in extra {
            if seen.insert(t.clone()) {
                redis_tags.push(t);
            }
        }
    }
    Ok(redis_tags)
}

fn evaluate_parsed_slice(
    parsed: &[Arc<ParsedPack>],
    fmap: &serde_json::Map<String, Value>,
    redis_tags: &[String],
    tid: &str,
    eid: &str,
    mode: &str,
) -> Result<serde_json::Value, TarkaEngineError> {
    let mut hits: Vec<String> = Vec::new();
    let mut tags: Vec<String> = Vec::new();
    let mut delta = 0.0;
    let mut contributing: Vec<String> = Vec::new();
    let mut telemetry: Vec<TelEvent> = Vec::new();

    for pack in parsed.iter() {
        if !pack_should_apply(pack, tid, eid, mode) {
            continue;
        }
        let (h, t, d, pf, tel) = evaluate_pack(pack, fmap, redis_tags)?;
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
    Ok(serde_json::json!({
        "rule_hits": hits,
        "tags": tags,
        "score_delta": delta,
        "contributing_pack_files": contributing,
        "telemetry": telemetry,
    }))
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
        g.clone()
            .ok_or_else(|| engine_err_to_py(&TarkaEngineError::EngineNotInitialized))?
    };
    let parsed = get_cached_parsed(&packs_arc).map_err(|e| engine_err_to_py(&e))?;

    let features: Value = serde_json::from_str(&features_json)
        .map_err(|e| engine_err_to_py(&json_parse_err("features_json", e)))?;
    let fmap = features
        .as_object()
        .cloned()
        .unwrap_or_default();

    let st_ref = signal_tags_json.as_deref();
    let redis_tags = merge_tags_signal(&redis_tags_json, st_ref).map_err(|e| engine_err_to_py(&e))?;

    let tid = tenant_id.trim();
    let tid = if tid.is_empty() { "default" } else { tid };
    let eid = entity_id.trim();
    let eid = if eid.is_empty() { "default" } else { eid };
    let mode = match evaluation_mode.as_str() {
        "production" | "simulation" | "challenger" => evaluation_mode.as_str(),
        _ => "production",
    };

    let out = evaluate_parsed_slice(&parsed, &fmap, &redis_tags, tid, eid, mode).map_err(|e| engine_err_to_py(&e))?;
    serde_json::to_string(&out).map_err(|e| engine_err_to_py(&json_serialize_err("evaluate_result", e)))
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
        .map_err(|e| engine_err_to_py(&json_parse_err("packs_json", e)))?;
    let parsed: Vec<Arc<ParsedPack>> = parse_active_packs(&arr, false).map_err(|e| engine_err_to_py(&e))?;

    let features: Value = serde_json::from_str(&features_json)
        .map_err(|e| engine_err_to_py(&json_parse_err("features_json", e)))?;
    let fmap = features.as_object().cloned().unwrap_or_default();

    let st_ref = signal_tags_json.as_deref();
    let redis_tags = merge_tags_signal(&redis_tags_json, st_ref).map_err(|e| engine_err_to_py(&e))?;

    let tid = tenant_id.trim();
    let tid = if tid.is_empty() { "default" } else { tid };
    let eid = entity_id.trim();
    let eid = if eid.is_empty() { "default" } else { eid };
    let mode = match evaluation_mode.as_str() {
        "production" | "simulation" | "challenger" => evaluation_mode.as_str(),
        _ => "production",
    };

    let out = evaluate_parsed_slice(&parsed, &fmap, &redis_tags, tid, eid, mode).map_err(|e| engine_err_to_py(&e))?;
    serde_json::to_string(&out).map_err(|e| engine_err_to_py(&json_serialize_err("evaluate_adhoc_result", e)))
}

/// Validate a single rule ``when_ast`` JSON object (strict: Pydantic-equivalent, ``extra`` forbidden).
#[pyfunction]
fn validate_json_rule_ast(ast_json: String) -> PyResult<()> {
    let v: Value = serde_json::from_str(&ast_json)
        .map_err(|e| engine_err_to_py(&json_parse_err("validate_json_rule_ast", e)))?;
    json_ast::parse_ast_strict(&v, "$")
        .map_err(|m| ast_malformed_py_err(&m))?;
    Ok(())
}

/// Parse + evaluate one AST against a feature map; raises ``JsonAstMalformedError`` when AST is malformed.
#[pyfunction]
fn evaluate_json_ast_strict(ast_json: String, features_json: String) -> PyResult<bool> {
    let v: Value = serde_json::from_str(&ast_json)
        .map_err(|e| engine_err_to_py(&json_parse_err("evaluate_json_ast_strict.ast", e)))?;
    let ast = json_ast::parse_ast_strict(&v, "$").map_err(|m| ast_malformed_py_err(&m))?;
    let features: Value = serde_json::from_str(&features_json)
        .map_err(|e| engine_err_to_py(&json_parse_err("evaluate_json_ast_strict.features", e)))?;
    let fmap = features
        .as_object()
        .cloned()
        .unwrap_or_default();
    Ok(json_ast::eval_ast(&ast, &fmap))
}

/// Install Python ``logging.Logger`` (or any object with ``.log(level, msg)``) as the tracing sink.
#[pyfunction]
#[pyo3(name = "install_tracing_python_bridge")]
fn install_tracing_python_bridge_py(logger: Bound<'_, PyAny>) -> PyResult<()> {
    ensure_tracing_installed();
    let unbound = logger.unbind();
    *LOGGER_BRIDGE.lock() = Some(unbound);
    Ok(())
}

#[pymodule]
fn tarka_rule_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Safe for `tracing` → Python `logging` if events are emitted from Rust threads.
    pyo3::prepare_freethreaded_python();
    ensure_tracing_installed();
    tracing::info!(target: "tarka_rule_engine", "tarka_rule_engine PyO3 module initialized");

    m.setattr(
        "__doc__",
        concat!(
            "Tarka JSON rule engine (Rust via PyO3).\n\n",
            "Exceptions (attach ``args[0]`` JSON from ``str(exc)`` for API responses):\n",
            "  JsonAstMalformedError — strict standalone AST validation (``validate_json_rule_ast``).\n",
            "  ASTValidationError — pack ``when_ast`` parse / structural validation.\n",
            "  RegexCompilationError — safe-regex build for flat ``when`` or AST ``regex``.\n",
            "  JsonEngineError — invalid JSON payloads or engine not initialized.\n",
            "  EvaluationBudgetExceeded — wall-clock budget for a pack evaluation.\n",
            "  RuleEnginePanic — internal invariant (should be unreachable for valid packs).\n\n",
            "Call ``install_tracing_python_bridge(logger)`` to forward Rust ``tracing`` events to a Python ``logging.Logger``.",
        ),
    )?;

    m.add(
        "JsonAstMalformedError",
        m.py().get_type::<JsonAstMalformedError>(),
    )?;
    m.add(
        "ASTValidationError",
        m.py().get_type::<ASTValidationError>(),
    )?;
    m.add(
        "RegexCompilationError",
        m.py().get_type::<RegexCompilationError>(),
    )?;
    m.add(
        "JsonEngineError",
        m.py().get_type::<JsonEngineError>(),
    )?;
    m.add(
        "EvaluationBudgetExceeded",
        m.py().get_type::<EvaluationBudgetExceeded>(),
    )?;
    m.add(
        "RuleEnginePanic",
        m.py().get_type::<RuleEnginePanic>(),
    )?;

    m.add_function(wrap_pyfunction!(sync_packs_json, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_json_rules_rust, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_adhoc_packs_rust, m)?)?;
    m.add_function(wrap_pyfunction!(rust_engine_cache_stats, m)?)?;
    m.add_function(wrap_pyfunction!(validate_json_rule_ast, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_json_ast_strict, m)?)?;
    m.add_function(wrap_pyfunction!(install_tracing_python_bridge_py, m)?)?;
    Ok(())
}
