"""Configurable policy engine facade over the native ``tarka._tarka`` evaluator."""

from __future__ import annotations

from typing import Any, Optional

from tarka.decision import TarkaDecision, evaluate as _evaluate_impl


class TarkaEngine:
    """
    High-level engine handle with default ``fast_path`` and ``engine_version`` for :meth:`evaluate`.

    The underlying evaluation path, key loading, and evidence sealing behavior are unchanged
    from module-level :func:`tarka.decision.evaluate`.
    """

    __slots__ = ("_engine_version_default", "_fast_path_default")

    def __init__(
        self,
        *,
        fast_path: bool = True,
        engine_version: str = "tarka-core",
    ) -> None:
        self._fast_path_default = fast_path
        self._engine_version_default = engine_version

    def evaluate(
        self,
        rule_json: str,
        data_json: str,
        rule_content_id_hex: str,
        *,
        fast_path: Optional[bool] = None,
        engine_version: Optional[str] = None,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        replay_wall_time_ns: Optional[int] = None,
        mock_redis: Any = None,
        mock_lists: Any = None,
        mock_custom: Any = None,
    ) -> TarkaDecision:
        """Run evaluation; per-call ``fast_path`` / ``engine_version`` override instance defaults."""
        return _evaluate_impl(
            rule_json,
            data_json,
            rule_content_id_hex,
            fast_path=self._fast_path_default if fast_path is None else fast_path,
            engine_version=(
                self._engine_version_default if engine_version is None else engine_version
            ),
            trace_id=trace_id,
            span_id=span_id,
            replay_wall_time_ns=replay_wall_time_ns,
            mock_redis=mock_redis,
            mock_lists=mock_lists,
            mock_custom=mock_custom,
        )
