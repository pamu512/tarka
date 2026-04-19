"""Structural validation for JSON rule packs (stdlib-only; safe for CI scripts)."""


def validate_rule_pack(pack: dict) -> list[str]:
    """Validate a rule pack and return list of error messages."""
    errors: list[str] = []
    canary = pack.get("canary_percent")
    if canary is not None:
        try:
            c = float(canary)
            if c < 0 or c > 100:
                errors.append("canary_percent must be between 0 and 100")
        except (TypeError, ValueError):
            errors.append("canary_percent must be a number")
    eff = pack.get("effective_at")
    if eff is not None and not isinstance(eff, str):
        errors.append("effective_at must be an ISO-8601 string when set")
    appr = pack.get("approved_by")
    if appr is not None and (not isinstance(appr, str) or len(str(appr)) > 256):
        errors.append("approved_by must be a short string when set")
    rules = pack.get("rules", [])
    if len(rules) > 200:
        errors.append(f"Too many rules: {len(rules)} (max 200)")
    for i, rule in enumerate(rules):
        rid = rule.get("id", f"rule_{i}")
        conditions = rule.get("when", [])
        if len(conditions) > 20:
            errors.append(f"Rule {rid}: too many conditions ({len(conditions)}, max 20)")
        for j, c in enumerate(conditions):
            if not c.get("field"):
                errors.append(f"Rule {rid}, condition {j}: missing 'field'")
            if c.get("op") == "regex":
                pattern = str(c.get("value", ""))
                if len(pattern) > 256:
                    errors.append(f"Rule {rid}, condition {j}: regex pattern too long")
        sd = rule.get("score_delta", 0)
        if abs(float(sd)) > 100:
            errors.append(f"Rule {rid}: score_delta {sd} exceeds bounds (-100, 100)")
    return errors
