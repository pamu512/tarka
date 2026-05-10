"""Resolve ``custom_signal`` AST nodes in Python before handing features to the Rust rule engine."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SIGNAL_RESOLUTION_TIMEOUT_S = 0.05
_MAX_PARAMS_JSON_BYTES = 8192

_CustomSignalHandler = Callable[..., Any]

_GLOBAL_RESOLVER_LOCK = threading.Lock()
_GLOBAL_RESOLVER: SignalResolver | None = None
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tarka_signal_")


class SignalResolver:
    """Maps ``plugin_id`` to callables; resolves signals under a strict wall-clock timeout."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: dict[str, _CustomSignalHandler] = {}

    def register(self, plugin_id: str, fn: _CustomSignalHandler) -> None:
        if not plugin_id or not plugin_id.strip():
            raise ValueError("plugin_id must be non-empty")
        self._handlers[plugin_id.strip()] = fn

    def unregister(self, plugin_id: str) -> None:
        self._handlers.pop(plugin_id.strip(), None)

    def clear(self) -> None:
        self._handlers.clear()

    def has_handler(self, plugin_id: str) -> bool:
        return plugin_id.strip() in self._handlers

    def _invoke(
        self,
        plugin_id: str,
        params: dict[str, Any],
        *,
        features: dict[str, Any],
        tenant_id: str,
        entity_id: str,
    ) -> Any:
        fn = self._handlers.get(plugin_id.strip())
        if fn is None:
            raise LookupError(f"unregistered plugin_id={plugin_id!r}")
        return fn(params, features=features, tenant_id=tenant_id, entity_id=entity_id)

    def resolve_spec(
        self,
        plugin_id: str,
        params: dict[str, Any],
        output_key: str,
        *,
        features: dict[str, Any],
        tenant_id: str,
        entity_id: str,
        timeout_s: float = DEFAULT_SIGNAL_RESOLUTION_TIMEOUT_S,
    ) -> Any:
        """Return handler result, ``None`` on timeout / error / missing handler (caller logs)."""
        tid = (tenant_id or "").strip() or "default"
        eid = (entity_id or "").strip() or "default"
        feat = dict(features) if isinstance(features, dict) else {}

        def _run() -> Any:
            return self._invoke(plugin_id, params, features=feat, tenant_id=tid, entity_id=eid)

        fut: Future[Any] = _EXECUTOR.submit(_run)
        try:
            return fut.result(timeout=timeout_s)
        except FuturesTimeoutError:
            raise TimeoutError(f"plugin_id={plugin_id!r} output_key={output_key!r}") from None

    def resolve_all(
        self,
        specs: Iterable[tuple[str, dict[str, Any], str]],
        *,
        features: dict[str, Any],
        tenant_id: str,
        entity_id: str,
        timeout_s: float = DEFAULT_SIGNAL_RESOLUTION_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Build the ``resolved_signals`` map: ``output_key -> value`` (failures become ``None``).

        Callers merge this dict into the request feature map before sending JSON to ``tarka_rule_engine``.
        Logs ``SIGNAL_RESOLUTION_FAILED`` on invalid spec, missing handler, timeout, or handler error.
        """
        resolved: dict[str, Any] = {}
        tid = (tenant_id or "").strip() or "default"
        eid = (entity_id or "").strip() or "default"
        base = dict(features) if isinstance(features, dict) else {}

        for plugin_id, params, output_key in specs:
            ok = (output_key or "").strip()
            pid = (plugin_id or "").strip()
            if not ok or not pid:
                log.warning(
                    "SIGNAL_RESOLUTION_FAILED plugin_id=%r output_key=%r reason=%s",
                    plugin_id,
                    output_key,
                    "invalid_spec",
                )
                continue
            if not self.has_handler(pid):
                log.warning(
                    "SIGNAL_RESOLUTION_FAILED plugin_id=%r output_key=%r reason=%s",
                    pid,
                    ok,
                    "unregistered_plugin",
                )
                resolved[ok] = None
                continue
            try:
                val = self.resolve_spec(
                    pid,
                    params,
                    ok,
                    features=base,
                    tenant_id=tid,
                    entity_id=eid,
                    timeout_s=timeout_s,
                )
                resolved[ok] = val
                base[ok] = val
            except TimeoutError as e:
                log.warning(
                    "SIGNAL_RESOLUTION_FAILED plugin_id=%r output_key=%r reason=%s",
                    pid,
                    ok,
                    e,
                )
                resolved[ok] = None
                base[ok] = None
            except Exception as e:
                log.warning(
                    "SIGNAL_RESOLUTION_FAILED plugin_id=%r output_key=%r reason=%s",
                    pid,
                    ok,
                    e,
                )
                resolved[ok] = None
                base[ok] = None
        return resolved


def default_signal_resolver() -> SignalResolver:
    global _GLOBAL_RESOLVER
    with _GLOBAL_RESOLVER_LOCK:
        if _GLOBAL_RESOLVER is None:
            _GLOBAL_RESOLVER = SignalResolver()
        return _GLOBAL_RESOLVER


def register_custom_signal(plugin_id: str, fn: _CustomSignalHandler) -> None:
    """Register a handler callable for use by the Visual Builder / JSON rules."""
    default_signal_resolver().register(plugin_id, fn)


def unregister_custom_signal(plugin_id: str) -> None:
    default_signal_resolver().unregister(plugin_id)


def iter_custom_signal_specs(ast: Any) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Yield ``(plugin_id, params, output_key)`` for every ``custom_signal`` node in a dict AST."""
    if not isinstance(ast, dict):
        return
    typ = ast.get("type")
    if typ == "custom_signal":
        pid = ast.get("plugin_id")
        out_k = ast.get("output_key")
        raw_p = ast.get("params")
        params: dict[str, Any] = raw_p if isinstance(raw_p, dict) else {}
        if isinstance(pid, str) and isinstance(out_k, str) and pid.strip() and out_k.strip():
            safe_params = params
            try:
                blob = json.dumps(params, sort_keys=True, separators=(",", ":")).encode()
                if len(blob) > _MAX_PARAMS_JSON_BYTES:
                    log.warning(
                        "SIGNAL_RESOLUTION_FAILED plugin_id=%r output_key=%r reason=%s",
                        pid.strip(),
                        out_k.strip(),
                        "params_too_large",
                    )
                    safe_params = {}
            except (TypeError, ValueError):
                safe_params = {}
            yield (pid.strip(), safe_params, out_k.strip())
    ch = ast.get("children")
    if isinstance(ch, list):
        for child in ch:
            yield from iter_custom_signal_specs(child)


def collect_custom_signal_specs_from_packs(
    packs: Iterable[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], str]]:
    """Unique resolution tasks across all ``when_ast`` trees (order preserved)."""
    out: list[tuple[str, dict[str, Any], str]] = []
    seen: set[tuple[str, str, str]] = set()
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        rules = pack.get("rules")
        if not isinstance(rules, list):
            continue
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            raw = rule.get("when_ast")
            if raw is None or not isinstance(raw, dict):
                continue
            for spec in iter_custom_signal_specs(raw):
                pid, params, ok = spec
                dedup = (pid, json.dumps(params, sort_keys=True, separators=(",", ":")), ok)
                if dedup in seen:
                    continue
                seen.add(dedup)
                out.append(spec)
    return out


