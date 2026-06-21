#!/usr/bin/env python3
"""Apply ClickHouse UP (or DOWN) section from a migrations/*.sql file."""

from __future__ import annotations

import argparse
import base64
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _http_post_sql(
    *,
    base_url: str,
    user: str,
    password: str,
    sql: str,
    connect_timeout_s: float,
    read_timeout_s: float,
    multiquery: bool = False,
) -> None:
    params = "wait_end_of_query=1"
    if multiquery:
        params += "&multiquery=1"
    url = f"{base_url.rstrip('/')}/?{params}"
    req = urllib.request.Request(url, data=sql.encode("utf-8"), method="POST")
    token = base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urllib.request.urlopen(
            req, timeout=(connect_timeout_s, read_timeout_s)
        ) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:8192]
        raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ClickHouse connection error: {exc}") from exc
    text = raw.decode("utf-8", errors="replace").strip()
    if text.startswith("Code:") or "\nCode:\t" in text[:512]:
        raise RuntimeError(f"ClickHouse error: {text[:4096]}")


def _strip_sql_comments(section: str) -> str:
    lines = [
        line
        for line in section.splitlines()
        if line.strip() and not line.strip().startswith("--")
    ]
    return "\n".join(lines).strip()


def _split_statements(section: str) -> list[str]:
    """Split on blank-line boundaries (avoids breaking ``INTERVAL N YEAR;`` TTL lines)."""
    stripped: list[str] = []
    for part in re.split(r";\s*\n\s*\n", section):
        body = _strip_sql_comments(part).strip()
        if body:
            stripped.append(body)
    return stripped


def _section_marker_pattern(marker: str) -> str:
    return rf"--\s*={{20,}}\s*\n--\s*{re.escape(marker)}\s*\n--\s*={{20,}}"


def _extract_section(text: str, marker: str) -> str:
    parts = re.split(_section_marker_pattern(marker), text, maxsplit=1)
    if len(parts) < 2:
        raise ValueError(f"missing {marker} section marker in migration file")
    return parts[1]


def parse_migration_section(path: Path, *, direction: str) -> str:
    raw = path.read_text(encoding="utf-8")
    if direction == "up":
        after_up = _extract_section(raw, "UP")
        down_split = re.split(_section_marker_pattern("DOWN"), after_up, maxsplit=1)
        section = down_split[0]
    else:
        section = _extract_section(raw, "DOWN")
    body = _strip_sql_comments(section)
    if not body:
        raise ValueError(f"empty {direction} section in {path}")
    return body


def parse_migration(path: Path, *, direction: str) -> list[str]:
    """Legacy helper: one statement per blank-line-delimited chunk."""
    return _split_statements(parse_migration_section(path, direction=direction))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration", type=Path, help="Path to migrations/*.sql")
    parser.add_argument(
        "--direction",
        choices=("up", "down"),
        default="up",
        help="Apply UP or DOWN block (default: up)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--user", default="default")
    parser.add_argument("--password", default="")
    parser.add_argument("--secure", action="store_true")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    path = args.migration.resolve()
    if not path.is_file():
        print(f"migration not found: {path}", file=sys.stderr)
        return 2

    scheme = "https" if args.secure else "http"
    base_url = f"{scheme}://{args.host}:{args.port}"
    sql = parse_migration_section(path, direction=args.direction)
    preview = sql.split("\n", 1)[0][:120]
    print(f"Applying {path.name} ({args.direction}): {preview}…")
    _http_post_sql(
        base_url=base_url,
        user=args.user,
        password=args.password,
        sql=sql,
        connect_timeout_s=args.connect_timeout,
        read_timeout_s=args.read_timeout,
        multiquery=True,
    )
    print("ClickHouse migration OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
