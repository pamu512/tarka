"""Evidence bundle JSON + zip export."""

from __future__ import annotations

import io
import json
import os
import zipfile

from case_api.main import app
from fastapi.testclient import TestClient


def _api_headers() -> dict[str, str]:
    keys = [k.strip() for k in (os.environ.get("API_KEYS") or "").split(",") if k.strip()]
    assert keys, "tests/conftest.py should set API_KEYS"
    return {"X-API-Key": keys[0]}


def test_evidence_bundle_zip_contains_json_and_readme() -> None:
    headers = _api_headers()
    with TestClient(app) as client:
        create = client.post(
            "/v1/cases",
            json={
                "tenant_id": "demo",
                "title": "evidence zip",
                "entity_id": "e-zip",
                "trace_id": "tr-zip-1",
            },
            headers=headers,
        )
        assert create.status_code == 201, create.text
        case_id = create.json()["id"]

        r = client.get(
            f"/v1/cases/{case_id}/evidence-bundle.zip",
            params={"tenant_id": "demo"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert "application/zip" in (r.headers.get("content-type") or "")
        assert "evidence-" in (r.headers.get("content-disposition") or "")

        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = set(zf.namelist())
            assert "evidence-bundle.json" in names
            assert "README.txt" in names
            bundle = json.loads(zf.read("evidence-bundle.json"))
            assert bundle["tenant_id"] == "demo"
            assert bundle["case"]["id"] == case_id
            assert "evidence_bundle_v1" in bundle