def merge_features_with_resolved_from_ast(
    features: dict[str, Any],
    ast: dict[str, Any] | Any,
    *,
    tenant_id: str = "default",
    entity_id: str = "default",
    timeout_s: float = DEFAULT_SIGNAL_RESOLUTION_TIMEOUT_S,
    resolver: SignalResolver | None = None,
) -> dict[str, Any]:
    """Resolve every ``custom_signal`` under ``ast``, merge ``resolved_signals`` into features, return one dict for Rust."""
    r = resolver or default_signal_resolver()
    if not isinstance(ast, dict):
        return dict(features) if isinstance(features, dict) else {}
    specs = list(iter_custom_signal_specs(ast))
    resolved_signals = r.resolve_all(
        specs,
        features=features if isinstance(features, dict) else {},
        tenant_id=tenant_id,
        entity_id=entity_id,
        timeout_s=timeout_s,
    )
    out = dict(features) if isinstance(features, dict) else {}
    out.update(resolved_signals)
    return out


def merge_features_with_resolved_from_packs(
    features: dict[str, Any],
    packs: Iterable[dict[str, Any]],
    *,
    tenant_id: str = "default",
    entity_id: str = "default",
    timeout_s: float = DEFAULT_SIGNAL_RESOLUTION_TIMEOUT_S,
    resolver: SignalResolver | None = None,
) -> dict[str, Any]:
    """Resolve all custom signals in ``packs`` once, merge ``resolved_signals`` into features for Rust."""
    specs = collect_custom_signal_specs_from_packs(packs)
    r = resolver or default_signal_resolver()
    resolved_signals = r.resolve_all(
        specs,
        features=features if isinstance(features, dict) else {},
        tenant_id=tenant_id,
        entity_id=entity_id,
        timeout_s=timeout_s,
    )
    out = dict(features) if isinstance(features, dict) else {}
    out.update(resolved_signals)
    return out
