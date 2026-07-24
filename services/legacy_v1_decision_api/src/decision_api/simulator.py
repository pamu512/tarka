"""Simulation engine — replay real data and generate synthetic fraud scenarios.

Supports:
- Replay historical audit records through current or custom rules
- Generate synthetic transaction data with configurable fraud patterns
- A/B comparison of rule sets
- Statistical analysis of results
"""

import random
from typing import Any

from pydantic import BaseModel


class SyntheticProfile(BaseModel):
    """Configuration for synthetic data generation."""

    name: str = "default"
    total_events: int = 1000
    fraud_rate: float = 0.05  # 5% fraud by default
    tenant_id: str = "synthetic"

    # Amount distribution
    amount_mean: float = 250.0
    amount_std: float = 500.0
    fraud_amount_multiplier: float = 5.0

    # Timing
    night_fraud_bias: float = 0.6  # 60% of fraud happens at night

    # Device signals
    vpn_rate: float = 0.03
    emulator_rate: float = 0.01
    bot_rate: float = 0.005
    fraud_vpn_rate: float = 0.4
    fraud_emulator_rate: float = 0.3
    fraud_bot_rate: float = 0.2

    # Account
    new_account_rate: float = 0.1
    fraud_new_account_rate: float = 0.5

    # Velocity
    high_velocity_rate: float = 0.05
    fraud_high_velocity_rate: float = 0.6


SCENARIO_TEMPLATES: dict[str, SyntheticProfile] = {
    "baseline": SyntheticProfile(name="baseline"),
    "high_fraud": SyntheticProfile(
        name="high_fraud",
        fraud_rate=0.15,
        total_events=2000,
    ),
    "bot_attack": SyntheticProfile(
        name="bot_attack",
        fraud_rate=0.3,
        fraud_bot_rate=0.9,
        fraud_emulator_rate=0.7,
        total_events=5000,
    ),
    "account_takeover": SyntheticProfile(
        name="account_takeover",
        fraud_rate=0.08,
        fraud_vpn_rate=0.6,
        fraud_new_account_rate=0.1,
        fraud_high_velocity_rate=0.8,
        total_events=1500,
    ),
    "money_mule": SyntheticProfile(
        name="money_mule",
        fraud_rate=0.04,
        fraud_amount_multiplier=10.0,
        amount_mean=100.0,
        fraud_new_account_rate=0.7,
        total_events=2000,
    ),
}


def generate_synthetic_event(
    profile: SyntheticProfile,
    is_fraud: bool,
    idx: int,
) -> dict[str, Any]:
    """Generate a single synthetic transaction event."""
    entity_id = (
        f"synth-user-{random.randint(1, max(int(profile.total_events * 0.3), 10))}"
    )

    if is_fraud:
        amount = abs(
            random.gauss(
                profile.amount_mean * profile.fraud_amount_multiplier,
                profile.amount_std * 2,
            )
        )
    else:
        amount = abs(random.gauss(profile.amount_mean, profile.amount_std))
    amount = round(max(1.0, amount), 2)

    if is_fraud and random.random() < profile.night_fraud_bias:
        hour = random.choice([0, 1, 2, 3, 4, 23])
    else:
        hour = random.randint(0, 23)

    vpn_rate = profile.fraud_vpn_rate if is_fraud else profile.vpn_rate
    emu_rate = profile.fraud_emulator_rate if is_fraud else profile.emulator_rate
    bot_rate = profile.fraud_bot_rate if is_fraud else profile.bot_rate
    new_acct_rate = (
        profile.fraud_new_account_rate if is_fraud else profile.new_account_rate
    )
    vel_rate = (
        profile.fraud_high_velocity_rate if is_fraud else profile.high_velocity_rate
    )

    is_vpn = random.random() < vpn_rate
    is_emulator = random.random() < emu_rate
    is_bot = random.random() < bot_rate
    is_new = random.random() < new_acct_rate
    high_vel = random.random() < vel_rate

    account_age = random.randint(0, 5) if is_new else random.randint(30, 1000)
    tx_count = random.randint(15, 50) if high_vel else random.randint(0, 10)
    countries = (
        random.randint(2, 6)
        if is_fraud and random.random() < 0.3
        else random.randint(1, 2)
    )

    return {
        "event_type": "payment",
        "entity_id": entity_id,
        "tenant_id": profile.tenant_id,
        "payload": {
            "amount": amount,
            "currency": "USD",
            "hour_of_day": hour,
            "is_vpn": is_vpn,
            "is_emulator": is_emulator,
            "is_bot": is_bot,
            "is_new_device": is_new,
            "account_age_days": account_age,
            "transaction_count_24h": tx_count,
            "distinct_countries_7d": countries,
        },
        "_synthetic": True,
        "_is_fraud": is_fraud,
        "_scenario": profile.name,
        "_index": idx,
    }


def generate_scenario(profile: SyntheticProfile) -> list[dict[str, Any]]:
    """Generate a full scenario of synthetic events."""
    events = []
    n_fraud = int(profile.total_events * profile.fraud_rate)
    n_legit = profile.total_events - n_fraud

    labels = [True] * n_fraud + [False] * n_legit
    random.shuffle(labels)

    for i, is_fraud in enumerate(labels):
        events.append(generate_synthetic_event(profile, is_fraud, i))

    return events


class SimulationResult(BaseModel):
    scenario: str
    total_events: int
    actual_fraud_count: int
    actual_fraud_rate: float
    decisions: dict[str, int]  # {"allow": n, "review": n, "deny": n}
    true_positives: int  # fraud correctly denied
    false_positives: int  # legit incorrectly denied
    false_negatives: int  # fraud incorrectly allowed
    true_negatives: int  # legit correctly allowed
    precision: float
    recall: float
    f1_score: float
    avg_score_fraud: float
    avg_score_legit: float
    score_separation: float  # difference between avg fraud and legit scores


def analyze_simulation(
    events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> SimulationResult:
    """Analyze simulation results computing precision, recall, F1."""
    tp = fp = fn = tn = 0
    fraud_scores: list[float] = []
    legit_scores: list[float] = []
    decision_counts: dict[str, int] = {"allow": 0, "review": 0, "deny": 0}

    for event, dec in zip(events, decisions):
        is_fraud = event.get("_is_fraud", False)
        decision = dec.get("decision", "allow")
        score = float(dec.get("score", 0))
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

        blocked = decision in ("deny", "review")
        if is_fraud and blocked:
            tp += 1
        elif not is_fraud and blocked:
            fp += 1
        elif is_fraud and not blocked:
            fn += 1
        else:
            tn += 1

        if is_fraud:
            fraud_scores.append(score)
        else:
            legit_scores.append(score)

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-8)
    avg_fraud = sum(fraud_scores) / max(len(fraud_scores), 1)
    avg_legit = sum(legit_scores) / max(len(legit_scores), 1)

    n_fraud = sum(1 for e in events if e.get("_is_fraud"))

    return SimulationResult(
        scenario=events[0].get("_scenario", "unknown") if events else "empty",
        total_events=len(events),
        actual_fraud_count=n_fraud,
        actual_fraud_rate=round(n_fraud / max(len(events), 1), 4),
        decisions=decision_counts,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        avg_score_fraud=round(avg_fraud, 2),
        avg_score_legit=round(avg_legit, 2),
        score_separation=round(avg_fraud - avg_legit, 2),
    )
