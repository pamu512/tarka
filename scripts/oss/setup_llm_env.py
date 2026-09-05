#!/usr/bin/env python3
"""Optional BYO LLM vars into infra/deploy/.env. Keys never go to the desk.

Interactive only when stdin is a TTY. Empty URL = skip (plane off).
CI / pipes skip. Does not start Shadow compose (no thin overlay on day-1).
"""

from __future__ import annotations

import argparse
from pathlib import Path

def env_has_llm_url(text: str) -> bool:
    for line in text.splitlines():
        raw = line.strip()
        if raw.startswith("#") or "=" not in raw:
            continue
        k, _, v = raw.partition("=")
        if k.strip() == "SHADOW_LLM_BASE_URL" and v.strip():
            return True
    return False


def render_llm_block(*, url: str, api_key: str, model: str) -> str:
    url = url.strip()
    if not url:
        return ""
    backend = "vllm"
    lines = [
        "",
        "# BYO LLM (OpenAI-compat). Empty URL = off. Desk never stores the key.",
        "SHADOW_LLM_BACKEND=" + backend,
        "SHADOW_LLM_BASE_URL=" + url,
    ]
    if api_key.strip():
        lines.append("SHADOW_LLM_API_KEY=" + api_key.strip())
    if model.strip():
        lines.append("SHADOW_LLM_MODEL=" + model.strip())
    return "\n".join(lines) + "\n"


def prompt_llm(*, env_path: Path, stdin_isatty: bool, input_fn=input) -> str:
    if not stdin_isatty:
        return "skip"
    existing = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    if env_has_llm_url(existing):
        return "already"
    print("BYO LLM (OpenAI-compat URL). Enter to skip — you can add this later in .env.")
    url = input_fn("  URL [skip]: ").strip()
    if not url:
        return "skip"
    key = input_fn("  API key [optional]: ")
    model = input_fn("  model [optional]: ")
    block = render_llm_block(url=url, api_key=key, model=model)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    prev = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    env_path.write_text(prev + block, encoding="utf-8")
    print("[ok] wrote SHADOW_LLM_* to .env — Shadow plane stays off until that service is composed later.")
    return "wrote"


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional BYO LLM .env prompt.")
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    import sys

    prompt_llm(env_path=Path(args.env_file), stdin_isatty=sys.stdin.isatty())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
