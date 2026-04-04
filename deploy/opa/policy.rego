package fraud

# OPA result merged by Decision API when OPA_URL is set (POST /v1/data/fraud/result).
# Input shape: input.snapshot with tenant_id, entity_id, event_type, features, redis_tags

default result := {"rule_hits": [], "tags": [], "score_delta": 0}

result := {
    "rule_hits": ["opa_high_risk_country"],
    "tags": ["geo_blocklist"],
    "score_delta": 30,
} if {
    input.snapshot.features.country == "XX"
}
