#!/usr/bin/env python3
"""Tarka — unified installer and management CLI.

Usage:
    python tarka.py install                     # Interactive module picker
    python tarka.py install --all               # Full stack
    python tarka.py install --modules core,graph,ml
    python tarka.py install --lite              # Minimal: decision-api + redis + postgres
    python tarka.py start                       # Start installed modules
    python tarka.py stop                        # Stop all running services
    python tarka.py status                      # Show running services
    python tarka.py dev <module>                # Run a single module locally (no Docker)
    python tarka.py env                         # Generate .env from template
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy"
STATE_FILE = ROOT / ".tarka" / "install.json"
ENV_FILE = DEPLOY / ".env"
COMPOSE_FILE = DEPLOY / "docker-compose.yml"
COMPOSE_LITE = DEPLOY / "docker-compose.lite.yml"

# ───────────────────────────────────────────────────────────────────
# Module registry — every installable component
# ───────────────────────────────────────────────────────────────────

MODULES: dict[str, dict[str, Any]] = {
    "core": {
        "codename": "Hetu",
        "name": "Core (Decision API + Rules Engine)",
        "description": "Real-time fraud scoring, JSON rule engine, OPA integration, Redis tags/scores",
        "services": ["decision-api"],
        "infra": ["postgres", "redis"],
        "profiles": ["core"],
        "port": 8000,
        "required": True,
    },
    "graph": {
        "codename": "Jaala",
        "name": "Graph Service (Neo4j)",
        "description": "Entity resolution, link analysis, community detection, fraud ring discovery",
        "services": ["graph-service"],
        "infra": ["neo4j"],
        "profiles": ["graph"],
        "port": 8001,
    },
    "cases": {
        "codename": "Lekha",
        "name": "Case Management",
        "description": "Investigation cases, workflow automation, SAR generation, labeling",
        "services": ["case-api"],
        "infra": ["postgres"],
        "profiles": ["cases"],
        "port": 8002,
    },
    "integration": {
        "codename": "Setu",
        "name": "Integration Ingress + OSINT",
        "description": "KYC webhooks, adapter registry, 12-source OSINT enrichment",
        "services": ["integration-ingress"],
        "infra": ["postgres"],
        "profiles": ["integration"],
        "port": 8003,
    },
    "ml": {
        "codename": "Anumana",
        "name": "ML Scoring + Feature Service",
        "description": "ONNX inference, adaptive autoencoder, drift detection, feature engineering",
        "services": ["feature-service", "ml-scoring"],
        "infra": [],
        "profiles": ["ml"],
        "port": "8004-8005",
    },
    "agent": {
        "codename": "Mantri",
        "name": "Investigation Agent (AI)",
        "description": "LLM-powered investigation copilot with tool-use loop",
        "services": ["investigation-agent"],
        "infra": [],
        "profiles": ["agent"],
        "port": 8006,
        "requires": ["cases"],
        "env_keys": ["OPENAI_API_KEY"],
    },
    "streaming": {
        "codename": "Srotas",
        "name": "Event Streaming (NATS)",
        "description": "High-throughput async event ingestion via NATS JetStream",
        "services": ["event-ingest"],
        "infra": ["nats"],
        "profiles": ["streaming"],
        "port": 8007,
        "requires": ["core"],
    },
    "analytics": {
        "codename": "Ganana",
        "name": "Analytics (ClickHouse)",
        "description": "Historical analytics, decision stats, ClickHouse OLAP storage",
        "services": ["analytics-sink"],
        "infra": ["clickhouse", "nats"],
        "profiles": ["analytics"],
        "port": 8008,
        "requires": ["streaming"],
    },
    "gateway": {
        "codename": "Dvara",
        "name": "GraphQL Gateway",
        "description": "Unified GraphQL API over all REST services",
        "services": ["graphql-gateway"],
        "infra": [],
        "profiles": ["gateway"],
        "port": 8010,
        "requires": ["core"],
    },
    "frontend": {
        "codename": "Darshana",
        "name": "React Frontend",
        "description": "Dashboard, Rules Builder, Cases, OSINT, Shadow Mode, Simulation, Analytics, Graph Explorer",
        "services": ["frontend"],
        "infra": [],
        "profiles": ["ui"],
        "port": 3000,
        "requires": ["core", "cases"],
    },
}

# SDK modules (pip/npm installable, not Docker services)
SDK_MODULES: dict[str, dict[str, Any]] = {
    "sdk-python": {
        "codename": "Duta",
        "name": "Python SDK",
        "description": "Server-side Python SDK with device signal collection",
        "path": "packages/fraud-sdk-python",
        "install_cmd": "pip install -e {path}",
    },
    "sdk-typescript": {
        "codename": "Darpana",
        "name": "TypeScript SDK",
        "description": "Browser SDK with behavioral biometrics and attestation",
        "path": "packages/fraud-sdk-typescript",
        "install_cmd": "npm install {path}",
    },
    "sdk-android": {
        "codename": "Kavacha",
        "name": "Android SDK (Kotlin)",
        "description": "Android SDK with Play Integrity attestation",
        "path": "packages/fraud-sdk-android",
        "install_cmd": None,
    },
    "sdk-ios": {
        "codename": "Mudra",
        "name": "iOS SDK (Swift)",
        "description": "iOS SDK with App Attest",
        "path": "packages/fraud-sdk-ios",
        "install_cmd": None,
    },
}

# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────

class Colors:
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @staticmethod
    def supports_color() -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if platform.system() == "Windows":
            return os.environ.get("TERM") == "xterm" or "WT_SESSION" in os.environ
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


C = Colors if Colors.supports_color() else type("NoColor", (), {k: "" for k in dir(Colors) if k.isupper()})()


def _module_line(key: str, mod: dict[str, Any]) -> str:
    """Single-line label: codename + technical name + slug."""
    saga = mod.get("codename")
    if saga:
        return f"{saga} — {mod['name']} ({key})"
    return f"{mod['name']} ({key})"


def _module_saga_title(mod: dict[str, Any]) -> str:
    """Codename + technical name (no slug), for tables that already show the key."""
    saga = mod.get("codename")
    if saga:
        return f"{saga} — {mod['name']}"
    return mod["name"]


def _sdk_line(key: str, sdk: dict[str, Any]) -> str:
    saga = sdk.get("codename")
    if saga:
        return f"{saga} — {sdk['name']} ({key})"
    return f"{sdk['name']} ({key})"


def _print_banner():
    print(f"""
{C.CYAN}{C.BOLD}  ╔════════════════════════════════════════╗
  ║          T A R K A   v1.0              ║
  ║       Prove every signal.              ║
  ╚════════════════════════════════════════╝{C.RESET}
