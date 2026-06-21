"""Run ``uvicorn tarka_management.app:app`` with ``TARKA_MANAGEMENT_*`` env."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("TARKA_MANAGEMENT_BIND_HOST", "127.0.0.1").strip()
    port_s = os.environ.get("TARKA_MANAGEMENT_BIND_PORT", "8019").strip()
    try:
        port = int(port_s)
    except ValueError as exc:
        raise SystemExit(f"invalid TARKA_MANAGEMENT_BIND_PORT: {port_s!r}") from exc

    uvicorn.run(
        "tarka_management.app:app",
        host=host,
        port=port,
        factory=False,
        reload=os.environ.get("TARKA_MANAGEMENT_RELOAD", "").strip().lower()
        in ("1", "true", "yes", "on"),
    )


if __name__ == "__main__":
    main()
