"""Ollama subprocess helper: merge environments without imposing RAM caps in core code.

Parallelism and loaded-model limits belong in **deployment** config (for example
``docker-compose.local.yml`` sets ``OLLAMA_NUM_PARALLEL`` / ``OLLAMA_MAX_LOADED_MODELS`` on the
``ollama`` service). This module only forwards ``os.environ`` plus optional ``base`` overrides for
``subprocess.Popen`` / ``exec``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

# Gate / ops: leave headroom for macOS + graph DB + browser (M5 Pro 24GB class).
RSS_HEADROOM_LIMIT_BYTES = 16 * 1024 * 1024 * 1024


def ollama_resource_environ(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a full environment mapping: current process env merged with ``base``.

    Does **not** set ``OLLAMA_NUM_PARALLEL`` or ``OLLAMA_MAX_LOADED_MODELS`` — configure those on the
    Ollama container / host (see repo ``docker-compose.local.yml`` for demo laptop caps).
    """
    merged: dict[str, str] = {str(k): str(v) for k, v in os.environ.items()}
    if base is not None:
        merged.update({str(k): str(v) for k, v in base.items()})
    return merged


def popen_ollama(argv: list[str], **kwargs: Any) -> subprocess.Popen[str]:
    """``subprocess.Popen(['ollama', *argv], env=ollama_resource_environ(...))`` with forwarded kwargs."""
    if not argv:
        raise ValueError("argv must contain at least one ollama subcommand, e.g. ['serve']")
    env_in = kwargs.pop("env", None)
    env = ollama_resource_environ(env_in)
    return subprocess.Popen(["ollama", *argv], env=env, text=True, **kwargs)


def exec_ollama(argv: list[str] | None = None) -> None:
    """Replace this process with ``ollama`` (default: ``ollama serve``)."""
    args = ["ollama", *(argv or ["serve"])]
    os.execvpe("ollama", args, ollama_resource_environ())


def main() -> None:
    """CLI: ``python -m shadow_agent.ollama_resource_guard [ollama args…]`` (default ``serve``)."""
    argv = sys.argv[1:]
    exec_ollama(argv or ["serve"])


if __name__ == "__main__":
    main()
