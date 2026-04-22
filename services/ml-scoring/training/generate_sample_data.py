from __future__ import annotations
import csv
from pathlib import Path

import numpy as np

"""Generate a sample CSV of realistic transactions with fraud labels.

Usage:
    python generate_sample_data.py

Output:
    training/sample_transactions.csv  (1000 rows)
"""
FEATURES = [
    "amount",
    "hour_of_day",
    "is_new_device",
    "is_vpn",
    "is_emulator",
    "is_bot",
    "transaction_count_24h",
    "distinct_countries_7d",
    "account_age_days",
]

N_SAMPLES = 1000
FRAUD_RATIO = 0.05
RANDOM_SEED = 123
OUTPUT_PATH = Path(__file__).resolve().parent / "sample_transactions.csv"


def generate(n: int = N_SAMPLES, seed: int = RANDOM_SEED) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.RandomState(seed)
    n_fraud = int(n * FRAUD_RATIO)
    n_legit = n - n_fraud

    def _legit(size: int) -> np.ndarray:
        return np.column_stack(
            [
                rng.lognormal(4.0, 1.0, size).clip(1, 50_000),
                rng.normal(14, 4, size).clip(0, 23).astype(int),
                (rng.random(size) < 0.08).astype(float),
                (rng.random(size) < 0.05).astype(float),
                (rng.random(size) < 0.01).astype(float),
                (rng.random(size) < 0.005).astype(float),
                rng.poisson(3, size).clip(0, 100).astype(float),
                rng.choice([1, 1, 1, 1, 2], size).astype(float),
                rng.exponential(400, size).clip(1, 3650),
            ]
        )

    def _fraud(size: int) -> np.ndarray:
        return np.column_stack(
            [
                rng.lognormal(7.5, 1.2, size).clip(500, 100_000),
                rng.choice([0, 1, 2, 3, 4, 23, 22], size).astype(float),
                (rng.random(size) < 0.65).astype(float),
                (rng.random(size) < 0.55).astype(float),
                (rng.random(size) < 0.30).astype(float),
                (rng.random(size) < 0.20).astype(float),
                rng.poisson(15, size).clip(0, 100).astype(float),
                rng.choice([2, 3, 4, 5, 6], size).astype(float),
                rng.exponential(30, size).clip(0, 365),
            ]
        )

    X = np.vstack([_legit(n_legit), _fraud(n_fraud)]).astype(np.float32)
    y = np.concatenate([np.zeros(n_legit), np.ones(n_fraud)]).astype(np.int64)

    idx = rng.permutation(n)
    return X[idx], y[idx]


def main() -> None:
    X, y = generate()

    header = ["transaction_id"] + FEATURES + ["is_fraud"]

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i in range(len(X)):
            row = [f"txn_{i:05d}"]
            row.append(f"{X[i, 0]:.2f}")  # amount
            row.append(str(int(X[i, 1])))  # hour_of_day
            for j in range(2, 6):  # binary flags
                row.append(str(int(X[i, j])))
            row.append(str(int(X[i, 6])))  # transaction_count_24h
            row.append(str(int(X[i, 7])))  # distinct_countries_7d
            row.append(f"{X[i, 8]:.1f}")  # account_age_days
            row.append(str(int(y[i])))  # is_fraud
            writer.writerow(row)

    print(f"Wrote {len(X)} rows to {OUTPUT_PATH}")
    print(f"  Fraud: {y.sum():.0f} ({y.mean() * 100:.1f}%)")
    print(f"  Legit: {(1 - y).sum():.0f}")


if __name__ == "__main__":
    main()
