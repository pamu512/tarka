#!/usr/bin/env python3
"""Optional BYO LLM vars into infra/deploy/.env. Keys never go to the desk.

Two planes, kept separate:
  Desk Advise  = investigation-agent  OPENAI_BASE_URL + OPENAI_API_KEY [+ OPENAI_MODEL]
  Ingest Advise = shadow_agent        SHADOW_LLM_* / SHADOW_AGENT_URL

Interactive only when stdin is a TTY. Empty URL = skip (that plane off).
CI / pipes skip. Empty desk Advise URL = hide Advise chrome (no half-on).
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _env_has_key(text: str, key: str) -> bool:
    for line in text.splitlines():
        raw = line.strip()
        if raw.startswith("#") or "=" not in raw:
            continue
        k, _, v = raw.partition("=")
        if k.strip() == key and v.strip():
            return True
    return False


def env_has_llm_url(text: str) -> bool:
    """Ingest sidecar URL present (SHADOW_LLM_BASE_URL)."""
    return _env_has_key(text, "SHADOW_LLM_BASE_URL")


def env_has_advise_url(text: str) -> bool:
    """Desk Advise / investigation-agent URL present (OPENAI_BASE_URL)."""
    return _env_has_key(text, "OPENAI_BASE_URL")


def render_llm_block(*, url: str, api_key: str, model: str) -> str:
    """Ingest sidecar (shadow_agent). Not desk Advise."""
    url = url.strip()
    if not url:
        return ""
    backend = "vllm"
    lines = [
        "",
        "# Ingest sidecar (shadow_agent). Separate from desk Advise OPENAI_*.",
        "SHADOW_LLM_BACKEND=" + backend,
        "SHADOW_LLM_BASE_URL=" + url,
    ]
    if api_key.strip():
        lines.append("SHADOW_LLM_API_KEY=" + api_key.strip())
    if model.strip():
        lines.append("SHADOW_LLM_MODEL=" + model.strip())
    return "\n".join(lines) + "\n"


def render_advise_block(*, url: str, api_key: str, model: str) -> str:
    """Desk Advise (investigation-agent). Never VITE_* — keys stay off the desk."""
    url = url.strip()
    if not url:
        return ""
    lines = [
        "",
        "# Desk Advise (investigation-agent). Empty URL = plane off. Key never goes to the desk.",
        "OPENAI_BASE_URL=" + url,
    ]
    if api_key.strip():
        lines.append("OPENAI_API_KEY=" + api_key.strip())
    if model.strip():
        lines.append("OPENAI_MODEL=" + model.strip())
    return "\n".join(lines) + "\n"


def _append_block(env_path: Path, block: str) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    prev = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    # Local TTY .env only (gitignored). Desk never sees this key.
    env_path.write_text(prev + block, encoding="utf-8")  # codeql[py/clear-text-storage-of-sensitive-data]
    env_path.chmod(0o600)


def prompt_llm(*, env_path: Path, stdin_isatty: bool, input_fn=input) -> str:
    if not stdin_isatty:
        return "skip"
    existing = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    already_advise = env_has_advise_url(existing)
    already_ingest = env_has_llm_url(existing)
    if already_advise and already_ingest:
        return "already"

    wrote = False

    if not already_advise:
        print(
            "Desk Advise (investigation-agent). OpenAI-compat URL "
            "(OpenAI / Gemini compat / Bedrock gateway / Azure / vLLM). "
            "Enter to skip — Advise stays hidden until you add this later."
        )
        url = input_fn("  URL [skip]: ").strip()
        if url:
            key = input_fn("  API key [optional]: ")
            model = input_fn("  model [optional]: ")
            block = render_advise_block(url=url, api_key=key, model=model)
            if block:
                _append_block(env_path, block)
                wrote = True
                print("[ok] wrote OPENAI_* to .env — desk Advise on when compose includes investigation-agent.")

    if not already_ingest:
        print(
            "Ingest sidecar (shadow_agent). Separate from desk Advise. "
            "Enter to skip — ingest LLM stays off."
        )
        url = input_fn("  ingest URL [skip]: ").strip()
        if url:
            key = input_fn("  ingest API key [optional]: ")
            model = input_fn("  ingest model [optional]: ")
            block = render_llm_block(url=url, api_key=key, model=model)
            if block:
                _append_block(env_path, block)
                wrote = True
                print("[ok] wrote SHADOW_LLM_* to .env — ingest sidecar stays off until that service is composed.")

    if wrote:
        return "wrote"
    if already_advise or already_ingest:
        return "already"
    return "skip"


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional BYO LLM .env prompt (desk Advise + ingest sidecar).")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    import sys

    prompt_llm(env_path=Path(args.env_file), stdin_isatty=sys.stdin.isatty())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
