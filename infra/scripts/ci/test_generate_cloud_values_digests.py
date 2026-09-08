#!/usr/bin/env python3
"""G2: generate_cloud_values.py --digest-map for prod-on-k8s.

Run: python3 infra/scripts/ci/test_generate_cloud_values_digests.py
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GEN = ROOT / "infra/scripts/deploy/generate_cloud_values.py"

CORE = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SIGNAL = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
AGENT = "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"


def _write_map(dir_path: Path, text: str) -> Path:
    p = dir_path / "digests.map"
    p.write_text(text, encoding="utf-8")
    return p


def _gen(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(GEN), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )


def _load_gen():
    spec = importlib.util.spec_from_file_location("generate_cloud_values", GEN)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {GEN}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prod_base(out: Path) -> list[str]:
    return [
        "--preset",
        "prod-on-k8s",
        "--image-registry",
        "registry.example.com/tarka",
        "--db-url",
        "postgresql+asyncpg://fraud:pw@db.internal:5432/fraud",
        "--redis-url",
        "rediss://elasticache:6379/0",
        "--output",
        str(out),
    ]


class TestGenerateCloudValuesDigests(unittest.TestCase):
    def test_prod_on_k8s_without_digest_map_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            r = _gen(_prod_base(out))
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("--digest-map", r.stderr + r.stdout)

    def test_prod_on_k8s_allow_empty_digest_is_limitation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            r = _gen([*_prod_base(out), "--allow-empty-digest"])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            text = out.read_text(encoding="utf-8")
            self.assertIn("coreApi:", text)
            self.assertIn('digest: ""', text)
            self.assertNotIn('digest: "sha256:', text)

    def test_prod_on_k8s_digest_map_writes_core_and_signal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            digest_map = _write_map(
                Path(td),
                f"coreApi={CORE}\nsignalApi={SIGNAL}\ninvestigationAgent={AGENT}\n",
            )
            r = _gen([*_prod_base(out), "--digest-map", str(digest_map)])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            text = out.read_text(encoding="utf-8")
        self.assertIn(f'digest: "{CORE}"', text)
        self.assertIn(f'digest: "{SIGNAL}"', text)
        self.assertIn(f'digest: "{AGENT}"', text)

    def test_prod_on_k8s_digest_map_missing_signal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            digest_map = _write_map(Path(td), f"coreApi={CORE}\n")
            r = _gen([*_prod_base(out), "--digest-map", str(digest_map)])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        combined = r.stderr + r.stdout
        self.assertIn("signalApi", combined)

    def test_invalid_digest_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            digest_map = _write_map(Path(td), "coreApi=latest\n")
            r = _gen([*_prod_base(out), "--digest-map", str(digest_map)])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("sha256", (r.stderr + r.stdout).lower())

    def test_enabled_image_without_digest_field_is_empty(self) -> None:
        gen = _load_gen()
        text = "coreApi:\n  enabled: true\n  tag: 1.3.0-beta\n"
        self.assertIn("coreApi", gen.empty_enabled_digests(text))

    def test_apply_digest_map_inserts_missing_digest_line(self) -> None:
        gen = _load_gen()
        text = "coreApi:\n  enabled: true\n  tag: 1.3.0-beta\nsignalApi:\n  enabled: false\n"
        out = gen.apply_digest_map(text, {"coreApi": CORE})
        self.assertIn(f'  digest: "{CORE}"', out)

    def test_missing_digest_map_file_exits(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            r = _gen([*_prod_base(out), "--digest-map", str(Path(td) / "nope.map")])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("digest-map", (r.stderr + r.stdout).lower())

    def test_json_digest_map_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "values.yaml"
            digest_map = Path(td) / "digests.json"
            digest_map.write_text(
                f'{{"coreApi":"{CORE}","signalApi":"{SIGNAL}","investigationAgent":"{AGENT}"}}\n',
                encoding="utf-8",
            )
            r = _gen([*_prod_base(out), "--digest-map", str(digest_map)])
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            text = out.read_text(encoding="utf-8")
        self.assertIn(f'digest: "{CORE}"', text)

    def test_promote_prod_on_k8s_requires_digest_map(self) -> None:
        promote = ROOT / "infra/scripts/deploy/promote_preset.sh"
        env = os.environ.copy()
        env.pop("DIGEST_MAP", None)
        r = subprocess.run(
            ["bash", str(promote), "prod-on-k8s"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("DIGEST_MAP", r.stderr + r.stdout)

    def test_lite_on_k8s_does_not_require_digest_map(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "lite.values.yaml"
            r = _gen(
                [
                    "--preset",
                    "lite-on-k8s",
                    "--image-registry",
                    "registry.example.com/tarka",
                    "--output",
                    str(out),
                ]
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            text = out.read_text(encoding="utf-8")
        self.assertNotIn("sha256:", text)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
