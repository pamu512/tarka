"""Zero-downtime ONNX hot reload for signal-api.

Uses a watchdog background thread to observe the model registry directory. When an
``.onnx`` file changes, the new graph is loaded **off** the swap lock; only the
pointer publish takes the lock so in-flight ``InferenceSession.run`` calls are not
blocked by disk I/O or session construction.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("signal_api.onnx_hot_reload")

_DEFAULT_DEBOUNCE_SEC = 0.75

_debounce_lock = threading.Lock()
_pending_timer: threading.Timer | None = None
_observer_lock = threading.Lock()
_observer: object | None = None


def _env_truthy(key: str) -> bool:
    v = (os.environ.get(key) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _debounce_seconds() -> float:
    raw = (os.environ.get("SIGNAL_ML_ONNX_HOT_RELOAD_DEBOUNCE_SEC") or "").strip()
    if not raw:
        return _DEFAULT_DEBOUNCE_SEC
    try:
        sec = float(raw)
    except ValueError:
        return _DEFAULT_DEBOUNCE_SEC
    return max(0.05, sec)


def _resolve_watch_root() -> Path | None:
    explicit = (os.environ.get("SIGNAL_ML_ONNX_WATCH_DIR") or "").strip()
    onnx_p = (os.environ.get("ONNX_MODEL_PATH") or "").strip()
    models_dir = (os.environ.get("MODELS_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if onnx_p:
        return Path(onnx_p).expanduser().resolve().parent
    if models_dir:
        return Path(models_dir).expanduser().resolve()
    return None


def _active_onnx_model_path() -> str:
    return (os.environ.get("ONNX_MODEL_PATH") or "").strip()


def _should_handle_path(event_path: str, watch_root: Path) -> bool:
    if not event_path or not event_path.lower().endswith(".onnx"):
        return False
    try:
        candidate = Path(event_path).expanduser().resolve()
    except OSError as exc:
        log.debug("signal_onnx_hot_reload_path_resolve_skip path=%s err=%s", event_path, exc)
        return False
    try:
        candidate.relative_to(watch_root)
    except ValueError:
        log.debug(
            "signal_onnx_hot_reload_path_outside_watch candidate=%s watch_root=%s",
            candidate,
            watch_root,
        )
        return False
    return True


def _execute_hot_reload(watch_root: Path) -> None:
    t_perf = time.perf_counter()
    log.info(
        "signal_onnx_hot_reload_cycle_begin watch_root=%s onnx_model_path=%s thread=%s",
        watch_root,
        _active_onnx_model_path() or "(unset)",
        threading.current_thread().name,
    )
    try:
        import ml_scoring.main as ml_main

        target = _active_onnx_model_path()
        if not target:
            log.warning("signal_onnx_hot_reload_aborted reason=onnx_model_path_unset")
            return
        t_path = Path(target).expanduser()
        try:
            resolved = str(t_path.resolve())
        except OSError as exc:
            log.error(
                "signal_onnx_hot_reload_aborted reason=model_path_resolve_failed path=%s err=%s",
                target,
                exc,
            )
            return
        if not t_path.is_file():
            log.error("signal_onnx_hot_reload_aborted reason=model_file_missing path=%s", resolved)
            return
        try:
            st = t_path.stat()
            meta = f"size_bytes={st.st_size} mtime_ns={getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9))}"
        except OSError as exc:
            meta = f"stat_failed err={exc}"
        log.info("signal_onnx_hot_reload_load_stage_begin path=%s %s", resolved, meta)

        t_load = time.perf_counter()
        new_handle = ml_main.load_onnx_inference_handle(resolved)
        load_ms = (time.perf_counter() - t_load) * 1000
        if new_handle.session is None:
            log.error(
                "signal_onnx_hot_reload_load_failed load_ms=%.2f path=%s",
                load_ms,
                resolved,
            )
            return
        log.info(
            "signal_onnx_hot_reload_load_stage_ok load_ms=%.2f input_name=%r source_path=%s",
            load_ms,
            new_handle.input_name,
            new_handle.source_path,
        )

        t_swap = time.perf_counter()
        prev = ml_main.swap_onnx_inference_handle(new_handle)
        swap_ms = (time.perf_counter() - t_swap) * 1000
        prev_sid = id(prev.session) if prev.session is not None else None
        new_sid = id(new_handle.session) if new_handle.session is not None else None
        total_ms = (time.perf_counter() - t_perf) * 1000
        log.info(
            "signal_onnx_hot_reload_swap_complete swap_ms=%.5f total_ms=%.2f "
            "active_session_id=%s retired_session_id=%s active_path=%s retired_path=%s "
            "(in-flight requests may still reference the retired session until their run finishes)",
            swap_ms,
            total_ms,
            new_sid,
            prev_sid,
            new_handle.source_path,
            prev.source_path,
        )
    except Exception:
        log.exception(
            "signal_onnx_hot_reload_cycle_failed watch_root=%s elapsed_ms=%.2f",
            watch_root,
            (time.perf_counter() - t_perf) * 1000,
        )


def _debounced_fire(watch_root: Path) -> None:
    global _pending_timer
    with _debounce_lock:
        _pending_timer = None
    _execute_hot_reload(watch_root)


def _schedule_debounced_reload(watch_root: Path) -> None:
    global _pending_timer
    delay = _debounce_seconds()
    with _debounce_lock:
        if _pending_timer is not None:
            _pending_timer.cancel()
            _pending_timer = None
        _pending_timer = threading.Timer(delay, _debounced_fire, args=(watch_root,))
        _pending_timer.daemon = True
        _pending_timer.start()
        log.info(
            "signal_onnx_hot_reload_debounce_scheduled delay_sec=%.3f watch_root=%s",
            delay,
            watch_root,
        )


def start_onnx_hot_reload_observer() -> Callable[[], None]:
    """Start watchdog observer thread if enabled by env. Returns ``stop`` callable."""
    global _observer  # noqa: PLW0603 — single process-wide observer

    if not _env_truthy("SIGNAL_ML_ONNX_HOT_RELOAD"):
        log.info(
            "signal_onnx_hot_reload_observer_not_started reason=disabled "
            "hint=set_SIGNAL_ML_ONNX_HOT_RELOAD_to_1",
        )
        return lambda: None

    if _env_truthy("DISABLE_ML"):
        log.info("signal_onnx_hot_reload_observer_not_started reason=disable_ml")
        return lambda: None

    watch_root = _resolve_watch_root()
    if watch_root is None:
        log.warning(
            "signal_onnx_hot_reload_observer_not_started reason=watch_root_unresolved "
            "hint=set_SIGNAL_ML_ONNX_WATCH_DIR_or_ONNX_MODEL_PATH_or_MODELS_DIR",
        )
        return lambda: None
    if not watch_root.is_dir():
        log.error(
            "signal_onnx_hot_reload_observer_not_started reason=watch_dir_missing path=%s",
            watch_root,
        )
        return lambda: None

    if not _active_onnx_model_path():
        log.warning(
            "signal_onnx_hot_reload_observer_not_started reason=onnx_model_path_unset "
            "hint=ONNX_MODEL_PATH",
        )
        return lambda: None

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        log.exception(
            "signal_onnx_hot_reload_observer_not_started reason=watchdog_missing "
            "hint=pip_install_watchdog",
        )
        return lambda: None

    class _OnnxRegistryHandler(FileSystemEventHandler):
        def __init__(self, root: Path) -> None:
            super().__init__()
            self._root = root

        def on_created(self, event):  # noqa: ANN001
            if event.is_directory:
                return
            if _should_handle_path(event.src_path, self._root):
                log.info("signal_onnx_hot_reload_fs_event kind=created path=%s", event.src_path)
                _schedule_debounced_reload(self._root)

        def on_modified(self, event):  # noqa: ANN001
            if event.is_directory:
                return
            if _should_handle_path(event.src_path, self._root):
                log.info("signal_onnx_hot_reload_fs_event kind=modified path=%s", event.src_path)
                _schedule_debounced_reload(self._root)

        def on_moved(self, event):  # noqa: ANN001
            if getattr(event, "is_directory", False):
                return
            dest = getattr(event, "dest_path", "") or ""
            if _should_handle_path(dest, self._root):
                log.info(
                    "signal_onnx_hot_reload_fs_event kind=moved dest=%s src=%s",
                    dest,
                    getattr(event, "src_path", ""),
                )
                _schedule_debounced_reload(self._root)

    observer = Observer()
    handler = _OnnxRegistryHandler(watch_root)
    observer.schedule(handler, str(watch_root), recursive=True)
    observer.start()
    log.info(
        "signal_onnx_hot_reload_observer_started watch_root=%s debounce_sec=%.3f recursive=True "
        "onnx_model_path=%s",
        watch_root,
        _debounce_seconds(),
        _active_onnx_model_path(),
    )
    with _observer_lock:
        _observer = observer

    def stop() -> None:
        global _observer, _pending_timer
        with _debounce_lock:
            if _pending_timer is not None:
                _pending_timer.cancel()
                _pending_timer = None
        with _observer_lock:
            obs = _observer
            _observer = None
        if obs is not None:
            log.info("signal_onnx_hot_reload_observer_stop_begin")
            obs.stop()
            obs.join(timeout=20)
            log.info("signal_onnx_hot_reload_observer_stop_done")

    return stop
