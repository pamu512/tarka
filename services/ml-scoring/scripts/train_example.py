from __future__ import annotations
import os

import numpy as np

"""
Optional: log a run to MLflow and export a trivial ONNX model for ONNX_MODEL_PATH.

Usage (with extras): pip install -e '.[onnx,mlflow]' && python scripts/train_example.py
"""

def main() -> None:
    try:
        import mlflow
        import mlflow.onnx
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("Install mlflow, skl2onnx, onnx, scikit-learn for this example.")
        return

    X = np.random.randn(200, 2).astype(np.float32)
    y = (X[:, 0] + X[:, 1] > 0).astype(np.int64)
    clf = LogisticRegression().fit(X, y)
    onnx_model = convert_sklearn(
        clf,
        initial_types=[("input", FloatTensorType([None, 2]))],
        target_opset=12,
    )
    out = os.environ.get("ONNX_EXPORT_PATH", "model.onnx")
    with open(out, "wb") as f:
        f.write(onnx_model.SerializeToString())
    mlflow.set_experiment("tarka")
    with mlflow.start_run():
        mlflow.log_param("features", 2)
        mlflow.log_artifact(out)
    print("Wrote", out)


if __name__ == "__main__":
    main()
