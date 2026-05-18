//! Best-effort mapping from `signal_name:` usages in YAML source to 1-based line numbers.

/// Find the first line (1-based) where `signal_name:` is assigned to `needle` (trimmed equality).
pub(crate) fn line_for_signal_assignment(source: &str, needle: &str) -> Option<u32> {
    let needle = needle.trim();
    for (idx, raw_line) in source.lines().enumerate() {
        let mut code = raw_line.trim_start();
        if code.starts_with('#') {
            continue;
        }
        code = code.split('#').next().unwrap_or("").trim_end();
        // Strip YAML block sequence marker (`- signal_name:`).
        let mut code = code.trim_start();
        code = code.strip_prefix("- ").unwrap_or(code);
        let Some(rest) = code.strip_prefix("signal_name:") else {
            continue;
        };
        let val = parse_yaml_scalar_token(rest);
        if val == needle {
            return Some((idx + 1) as u32);
        }
    }
    None
}

/// Strip optional quotes and YAML flow punctuation from a scalar token.
fn parse_yaml_scalar_token(s: &str) -> &str {
    let s = s.trim();
    if (s.starts_with('"') && s.ends_with('"')) || (s.starts_with('\'') && s.ends_with('\'')) {
        s.get(1..s.len().saturating_sub(1)).unwrap_or("")
    } else {
        s.split([':', '{', '}', '[', ']', ','])
            .next()
            .unwrap_or("")
            .trim()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_plain_assignment() {
        let src = "foo: bar\nrules:\n  - signal_name: payment.amount\n";
        assert_eq!(line_for_signal_assignment(src, "payment.amount"), Some(3));
    }
}
