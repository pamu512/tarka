//! Load content-addressed wasm artifacts from a directory (`<sha256-hex>.wasm` naming convention).

use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;

use tarka_core::rule_content_sha256;

use crate::error::CliError;

/// Loads every `*.wasm` file and indexes by lowercase hex SHA-256 of bytes (matches [`tarka_core`] CAS).
pub fn load_wasm_modules(dir: &Path) -> Result<HashMap<String, Arc<[u8]>>, CliError> {
    let mut out = HashMap::new();
    let rd = fs::read_dir(dir).map_err(|e| CliError::RuleFileIo {
        path: dir.to_path_buf(),
        source: e,
    })?;
    for ent in rd {
        let ent = ent.map_err(|e| CliError::RuleFileIo {
            path: dir.to_path_buf(),
            source: e,
        })?;
        let path = ent.path();
        if path.extension().and_then(|x| x.to_str()) != Some("wasm") {
            continue;
        }
        let bytes = fs::read(&path).map_err(|e| CliError::RuleFileIo {
            path: path.clone(),
            source: e,
        })?;
        let id = hex::encode(rule_content_sha256(&bytes));
        out.insert(id, bytes.into());
    }
    if out.is_empty() {
        return Err(CliError::WasmMissing(format!(
            "no `.wasm` files found under {}",
            dir.display()
        )));
    }
    Ok(out)
}