""")


def _print_module(key: str, mod: dict, selected: bool = False, index: int | None = None):
    marker = f"{C.GREEN}[x]{C.RESET}" if selected else f"{C.DIM}[ ]{C.RESET}"
    idx = f"{C.DIM}{index:>2}.{C.RESET} " if index is not None else "    "
    req = f" {C.RED}(required){C.RESET}" if mod.get("required") else ""
    deps = ""
    if mod.get("requires"):
        deps = f" {C.DIM}(needs: {', '.join(mod['requires'])}){C.RESET}"
    port = f" {C.DIM}:{mod['port']}{C.RESET}" if mod.get("port") else ""
    saga = mod.get("codename")
    title = f"{C.BOLD}{saga}{C.RESET} — {mod['name']}" if saga else f"{C.BOLD}{mod['name']}{C.RESET}"
    print(f"  {idx}{marker} {title}{C.DIM} ({key}){C.RESET}{port}{req}{deps}")
    print(f"       {C.DIM}{mod['description']}{C.RESET}")


def _save_state(modules: list[str], sdks: list[str]):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "modules": modules,
        "sdks": sdks,
        "version": "1.0.0",
    }, indent=2))


def _load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def _check_docker() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_docker_compose() -> bool:
    try:
        result = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _resolve_dependencies(selected: list[str]) -> list[str]:
    """Resolve module dependencies, adding required modules."""
    resolved = set(selected)
    changed = True
    while changed:
        changed = False
        for mod_key in list(resolved):
            mod = MODULES.get(mod_key, {})
            for dep in mod.get("requires", []):
                if dep not in resolved:
                    resolved.add(dep)
                    changed = True
    if "core" not in resolved:
        resolved.add("core")
    return sorted(resolved)


def _get_profiles(modules: list[str]) -> list[str]:
    profiles = set()
    for m in modules:
        mod = MODULES.get(m, {})
        profiles.update(mod.get("profiles", []))
    return sorted(profiles)


# ───────────────────────────────────────────────────────────────────
# Commands
# ───────────────────────────────────────────────────────────────────

def cmd_install(args):
    _print_banner()

    if not _check_docker():
        print(f"{C.RED}Docker is not running or not installed.{C.RESET}")
        print(f"Install Docker: https://docs.docker.com/get-docker/")
        sys.exit(1)

    if not _check_docker_compose():
        print(f"{C.RED}Docker Compose is not available.{C.RESET}")
        sys.exit(1)

    # Determine selected modules
    if args.all:
        selected = list(MODULES.keys())
        print(f"{C.GREEN}Installing full stack (all modules){C.RESET}\n")
    elif args.lite:
        selected = ["core", "cases", "frontend"]
        print(f"{C.GREEN}Installing lite mode (core + cases + frontend){C.RESET}\n")
    elif args.modules:
        selected = [m.strip() for m in args.modules.split(",")]
        invalid = [m for m in selected if m not in MODULES]
        if invalid:
            print(f"{C.RED}Unknown modules: {', '.join(invalid)}{C.RESET}")
            print(f"Available: {', '.join(MODULES.keys())}")
            sys.exit(1)
    else:
        selected = _interactive_picker()

    if not selected:
        print(f"{C.YELLOW}No modules selected. Exiting.{C.RESET}")
        return

    resolved = _resolve_dependencies(selected)
    if set(resolved) != set(selected):
        added = set(resolved) - set(selected)
        print(f"\n{C.YELLOW}Auto-added dependencies: {', '.join(added)}{C.RESET}")

    print(f"\n{C.BOLD}Selected modules:{C.RESET}")
    for m in resolved:
        mod = MODULES[m]
        print(f"  {C.GREEN}✓{C.RESET} {_module_line(m, mod)}")

    # SDK selection
    selected_sdks: list[str] = []
    if not args.all and not args.lite and not args.modules and not args.skip_sdks:
        print(f"\n{C.BOLD}SDK Packages (optional):{C.RESET}")
        for i, (key, sdk) in enumerate(SDK_MODULES.items(), 1):
            print(f"  {C.DIM}{i}.{C.RESET} {C.BOLD}{_sdk_line(key, sdk)}{C.RESET} — {C.DIM}{sdk['description']}{C.RESET}")
        sdk_input = input(f"\n  Enter SDK numbers (comma-separated, or Enter to skip): ").strip()
        if sdk_input:
            sdk_keys = list(SDK_MODULES.keys())
            for num in sdk_input.split(","):
                try:
                    idx = int(num.strip()) - 1
                    if 0 <= idx < len(sdk_keys):
                        selected_sdks.append(sdk_keys[idx])
                except ValueError:
                    pass
    elif args.all:
        selected_sdks = list(SDK_MODULES.keys())

    # Generate .env
    _generate_env(resolved)

    # Save state
    _save_state(resolved, selected_sdks)

    # Build and start
    profiles = _get_profiles(resolved)
    compose_args = []
    for p in profiles:
        compose_args.extend(["--profile", p])

    print(f"\n{C.BOLD}Building Docker images...{C.RESET}")
    print(f"{C.DIM}  docker compose {' '.join(compose_args)} build{C.RESET}\n")

    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE)] + compose_args + ["build"],
        cwd=str(DEPLOY),
    )
    if result.returncode != 0:
        print(f"\n{C.RED}Build failed. Check the output above.{C.RESET}")
        sys.exit(1)

    # Install SDKs
    for sdk_key in selected_sdks:
        sdk = SDK_MODULES[sdk_key]
        if sdk.get("install_cmd"):
            sdk_path = ROOT / sdk["path"]
            cmd = sdk["install_cmd"].format(path=str(sdk_path))
            print(f"\n{C.BOLD}Installing {_sdk_line(sdk_key, sdk)}...{C.RESET}")
            print(f"  {C.DIM}{cmd}{C.RESET}")
            subprocess.run(cmd.split(), cwd=str(ROOT))

    print(f"\n{C.GREEN}{C.BOLD}Installation complete!{C.RESET}")
    print(f"\n  Start services:  {C.CYAN}python tarka.py start{C.RESET}")
    print(f"  Check status:    {C.CYAN}python tarka.py status{C.RESET}")
    print(f"  View logs:       {C.CYAN}python tarka.py logs{C.RESET}")
    print(f"  Stop services:   {C.CYAN}python tarka.py stop{C.RESET}")

    if "frontend" in resolved:
        print(f"\n  {C.GREEN}Dashboard will be at: http://localhost:3000{C.RESET}")
    print(f"  {C.GREEN}Decision API:       http://localhost:8000/docs{C.RESET}")


def _interactive_picker() -> list[str]:
    """Interactive terminal module picker."""
    selected: set[str] = {"core"}
    module_keys = list(MODULES.keys())

    print(f"{C.BOLD}Select modules to install:{C.RESET}")
    print(f"{C.DIM}  (Enter numbers to toggle, 'a' for all, 'd' for done){C.RESET}\n")

    while True:
        for i, key in enumerate(module_keys, 1):
            _print_module(key, MODULES[key], selected=key in selected, index=i)
        print()

        choice = input(f"  {C.CYAN}Toggle [1-{len(module_keys)}], (a)ll, (d)one, (q)uit: {C.RESET}").strip().lower()

        if choice == "q":
            sys.exit(0)
        elif choice == "d":
            return list(selected)
        elif choice == "a":
            selected = set(module_keys)
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(module_keys):
                key = module_keys[idx]
                if MODULES[key].get("required"):
                    print(f"  {C.YELLOW}'{MODULES[key]['name']}' is required and cannot be deselected{C.RESET}")
                elif key in selected:
                    selected.discard(key)
                else:
                    selected.add(key)
        else:
            nums = [n.strip() for n in choice.split(",") if n.strip().isdigit()]
            for n in nums:
                idx = int(n) - 1
                if 0 <= idx < len(module_keys):
                    key = module_keys[idx]
                    if not MODULES[key].get("required"):
                        selected.symmetric_difference_update({key})

        print("\033[F" * (len(module_keys) * 2 + 2), end="")

    return list(selected)


def _generate_env(modules: list[str]):
    """Generate .env file with sensible defaults for selected modules."""
    lines = [
        "# Tarka environment configuration",
        "# Generated by tarka.py installer",
        "",
    ]

    if "ml" in modules:
        lines.extend([
            "# ML Scoring",
            "DISABLE_ML=false",
            "ML_SCORING_URL=http://ml-scoring:8005",
            "FEATURE_SERVICE_URL=http://feature-service:8004",
            "",
        ])

    if "graph" in modules:
        lines.extend([
            "# Graph Service",
            "GRAPH_SERVICE_URL=http://graph-service:8001",
            "NEO4J_URI=bolt://neo4j:7687",
            "NEO4J_USER=neo4j",
            "NEO4J_PASSWORD=tarka",
            "",
        ])

    if "agent" in modules:
        lines.extend([
            "# Investigation Agent",
            "OPENAI_API_KEY=sk-your-key-here",
            "ALLOWED_ANALYSTS=*",
            "",
        ])

    if "streaming" in modules or "analytics" in modules:
        lines.extend([
            "# Streaming / Analytics",
            "NATS_URL=nats://nats:4222",
            "",
        ])

    if "integration" in modules:
        lines.extend([
            "# OSINT API Keys (all optional — sources work without keys at lower limits)",
            "ABUSEIPDB_KEY=",
            "GREYNOISE_KEY=",
            "EMAILREP_KEY=",
            "NUMVERIFY_KEY=",
            "IPINFO_TOKEN=",
            "",
        ])

    lines.extend([
        "# Rate limiting",
        "RATE_LIMIT_RPM=1000",
        "",
        "# API keys (comma-separated, empty = no auth)",
        "API_KEYS=",
        "",
    ])

    ENV_FILE.write_text("\n".join(lines))
    print(f"\n{C.GREEN}Generated {ENV_FILE}{C.RESET}")


def cmd_start(args):
    state = _load_state()
    if not state.get("modules"):
        print(f"{C.YELLOW}No modules installed. Run: python tarka.py install{C.RESET}")
        sys.exit(1)

    modules = state["modules"]
    profiles = _get_profiles(modules)
    compose_args = []
    for p in profiles:
        compose_args.extend(["--profile", p])

    print(f"{C.BOLD}Starting Tarka ({len(modules)} modules)...{C.RESET}")
    for m in modules:
        print(f"  {C.GREEN}✓{C.RESET} {_module_line(m, MODULES[m])}")
    print()

    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE)] + compose_args + ["up", "-d"]
    if args.build:
        cmd.append("--build")

    subprocess.run(cmd, cwd=str(DEPLOY))

    print(f"\n{C.GREEN}Services starting...{C.RESET}")
    print(f"  Run {C.CYAN}python tarka.py status{C.RESET} to check health")
    if "frontend" in modules:
        print(f"  Dashboard: {C.CYAN}http://localhost:3000{C.RESET}")
    print(f"  Decision API: {C.CYAN}http://localhost:8000/docs{C.RESET}")


def cmd_stop(args):
    state = _load_state()
    modules = state.get("modules", list(MODULES.keys()))
    profiles = _get_profiles(modules)
    compose_args = []
    for p in profiles:
        compose_args.extend(["--profile", p])

    print(f"{C.BOLD}Stopping Tarka...{C.RESET}")
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE)] + compose_args + ["down"],
        cwd=str(DEPLOY),
    )
    print(f"{C.GREEN}All services stopped.{C.RESET}")


def cmd_status(args):
    state = _load_state()
    if not state.get("modules"):
        print(f"{C.YELLOW}No modules installed. Run: python tarka.py install{C.RESET}")
        return

    modules = state["modules"]
    profiles = _get_profiles(modules)
    compose_args = []
    for p in profiles:
        compose_args.extend(["--profile", p])

    print(f"{C.BOLD}Tarka Status{C.RESET}")
    print(f"{C.DIM}Installed modules: {', '.join(modules)}{C.RESET}\n")

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE)] + compose_args + ["ps", "--format", "table"],
        cwd=str(DEPLOY),
    )


def cmd_logs(args):
    state = _load_state()
    modules = state.get("modules", list(MODULES.keys()))
    profiles = _get_profiles(modules)
    compose_args = []
    for p in profiles:
        compose_args.extend(["--profile", p])

    extra = []
    if args.follow:
        extra.append("-f")
    if args.tail:
        extra.extend(["--tail", args.tail])
    if args.service:
        extra.append(args.service)

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE)] + compose_args + ["logs"] + extra,
        cwd=str(DEPLOY),
    )


def cmd_dev(args):
    """Run a single service locally without Docker (for development)."""
    service = args.service
    service_dir = ROOT / "services" / service

    if not service_dir.exists():
        print(f"{C.RED}Service '{service}' not found at {service_dir}{C.RESET}")
        print(f"Available: {', '.join(d.name for d in (ROOT / 'services').iterdir() if d.is_dir() and not d.name.startswith('.'))}")
        sys.exit(1)

    pyproject = service_dir / "pyproject.toml"
    if not pyproject.exists():
        print(f"{C.RED}No pyproject.toml found for '{service}'{C.RESET}")
        sys.exit(1)

    print(f"{C.BOLD}Starting {service} in development mode...{C.RESET}")

    # Install dependencies
    print(f"{C.DIM}Installing dependencies...{C.RESET}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", f".[dev]"], cwd=str(service_dir), capture_output=True)

    # Determine the module name and port
    port_map = {
        "decision-api": ("decision_api.main:app", "8000"),
        "graph-service": ("graph_service.main:app", "8001"),
        "case-api": ("case_api.main:app", "8002"),
        "integration-ingress": ("integration_ingress.main:app", "8003"),
        "feature-service": ("feature_service.main:app", "8004"),
        "ml-scoring": ("ml_scoring.main:app", "8005"),
        "investigation-agent": ("investigation_agent.main:app", "8006"),
        "event-ingest": ("event_ingest.main:app", "8007"),
        "analytics-sink": ("analytics_sink.main:app", "8008"),
        "graphql-gateway": ("graphql_gateway.main:app", "8010"),
    }

    if service not in port_map:
        print(f"{C.RED}No dev configuration for '{service}'{C.RESET}")
        sys.exit(1)

    module, port = port_map[service]
    env = {**os.environ, "PYTHONPATH": str(service_dir / "src")}

    print(f"\n{C.GREEN}Running on http://localhost:{port}{C.RESET}")
    print(f"{C.DIM}Press Ctrl+C to stop{C.RESET}\n")

    subprocess.run(
        [sys.executable, "-m", "uvicorn", module, "--host", "0.0.0.0", "--port", port, "--reload"],
        cwd=str(service_dir),
        env=env,
    )


def cmd_env(args):
    """Generate or display environment configuration."""
    state = _load_state()
    modules = state.get("modules", ["core"])
    _generate_env(modules)
    print(f"\nEdit the file at: {C.CYAN}{ENV_FILE}{C.RESET}")


def cmd_uninstall(args):
    """Remove all Tarka containers, volumes, and state."""
    print(f"{C.BOLD}Uninstalling Tarka...{C.RESET}")

    if not args.yes:
        confirm = input(f"  {C.YELLOW}This will remove all containers and data. Continue? [y/N]: {C.RESET}").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "full", "down", "-v", "--remove-orphans"],
        cwd=str(DEPLOY),
    )

    if STATE_FILE.exists():
        STATE_FILE.unlink()
    if STATE_FILE.parent.exists():
        shutil.rmtree(STATE_FILE.parent, ignore_errors=True)

    print(f"{C.GREEN}Tarka uninstalled.{C.RESET}")


def cmd_info(args):
    """Show information about a specific module."""
    key = args.module
    if key in MODULES:
        mod = MODULES[key]
        print(f"\n{C.BOLD}{_module_line(key, mod)}{C.RESET}")
        print(f"  {mod['description']}\n")
        print(f"  {C.DIM}Services:{C.RESET}  {', '.join(mod['services'])}")
        print(f"  {C.DIM}Infra:{C.RESET}     {', '.join(mod.get('infra', [])) or 'none'}")
        print(f"  {C.DIM}Port(s):{C.RESET}   {mod.get('port', 'N/A')}")
        if mod.get("requires"):
            print(f"  {C.DIM}Requires:{C.RESET}  {', '.join(mod['requires'])}")
        if mod.get("env_keys"):
            print(f"  {C.DIM}Env vars:{C.RESET}  {', '.join(mod['env_keys'])}")
    elif key in SDK_MODULES:
        sdk = SDK_MODULES[key]
        print(f"\n{C.BOLD}{_sdk_line(key, sdk)}{C.RESET}")
        print(f"  {sdk['description']}\n")
        print(f"  {C.DIM}Path:{C.RESET}    {sdk['path']}")
        if sdk.get("install_cmd"):
            print(f"  {C.DIM}Install:{C.RESET} {sdk['install_cmd'].format(path=sdk['path'])}")
    else:
        print(f"{C.RED}Unknown module: {key}{C.RESET}")
        print(f"Available modules: {', '.join(list(MODULES.keys()) + list(SDK_MODULES.keys()))}")


def cmd_list(args):
    """List all available modules."""
    _print_banner()

    state = _load_state()
    installed = set(state.get("modules", []))

    print(f"{C.BOLD}Service Modules:{C.RESET}\n")
    for key, mod in MODULES.items():
        marker = f"{C.GREEN}●{C.RESET}" if key in installed else f"{C.DIM}○{C.RESET}"
        req = f" {C.RED}(required){C.RESET}" if mod.get("required") else ""
        port = f" {C.DIM}:{mod['port']}{C.RESET}" if mod.get("port") else ""
        print(f"  {marker} {C.BOLD}{key:<15}{C.RESET} {_module_saga_title(mod)}{port}{req}")
        print(f"    {C.DIM}{mod['description']}{C.RESET}")

    print(f"\n{C.BOLD}SDK Packages:{C.RESET}\n")
    for key, sdk in SDK_MODULES.items():
        installed_sdks = set(state.get("sdks", []))
        marker = f"{C.GREEN}●{C.RESET}" if key in installed_sdks else f"{C.DIM}○{C.RESET}"
        saga = sdk.get("codename")
        sdk_title = f"{saga} — {sdk['name']}" if saga else sdk["name"]
        print(f"  {marker} {C.BOLD}{key:<15}{C.RESET} {sdk_title}")
        print(f"    {C.DIM}{sdk['description']}{C.RESET}")

    if installed:
        print(f"\n{C.DIM}● = installed   ○ = not installed{C.RESET}")


def cmd_add(args):
    """Add a module to an existing installation."""
    state = _load_state()
    current = set(state.get("modules", []))

    new_modules = [m.strip() for m in args.modules.split(",")]
    invalid = [m for m in new_modules if m not in MODULES]
    if invalid:
        print(f"{C.RED}Unknown modules: {', '.join(invalid)}{C.RESET}")
        sys.exit(1)

    combined = list(current | set(new_modules))
    resolved = _resolve_dependencies(combined)

    added = set(resolved) - current
    if not added:
        print(f"{C.YELLOW}All specified modules are already installed.{C.RESET}")
        return

    print(f"{C.BOLD}Adding modules:{C.RESET}")
    for m in sorted(added):
        print(f"  {C.GREEN}+{C.RESET} {_module_line(m, MODULES[m])}")

    _save_state(resolved, state.get("sdks", []))
    _generate_env(resolved)

    profiles = _get_profiles(list(added))
    compose_args = []
    for p in profiles:
        compose_args.extend(["--profile", p])

    print(f"\n{C.BOLD}Building new services...{C.RESET}")
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE)] + _get_all_profile_args(resolved) + ["build"],
        cwd=str(DEPLOY),
    )

    print(f"\n{C.GREEN}Module(s) added. Run {C.CYAN}python tarka.py start{C.GREEN} to start.{C.RESET}")


def cmd_remove(args):
    """Remove a module from the installation."""
    state = _load_state()
    current = set(state.get("modules", []))

    to_remove = [m.strip() for m in args.modules.split(",")]

    for m in to_remove:
        if m not in MODULES:
            print(f"{C.RED}Unknown module: {m}{C.RESET}")
            sys.exit(1)
        if MODULES[m].get("required"):
            print(f"{C.RED}Cannot remove required module: {_module_line(m, MODULES[m])}{C.RESET}")
            sys.exit(1)

    remaining = current - set(to_remove)
    resolved = _resolve_dependencies(list(remaining))

    removed = current - set(resolved)
    print(f"{C.BOLD}Removing modules:{C.RESET}")
    for m in sorted(removed):
        print(f"  {C.RED}−{C.RESET} {_module_line(m, MODULES[m])}")

    _save_state(resolved, state.get("sdks", []))
    print(f"\n{C.GREEN}Module(s) removed. Restart with {C.CYAN}python tarka.py start{C.GREEN}.{C.RESET}")


def _get_all_profile_args(modules: list[str]) -> list[str]:
    profiles = _get_profiles(modules)
    args_list = []
    for p in profiles:
        args_list.extend(["--profile", p])
    return args_list


# ───────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="tarka",
        description="Tarka — fraud detection platform installer and manager",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # install
    p_install = subparsers.add_parser("install", help="Install Tarka modules")
    p_install.add_argument("--all", action="store_true", help="Install all modules")
    p_install.add_argument("--lite", action="store_true", help="Install lite mode (core + cases + frontend)")
    p_install.add_argument("--modules", "-m", type=str, help="Comma-separated module list")
    p_install.add_argument("--skip-sdks", action="store_true", help="Skip SDK installation prompt")
    p_install.set_defaults(func=cmd_install)

    # start
    p_start = subparsers.add_parser("start", help="Start installed services")
    p_start.add_argument("--build", action="store_true", help="Rebuild images before starting")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = subparsers.add_parser("stop", help="Stop all services")
    p_stop.set_defaults(func=cmd_stop)

    # status
    p_status = subparsers.add_parser("status", help="Show service status")
    p_status.set_defaults(func=cmd_status)

    # logs
    p_logs = subparsers.add_parser("logs", help="View service logs")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p_logs.add_argument("--tail", type=str, default="100", help="Number of lines to show")
    p_logs.add_argument("service", nargs="?", help="Specific service name")
    p_logs.set_defaults(func=cmd_logs)

    # dev
    p_dev = subparsers.add_parser("dev", help="Run a single service locally (no Docker)")
    p_dev.add_argument("service", help="Service name (e.g., decision-api)")
    p_dev.set_defaults(func=cmd_dev)

    # env
    p_env = subparsers.add_parser("env", help="Generate .env configuration")
    p_env.set_defaults(func=cmd_env)

    # list
    p_list = subparsers.add_parser("list", help="List all available modules")
    p_list.set_defaults(func=cmd_list)

    # info
    p_info = subparsers.add_parser("info", help="Show details about a module")
    p_info.add_argument("module", help="Module name")
    p_info.set_defaults(func=cmd_info)

    # add
    p_add = subparsers.add_parser("add", help="Add module(s) to existing installation")
    p_add.add_argument("modules", help="Comma-separated module names")
    p_add.set_defaults(func=cmd_add)

    # remove
    p_remove = subparsers.add_parser("remove", help="Remove module(s) from installation")
    p_remove.add_argument("modules", help="Comma-separated module names")
    p_remove.set_defaults(func=cmd_remove)

    # uninstall
    p_uninstall = subparsers.add_parser("uninstall", help="Remove all Tarka containers and data")
    p_uninstall.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p_uninstall.set_defaults(func=cmd_uninstall)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        print(f"\n{C.DIM}Quick start:{C.RESET}")
        print(f"  {C.CYAN}python tarka.py install --all{C.RESET}    Full stack")
        print(f"  {C.CYAN}python tarka.py install --lite{C.RESET}   Minimal setup")
        print(f"  {C.CYAN}python tarka.py install{C.RESET}          Interactive picker")
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
