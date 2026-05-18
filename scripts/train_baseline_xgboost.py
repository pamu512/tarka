import logging
import os

import numpy as np
import xgboost as xgb
from onnxconverter_common.data_types import FloatTensorType
from onnxmltools.convert import convert_xgboost
from sklearn.model_selection import train_test_split

# Enforce strict logging for infra-level visibility
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def generate_synthetic_fraud_data(n_samples: int = 15000):
    """
    Generates synthetic transaction data that mimics a real-world API payload.
    Features: [amount, velocity_1h, velocity_24h, risk_score, time_of_day]
    """
    np.random.seed(42)

    # 5-dimensional feature array
    X = np.random.rand(n_samples, 5)
    X[:, 0] = X[:, 0] * 5000  # amount up to $5000
    X[:, 1] = X[:, 1] * 10  # 1h velocity (transactions in last hour)
    X[:, 2] = X[:, 2] * 50  # 24h velocity
    X[:, 3] = X[:, 3] * 100  # external risk score 0-100
    X[:, 4] = X[:, 4] * 24  # hour of day

    # Target labels (1 = Fraud, 0 = Legit).
    # Bias fraud towards high amount, high velocity, and high risk score.
    fraud_prob = (X[:, 0] / 5000) * 0.4 + (X[:, 1] / 10) * 0.3 + (X[:, 3] / 100) * 0.3
    y = (fraud_prob > 0.65).astype(int)

    return X, y


def main() -> None:
    target_dir = "services/ml_sidecar/models"
    os.makedirs(target_dir, exist_ok=True)
    onnx_model_path = os.path.join(target_dir, "baseline_fraud_v1.onnx")

    logging.info("1. Generating synthetic transaction data...")
    X, y = generate_synthetic_fraud_data()
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    logging.info("2. Training XGBoost Classifier on %s samples...", len(X_train))
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        use_label_encoder=False,
        eval_metric="logloss",
    )
    model.fit(X_train, y_train)

    accuracy = model.score(X_test, y_test)
    logging.info("3. Model trained successfully. Test Accuracy: %.4f", accuracy)

    logging.info("4. Converting XGBoost model to ONNX format...")
    # Define the input tensor type: [None, 5] means any batch size, exactly 5 float features
    initial_types = [("float_input", FloatTensorType([None, 5]))]
    onnx_model = convert_xgboost(model, initial_types=initial_types)

    logging.info("5. Saving compiled ONNX model to %s...", onnx_model_path)
    with open(onnx_model_path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    logging.info("SUCCESS: ONNX model physically bootstrapped and ready for ingestion.")


if __name__ == "__main__":
    main()
