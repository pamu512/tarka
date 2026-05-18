//! Lazy node identity snapshot used for [`crate::evidence::Header::engine_fingerprint`].
//!
//! Uses [`sysinfo`] for CPU vendor/brand and the first non-zero MAC. Sandboxed or permission-limited
//! environments may yield empty enumerations; those paths log at `warn` and substitute `restricted`.

use sha2::{Digest, Sha256};
use std::sync::OnceLock;
use sysinfo::{CpuRefreshKind, Networks, RefreshKind, System};

static ENGINE_FINGERPRINT: OnceLock<String> = OnceLock::new();

/// Returns the cached engine fingerprint for this process (computed once at first call).
///
/// Format: `tarka.engine_fp/v1;h=<sha256 hex>;arch=<…>;vendor=<…>;brand=<…>;mac=<…>` where any
/// unavailable segment is the literal `restricted`.
pub fn engine_fingerprint() -> &'static str {
    ENGINE_FINGERPRINT
        .get_or_init(compute_engine_fingerprint)
        .as_str()
}

fn compute_engine_fingerprint() -> String {
    let sys = System::new_with_specifics(
        RefreshKind::new().with_cpu(CpuRefreshKind::everything()),
    );

    let arch_raw = System::cpu_arch().unwrap_or_else(|| "unknown".to_string());
    let arch = sanitize_component(arch_raw.as_str(), 64, "cpu_arch");

    let (vendor_raw, brand_raw) = sys.cpus().first().map_or_else(
        || {
            tracing::warn!(
                target: "tarka.engine",
                "CPU identity unavailable (empty CPU list or unsupported platform); fingerprint uses restricted CPU fields"
            );
            ("restricted", "restricted")
        },
        |cpu| (cpu.vendor_id(), cpu.brand()),
    );

    let vendor = sanitize_component(vendor_raw, 64, "cpu_vendor_id");
    let brand = sanitize_component(brand_raw, 96, "cpu_brand");

    let networks = Networks::new_with_refreshed_list();
    let mac_from_iface = first_physical_mac(&networks);
    if mac_from_iface.is_none() {
        tracing::warn!(
            target: "tarka.engine",
            "No non-zero MAC address found (permissions, sandbox, or no interfaces); fingerprint uses restricted MAC"
        );
    }
    let mac_src = mac_from_iface.as_deref().unwrap_or("restricted");
    let mac = sanitize_component(mac_src, 32, "mac");

    let canonical_material = format!(
        "tarka.engine_fp/v1|arch={}|vendor={}|brand={}|mac={}",
        arch, vendor, brand, mac
    );
    let digest = hex::encode(Sha256::digest(canonical_material.as_bytes()));

    format!(
        "tarka.engine_fp/v1;h={digest};arch={arch};vendor={vendor};brand={brand};mac={mac}"
    )
}

fn first_physical_mac(networks: &Networks) -> Option<String> {
    for (_name, data) in networks {
        let m = data.mac_address();
        if !m.is_unspecified() {
            return Some(format!("{m}"));
        }
    }
    None
}

fn sanitize_component(raw: &str, max_chars: usize, label: &'static str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        tracing::warn!(
            target: "tarka.engine",
            component = label,
            "hardware identifier empty after trim; using restricted"
        );
        return "restricted".to_string();
    }
    let mut out = String::new();
    let mut truncated = false;
    let mut n_chars = 0usize;
    for ch in trimmed.chars().filter(|c| !matches!(c, ';' | '|')) {
        if n_chars >= max_chars {
            truncated = true;
            break;
        }
        out.push(ch);
        n_chars += 1;
    }
    if truncated {
        tracing::warn!(
            target: "tarka.engine",
            component = label,
            "hardware identifier truncated for fingerprint envelope"
        );
    }
    if out.is_empty() {
        tracing::warn!(
            target: "tarka.engine",
            component = label,
            "hardware identifier contained only delimiter characters; using restricted"
        );
        return "restricted".to_string();
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fingerprint_stable_and_well_formed() {
        let a = engine_fingerprint();
        let b = engine_fingerprint();
        assert_eq!(a, b);
        assert!(
            a.starts_with("tarka.engine_fp/v1;h="),
            "unexpected prefix: {a}"
        );
        assert!(a.contains(";arch="));
        assert!(a.contains(";vendor="));
        assert!(a.contains(";brand="));
        assert!(a.contains(";mac="));
    }
}
