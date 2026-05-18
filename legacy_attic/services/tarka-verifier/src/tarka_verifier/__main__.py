"""Run the verifier HTTP service."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("TARKA_VERIFIER_BIND_HOST", "127.0.0.1").strip()
    port_s = os.environ.get("TARKA_VERIFIER_BIND_PORT", "8028").strip()
    port = int(port_s)

    uvicorn.run(
        "tarka_verifier.app:app",
        host=host,
        port=port,
        factory=False,
        reload=os.environ.get("TARKA_VERIFIER_RELOAD", "").strip().lower()
        in ("1", "true", "yes", "on"),
    )


if __name__ == "__main__":
    main()
