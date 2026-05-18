"""Tarka v2 CLI: compose lifecycle + orchestrator ``GET /health/full`` status matrix."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import typer

app = typer.Typer(
    name="tarka",
    help="Tarka v2 stack: Docker Compose control and orchestrator health.",
    no_args_is_help=True,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ANSI (TTY only)
_C_RESET = "\033[0m"
_C_RED = "\033[31m"
_C_GREEN = "\033[32m"
_C_YELLOW = "\033[33m"
_C_DIM = "\033[2m"


def _colorize(text: str, code: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{code}{text}{_C_RESET}"


def _resolve_compose_file() -> Path:
    raw = os.environ.get("DOCKER_COMPOSE_FILE", "docker-compose.yml")
    path = Path(raw)
    if path.is_absolute():
        return path
    return _REPO_ROOT / path


def _compose_cmd() -> list[str]:
    """Prefer Docker Compose v2 plugin; fall back to docker-compose v1."""
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return ["docker", "compose"]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ["docker-compose"]


def _orchestrator_base() -> str:
    raw = os.environ.get("TARKA_ORCHESTRATOR_BASE", "http://127.0.0.1:8790").strip().rstrip("/")
    # Accept accidental ingest URL from env hints.
    if raw.endswith("/v1/ingest"):
        raw = raw[: -len("/v1/ingest")].rstrip("/")
    return raw


def _fetch_health_full(base: str, timeout_s: float = 8.0) -> tuple[dict[str, Any] | None, str | None]:
    """Return (payload, error_message). On success error_message is None."""
    url = f"{base.rstrip('/')}/health/full"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw), None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return None, f"HTTP {exc.code} from {url}: {body[:200]}"
    except urllib.error.URLError as exc:
        return None, f"{exc.reason or exc}"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON from {url}: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return None, str(exc)


def _print_offline_matrix(error: str, use_color: bool) -> None:
    """When orchestrator is unreachable, still emit a stable matrix (gate: no traceback)."""
    rows = [
        ("orchestrator", "offline", error[:120]),
        ("rule_engine", "unknown", "not probed (orchestrator unreachable)"),
        ("shadow_agent", "unknown", "not probed (orchestrator unreachable)"),
    ]
    _print_table(rows, use_color)


def _print_table_from_payload(payload: dict[str, Any], use_color: bool) -> None:
    svcs = payload.get("services")
    if not isinstance(svcs, list):
        _print_offline_matrix("invalid /health/full payload (missing services[])", use_color)
        return
    rows: list[tuple[str, str, str]] = []
    for item in svcs:
        if not isinstance(item, dict):
            continue
        comp = str(item.get("component", "?"))
        st = str(item.get("status", "?"))
        lat = item.get("latency_ms")
        detail = str(item.get("detail", ""))
        lat_s = "" if lat is None else f"{lat}ms"
        rows.append((comp, st, " ".join(x for x in (lat_s, detail) if x).strip()))
    if not rows:
        _print_offline_matrix("empty services list", use_color)
        return
    _print_table(rows, use_color)


def _status_style(status: str) -> str:
    u = status.strip().lower()
    if u == "ok":
        return "ok"
    if u == "offline":
        return "bad"
    if u == "degraded":
        return "warn"
    if u == "not_configured":
        return "dim"
    if u == "unknown":
        return "dim"
    return "warn"


def _print_table(rows: list[tuple[str, str, str]], use_color: bool) -> None:
    w_comp = max(len(r[0]) for r in rows)
    header = f"{'COMPONENT'.ljust(w_comp)}  STATUS  DETAIL"
    print(header)
    print("-" * min(len(header), 120))
    for comp, status, detail in rows:
        st_display = status
        if use_color:
            style = _status_style(status)
            if style == "ok":
                st_display = _colorize(status, _C_GREEN, True)
            elif style == "bad":
                st_display = _colorize(status, _C_RED, True)
            elif style == "dim":
                st_display = _colorize(status, _C_DIM, True)
            else:
                st_display = _colorize(status, _C_YELLOW, True)
        print(f"{comp.ljust(w_comp)}  {st_display}  {detail}")


@app.command()
def start(
    detach: bool = typer.Option(True, "--detach/--no-detach", help="Run compose in detached mode."),
) -> None:
    """Run ``docker compose up`` for the repo compose file (default root ``docker-compose.yml``)."""
    compose = _resolve_compose_file()
    if not compose.is_file():
        typer.secho(f"Compose file not found: {compose}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    cmd = _compose_cmd() + ["-f", str(compose), "up"]
    if detach:
        cmd.append("-d")
    typer.echo(f"+ cd {_REPO_ROOT} && {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), check=True)


@app.command()
def stop() -> None:
    """Run ``docker compose down``."""
    compose = _resolve_compose_file()
    if not compose.is_file():
        typer.secho(f"Compose file not found: {compose}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    cmd = _compose_cmd() + ["-f", str(compose), "down"]
    typer.echo(f"+ cd {_REPO_ROOT} && {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), check=True)


@app.command()
def status(
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON from /health/full."),
) -> None:
    """GET orchestrator ``/health/full`` and print a color-coded status table."""
    base = _orchestrator_base()
    use_color = sys.stdout.isatty()
    payload, err = _fetch_health_full(base)
    if json_out:
        if payload is not None:
            print(json.dumps(payload, indent=2))
            raise typer.Exit(code=0)
        typer.secho(json.dumps({"error": err, "orchestrator_base": base}, indent=2), fg=typer.colors.RED)
        raise typer.Exit(code=1)

    if payload is None:
        typer.secho(f"tarka status: orchestrator unreachable at {base} ({err})", fg=typer.colors.RED, err=True)
        _print_offline_matrix(err or "unknown error", use_color)
        raise typer.Exit(code=1)

    gen = payload.get("generated_at", "")
    if gen:
        print(f"tarka status  orchestrator={base}  generated_at={gen}")
    else:
        print(f"tarka status  orchestrator={base}")
    _print_table_from_payload(payload, use_color)


@app.command("export-audit")
def export_audit(
    output: Path = typer.Option(
        Path("export.json"),
        "--output",
        "-o",
        help="Destination JSON file (default: ./export.json).",
    ),
    limit: int = typer.Option(100, "--limit", min=1, max=500, help="Maximum audit rows to export."),
) -> None:
    """Export the last N ``audit_logs`` rows with PII masking (beta feedback bundle)."""
    from tarka_v2_core.audit_export import ExportAuditError, run_export_audit

    try:
        run_export_audit(output, limit=limit)
    except ExportAuditError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.secho(f"Wrote {output.resolve()} ({limit} max rows)", fg=typer.colors.GREEN)


@app.command("nuke")
def nuke_cmd(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt (non-interactive / automation only).",
    ),
    remove_volumes: bool = typer.Option(
        False,
        "--remove-volumes",
        "-v",
        help="Also run ``docker compose down -v`` (remove named Docker volumes declared in the compose file).",
    ),
    skip_compose: bool = typer.Option(
        False,
        "--skip-compose",
        help="Skip ``docker compose down`` (no Docker on host); still deletes SQLite audit files.",
    ),
) -> None:
    """Tear down sidecar containers, remove the compose network, and wipe local SQLite audit DB files."""
    from tarka_v2_core.nuke import NukeError, run_nuke

    typer.secho(
        "WARNING: This will destroy local audit data.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.secho(
        "All audit_logs (and other data) in the configured SQLite database file(s) will be "
        "PERMANENTLY deleted. This cannot be undone.",
        fg=typer.colors.RED,
        err=True,
    )
    if skip_compose:
        typer.secho(
            "(--skip-compose) Docker will NOT be invoked; containers/networks are unchanged.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    else:
        typer.secho(
            "Docker containers for this compose project will be stopped and removed, and the "
            "project network will be removed.",
            err=True,
        )

    if not yes:
        while True:
            typer.echo(
                "Type Y to destroy all audit data and tear down sidecars, or N to abort: ",
                nl=False,
            )
            line = sys.stdin.readline()
            if not line:
                typer.echo("\nAborted.")
                raise typer.Exit(code=1)
            ans = line.strip().upper()
            if ans == "N":
                typer.echo("Aborted.")
                raise typer.Exit(code=0)
            if ans == "Y":
                break
            typer.echo("Please type exactly Y or N.")

    compose = _resolve_compose_file()
    if not skip_compose and not compose.is_file():
        typer.secho(f"Compose file not found: {compose}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    try:
        _, deleted = run_nuke(
            repo_root=_REPO_ROOT,
            compose_file=compose,
            compose_argv_prefix=_compose_cmd(),
            remove_named_volumes=remove_volumes,
            skip_compose=skip_compose,
        )
    except NukeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if skip_compose:
        typer.secho("Skipped docker compose (containers/network unchanged).", fg=typer.colors.YELLOW)
    else:
        typer.secho("Compose stack torn down (containers + project network).", fg=typer.colors.GREEN)
    if deleted:
        for p in deleted:
            typer.secho(f"Removed database file: {p}", fg=typer.colors.GREEN)
    else:
        typer.secho(
            "No SQLite database files were removed (none of the candidate paths existed).",
            fg=typer.colors.YELLOW,
        )


@app.command("import-rules")
def import_rules_cmd(
    filepath: Path = typer.Argument(
        ...,
        metavar="FILEPATH",
        help="JSON file: array of rules or {\"rules\": [ ... ]} (AST matches rule_engine.ast_schemas.Rule).",
    ),
    skip_reload: bool = typer.Option(
        False,
        "--skip-reload",
        help="Write DB only; do not POST /v1/rules/reload on the rule-engine sidecar.",
    ),
) -> None:
    """Validate rules JSON, upsert into ``engine_rules`` (Shadow DB), then hot-reload the engine cache."""
    from tarka_v2_core.rules_import import ImportRulesError, run_import_rules

    try:
        n, reload_err = run_import_rules(filepath, skip_reload=skip_reload)
    except ImportRulesError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    typer.secho(f"Imported {n} rule(s) into engine_rules.", fg=typer.colors.GREEN)
    if reload_err:
        typer.secho(f"Reload warning: {reload_err}", fg=typer.colors.YELLOW, err=True)


@app.command("logs")
def logs_cmd(
    service: str = typer.Argument(..., help="Compose service name (e.g. core_api, postgres)."),
    follow: bool = typer.Option(False, "-f", "--follow", help="Stream logs."),
    tail: str | None = typer.Option(None, "--tail", help="Number of lines (default: all)."),
) -> None:
    """Run ``docker compose logs`` for a service."""
    compose = _resolve_compose_file()
    if not compose.is_file():
        typer.secho(f"Compose file not found: {compose}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    cmd = _compose_cmd() + ["-f", str(compose), "logs"]
    if follow:
        cmd.append("-f")
    if tail is not None:
        cmd.extend(["--tail", tail])
    cmd.append(service)
    typer.echo(f"+ cd {_REPO_ROOT} && {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(_REPO_ROOT), check=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
