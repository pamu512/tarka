"""Macro seasonal baseline synthesizer for the local trend-engine RAG plane.

Reads multi-scale rollups from ClickHouse (``daily_entity_rollups`` / merged view),
sub-minute tactical metrics, and HIL override rows, then emits a structured context matrix
for downstream LLM scoring.

Prerequisites (see ``migrations/20260603_002_macro_seasonal_baselines.sql``):
  • ``tarka_analytics.v_daily_entity_rollups_merged``
  • ``tarka_analytics.hil_context_overrides``
  • ``tarka_analytics.sub_minute_metrics`` (tactical plane; see ``SUB_MINUTE_TABLE``)
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

CASCADE_WINDOW_DAYS: Final[tuple[int, ...]] = (1, 3, 7, 15, 30, 45, 60, 90)
SEASONAL_LOOKBACK_YEARS: Final[int] = 3
DEFAULT_MIN_SIGMA: Final[float] = 1.0
SUB_MINUTE_TABLE: Final[str] = "tarka_analytics.sub_minute_metrics"
DAILY_ROLLUPS_TABLE: Final[str] = "tarka_analytics.daily_entity_rollups"
DAILY_ROLLUPS_VIEW: Final[str] = "tarka_analytics.v_daily_entity_rollups_merged"
HIL_OVERRIDES_TABLE: Final[str] = "tarka_analytics.hil_context_overrides"
DAILY_LOOKBACK_DAYS: Final[int] = max(CASCADE_WINDOW_DAYS) + (SEASONAL_LOOKBACK_YEARS * 366) + 7
Z_SCORE_BASELINE_WINDOW_DAYS: Final[int] = 90
OBSERVATION_WINDOW_HOURS: Final[int] = 24

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MacroSynthesizerError(RuntimeError):
    """Base error for macro synthesis failures."""


class ClickHouseConnectionExhaustedError(MacroSynthesizerError):
    """Raised when ClickHouse refuses connections (pool / server limit)."""


class ClickHouseQueryError(MacroSynthesizerError):
    """Raised when a ClickHouse query fails after retries."""


class MacroSynthesizerConfig(BaseSettings):
    """Connection and retry policy for :class:`MacroSynthesizer`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    clickhouse_host: str = Field(
        default="",
        validation_alias="CLICKHOUSE_HOST",
    )
    clickhouse_url: str = Field(
        default="",
        validation_alias="CLICKHOUSE_URL",
    )
    clickhouse_port: int = Field(default=8123, validation_alias="CLICKHOUSE_PORT")
    clickhouse_user: str = Field(default="default", validation_alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", validation_alias="CLICKHOUSE_PASSWORD")
    clickhouse_database: str = Field(
        default="tarka_analytics",
        validation_alias="CLICKHOUSE_DATABASE",
    )
    clickhouse_secure: bool = Field(default=False, validation_alias="CLICKHOUSE_SECURE")
    statement_timeout_ms: int = Field(
        default=30_000,
        validation_alias="CLICKHOUSE_STATEMENT_TIMEOUT_MS",
    )
    connect_timeout_s: float = Field(default=10.0, validation_alias="CLICKHOUSE_CONNECT_TIMEOUT_S")
    max_query_retries: int = Field(default=3, validation_alias="MACRO_SYNTH_MAX_QUERY_RETRIES")
    retry_backoff_base_s: float = Field(
        default=0.25,
        validation_alias="MACRO_SYNTH_RETRY_BACKOFF_BASE_S",
    )


class HilOverrideType(str, Enum):
    ALLOW_SEASONAL_SPIKE = "ALLOW_SEASONAL_SPIKE"
    FORCE_BLOCK = "FORCE_BLOCK"
    TEMPORARY_BASELINE_SHIFT = "TEMPORARY_BASELINE_SHIFT"


class SubMinuteSnapshot(BaseModel):
    """One sub-minute bucket from ``sub_minute_metrics``."""

    model_config = ConfigDict(strict=True)

    bucket_start: datetime
    tx_count: int = Field(ge=0)
    failed_auth_count: int = Field(ge=0)
    tx_volume_usd: float = Field(ge=0.0)


class WindowStatistics(BaseModel):
    """Mean / std for transaction volume and failed-auth counts over a sliding window."""

    model_config = ConfigDict(strict=True)

    window_days: int = Field(ge=1)
    sample_days: int = Field(ge=0)
    tx_volume_mean: float
    tx_volume_std: float
    failed_auth_mean: float
    failed_auth_std: float
    total_tx_count: int = Field(ge=0)
    total_failed_auth: int = Field(ge=0)


class SeasonalYearSlice(BaseModel):
    """Aggregated metrics for one calendar year on the same DOY/DOW slice."""

    model_config = ConfigDict(strict=True)

    calendar_year: int
    sample_days: int = Field(ge=0)
    tx_volume_mean: float
    failed_auth_mean: float
    total_tx_count: int = Field(ge=0)


class SeasonalHistorical3Y(BaseModel):
    """Three-year cyclical baseline for the entity's current calendar position."""

    model_config = ConfigDict(strict=True)

    day_of_year: int = Field(ge=1, le=366)
    day_of_week: int = Field(ge=1, le=7)
    slices: list[SeasonalYearSlice]


class HilOverrideRecord(BaseModel):
    """Active analyst override row."""

    model_config = ConfigDict(strict=True)

    override_type: HilOverrideType
    scope_key: str
    expires_at: datetime
    analyst_rationale: str
    created_at: datetime | None = None


class ZScoreValidation(BaseModel):
    """Inline validator: 24h volume vs 90-day baseline."""

    model_config = ConfigDict(strict=True)

    metric: Literal["tx_volume_usd", "failed_auth_count"]
    observed_24h: float
    baseline_mu: float
    baseline_sigma: float
    sigma_used: float
    z_score: float


class RagContextMatrix(BaseModel):
    """RAG payload for the local trend engine."""

    model_config = ConfigDict(strict=True)

    tenant_id: str
    entity_id: str
    compiled_at: datetime
    tactical_snapshots: list[SubMinuteSnapshot]
    cascading_baselines: dict[str, WindowStatistics]
    seasonal_historical_3y: SeasonalHistorical3Y
    active_hil_overrides: list[HilOverrideRecord]
    active_hil_exclusions: list[HilOverrideRecord]
    z_score_validations: list[ZScoreValidation]


@dataclass(frozen=True, slots=True)
class _DailyRow:
    day: date
    day_of_week: int
    day_of_year: int
    region_code: str
    tx_count: int
    tx_volume_usd: float
    failed_auth_count: int


def _validate_identifier(value: str, *, context: str) -> str:
    token = (value or "").strip()
    if not token or not _IDENTIFIER_RE.match(token):
        raise ValueError(f"invalid ClickHouse identifier for {context}: {value!r}")
    return token


def _population_std(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(max(variance, 0.0))


def _population_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_z_score(
    observed: float,
    mu: float,
    sigma: float,
    *,
    min_sigma: float = DEFAULT_MIN_SIGMA,
) -> tuple[float, float]:
    """Return ``(z_score, sigma_used)`` with safe handling when σ≈0."""
    sigma_used = sigma if sigma > min_sigma else min_sigma
    if not math.isfinite(observed) or not math.isfinite(mu):
        raise ValueError("non-finite value in z-score inputs")
    return (observed - mu) / sigma_used, sigma_used


def _is_connection_exhausted(exc: BaseException) -> bool:
    message = str(exc).lower()
    needles = (
        "too many connections",
        "connection pool",
        "max connections",
        "connection refused",
        "cannot allocate",
        "resource temporarily unavailable",
    )
    return any(n in message for n in needles)


def _is_transient_clickhouse_error(exc: BaseException) -> bool:
    if _is_connection_exhausted(exc):
        return True
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "timeout",
            "timed out",
            "temporarily unavailable",
            "connection reset",
            "broken pipe",
            "socket",
        )
    )


def _parse_hil_override_type(raw: Any) -> HilOverrideType:
    text = str(raw or "").strip()
    if text.isdigit():
        mapping = {
            "1": HilOverrideType.ALLOW_SEASONAL_SPIKE,
            "2": HilOverrideType.FORCE_BLOCK,
            "3": HilOverrideType.TEMPORARY_BASELINE_SHIFT,
        }
        if text in mapping:
            return mapping[text]
    try:
        return HilOverrideType(text)
    except ValueError as exc:
        raise ClickHouseQueryError(f"unknown hil override_type: {raw!r}") from exc


def _scope_matches_calendar(scope_key: str, *, day_of_year: int, day_of_week: int, region_code: str) -> bool:
    key = scope_key.strip()
    if not key:
        return False
    if key == "global":
        return True
    if key == f"day_of_year:{day_of_year}":
        return True
    if key == f"day_of_week:{day_of_week}":
        return True
    region = (region_code or "").strip()
    if region and key == f"global_region:{region}":
        return True
    return False


def _window_statistics(rows: Sequence[_DailyRow], window_days: int, *, anchor: date) -> WindowStatistics:
    """Inclusive sliding window of ``window_days`` calendar days ending on ``anchor``."""
    cutoff = anchor - timedelta(days=window_days - 1)
    window_rows = [r for r in rows if cutoff <= r.day <= anchor]
    volumes = [float(r.tx_volume_usd) for r in window_rows]
    failures = [float(r.failed_auth_count) for r in window_rows]
    return WindowStatistics(
        window_days=window_days,
        sample_days=len(window_rows),
        tx_volume_mean=_population_mean(volumes),
        tx_volume_std=_population_std(volumes),
        failed_auth_mean=_population_mean(failures),
        failed_auth_std=_population_std(failures),
        total_tx_count=sum(r.tx_count for r in window_rows),
        total_failed_auth=sum(r.failed_auth_count for r in window_rows),
    )


def _seasonal_slices(rows: Sequence[_DailyRow], *, day_of_year: int, day_of_week: int, anchor: date) -> SeasonalHistorical3Y:
    earliest = anchor - timedelta(days=SEASONAL_LOOKBACK_YEARS * 366)
    matched = [
        r
        for r in rows
        if r.day >= earliest
        and r.day < anchor
        and r.day_of_year == day_of_year
        and r.day_of_week == day_of_week
    ]
    by_year: dict[int, list[_DailyRow]] = {}
    for row in matched:
        by_year.setdefault(row.day.year, []).append(row)

    slices: list[SeasonalYearSlice] = []
    for year in sorted(by_year):
        year_rows = by_year[year]
        volumes = [float(r.tx_volume_usd) for r in year_rows]
        failures = [float(r.failed_auth_count) for r in year_rows]
        slices.append(
            SeasonalYearSlice(
                calendar_year=year,
                sample_days=len(year_rows),
                tx_volume_mean=_population_mean(volumes),
                failed_auth_mean=_population_mean(failures),
                total_tx_count=sum(r.tx_count for r in year_rows),
            )
        )
    return SeasonalHistorical3Y(
        day_of_year=day_of_year,
        day_of_week=day_of_week,
        slices=slices,
    )


class MacroSynthesizer:
    """ClickHouse-backed worker that compiles multi-scale RAG context for one entity."""

    def __init__(
        self,
        *,
        config: MacroSynthesizerConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self._config = config or MacroSynthesizerConfig()
        self._client = client if client is not None else self._connect_from_config(self._config)

    @staticmethod
    def _connect_from_config(config: MacroSynthesizerConfig) -> Any:
        try:
            import clickhouse_connect
        except ImportError as exc:
            raise MacroSynthesizerError(
                "clickhouse-connect is required; install tarka-v2-analytics dependencies"
            ) from exc

        host = (config.clickhouse_host or "").strip()
        url = (config.clickhouse_url or "").strip()
        if not host and not url:
            raise MacroSynthesizerError(
                "ClickHouse is not configured (set CLICKHOUSE_HOST or CLICKHOUSE_URL)"
            )

        timeout_s = max(config.statement_timeout_ms / 1000.0, 0.001)
        try:
            if url:
                return clickhouse_connect.get_client(
                    dsn=url,
                    connect_timeout=config.connect_timeout_s,
                    send_receive_timeout=timeout_s,
                )
            return clickhouse_connect.get_client(
                host=host,
                port=int(config.clickhouse_port),
                username=config.clickhouse_user,
                password=config.clickhouse_password or "",
                database=config.clickhouse_database,
                secure=bool(config.clickhouse_secure),
                connect_timeout=config.connect_timeout_s,
                send_receive_timeout=timeout_s,
            )
        except Exception as exc:
            if _is_connection_exhausted(exc):
                raise ClickHouseConnectionExhaustedError(
                    "ClickHouse connection pool exhausted during client init"
                ) from exc
            raise MacroSynthesizerError(f"ClickHouse client init failed: {exc}") from exc

    def close(self) -> None:
        close_fn = getattr(self._client, "close", None)
        if callable(close_fn):
            close_fn()

    def _query(
        self,
        sql: str,
        parameters: Mapping[str, Any],
        *,
        operation: str,
    ) -> Any:
        last_exc: BaseException | None = None
        attempts = max(int(self._config.max_query_retries), 1)
        for attempt in range(attempts):
            try:
                return self._client.query(sql, parameters=dict(parameters))
            except Exception as exc:
                last_exc = exc
                if _is_connection_exhausted(exc):
                    raise ClickHouseConnectionExhaustedError(
                        f"ClickHouse connection exhausted during {operation}"
                    ) from exc
                if attempt + 1 >= attempts or not _is_transient_clickhouse_error(exc):
                    break
                sleep_s = self._config.retry_backoff_base_s * (2**attempt)
                logger.warning(
                    "macro_synthesizer_query_retry operation=%s attempt=%s sleep_s=%.3f error=%s",
                    operation,
                    attempt + 1,
                    sleep_s,
                    exc,
                )
                time.sleep(sleep_s)
        assert last_exc is not None
        raise ClickHouseQueryError(f"{operation} failed: {last_exc}") from last_exc

    def _fetch_daily_rollups(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        anchor: date,
    ) -> list[_DailyRow]:
        """Pull merged ``{DAILY_ROLLUPS_TABLE}`` rows for cascade + 3y seasonal planes."""
        sql = f"""
        SELECT
            date,
            any(day_of_week) AS day_of_week,
            any(day_of_year) AS day_of_year,
            any(region_code) AS region_code,
            sum(daily_tx_count) AS daily_tx_count,
            sum(daily_tx_volume_usd) AS daily_tx_volume_usd,
            sum(daily_failed_auth_count) AS daily_failed_auth_count
        FROM {DAILY_ROLLUPS_VIEW}
        WHERE tenant_id = {{tenant_id:String}}
          AND entity_id = {{entity_id:String}}
          AND date >= {{start_date:Date}}
          AND date <= {{anchor_date:Date}}
        GROUP BY date
        ORDER BY date
        """
        start_date = anchor - timedelta(days=DAILY_LOOKBACK_DAYS)
        result = self._query(
            sql,
            {
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "start_date": start_date,
                "anchor_date": anchor,
            },
            operation="fetch_daily_rollups",
        )
        rows: list[_DailyRow] = []
        for row in result.result_rows or ():
            day_val, dow, doy, region, tx_c, vol, fail_c = row
            if isinstance(day_val, datetime):
                day_parsed = day_val.date()
            elif isinstance(day_val, date):
                day_parsed = day_val
            else:
                day_parsed = date.fromisoformat(str(day_val))
            rows.append(
                _DailyRow(
                    day=day_parsed,
                    day_of_week=int(dow),
                    day_of_year=int(doy),
                    region_code=str(region or "").strip(),
                    tx_count=int(tx_c or 0),
                    tx_volume_usd=float(vol or 0.0),
                    failed_auth_count=int(fail_c or 0),
                )
            )
        return rows

    def _fetch_sub_minute_snapshots(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        anchor_dt: datetime,
    ) -> list[SubMinuteSnapshot]:
        sql = f"""
        SELECT
            bucket_start,
            tx_count,
            failed_auth_count,
            tx_volume_usd
        FROM {SUB_MINUTE_TABLE}
        WHERE tenant_id = {{tenant_id:String}}
          AND entity_id = {{entity_id:String}}
          AND bucket_start > {{since:DateTime}}
          AND bucket_start <= {{until:DateTime}}
        ORDER BY bucket_start
        """
        since = anchor_dt - timedelta(hours=OBSERVATION_WINDOW_HOURS)
        result = self._query(
            sql,
            {
                "tenant_id": tenant_id,
                "entity_id": entity_id,
                "since": since.replace(tzinfo=None),
                "until": anchor_dt.replace(tzinfo=None),
            },
            operation="fetch_sub_minute_metrics",
        )
        snapshots: list[SubMinuteSnapshot] = []
        for row in result.result_rows or ():
            bucket_start, tx_count, failed_auth, volume = row
            if isinstance(bucket_start, datetime):
                bucket_dt = bucket_start.replace(tzinfo=UTC) if bucket_start.tzinfo is None else bucket_start.astimezone(UTC)
            else:
                bucket_dt = datetime.fromisoformat(str(bucket_start)).replace(tzinfo=UTC)
            snapshots.append(
                SubMinuteSnapshot(
                    bucket_start=bucket_dt,
                    tx_count=int(tx_count or 0),
                    failed_auth_count=int(failed_auth or 0),
                    tx_volume_usd=float(volume or 0.0),
                )
            )
        return snapshots

    def _fetch_hil_overrides(self, tenant_id: str, entity_id: str) -> list[HilOverrideRecord]:
        sql = f"""
        SELECT
            override_type,
            scope_key,
            expires_at,
            created_at,
            analyst_rationale
        FROM {HIL_OVERRIDES_TABLE} FINAL
        WHERE tenant_id = {{tenant_id:String}}
          AND entity_id = {{entity_id:String}}
          AND expires_at > now()
        ORDER BY created_at DESC
        """
        result = self._query(
            sql,
            {"tenant_id": tenant_id, "entity_id": entity_id},
            operation="fetch_hil_overrides",
        )
        records: list[HilOverrideRecord] = []
        for row in result.result_rows or ():
            override_raw, scope_key, expires_at, created_at, rationale = row
            if isinstance(expires_at, datetime):
                expires_dt = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)
            else:
                expires_dt = datetime.fromisoformat(str(expires_at)).replace(tzinfo=UTC)
            created_dt: datetime | None = None
            if created_at is not None:
                if isinstance(created_at, datetime):
                    created_dt = (
                        created_at.replace(tzinfo=UTC)
                        if created_at.tzinfo is None
                        else created_at.astimezone(UTC)
                    )
                else:
                    created_dt = datetime.fromisoformat(str(created_at)).replace(tzinfo=UTC)
            records.append(
                HilOverrideRecord(
                    override_type=_parse_hil_override_type(override_raw),
                    scope_key=str(scope_key or ""),
                    expires_at=expires_dt,
                    analyst_rationale=str(rationale or ""),
                    created_at=created_dt,
                )
            )
        return records

    @staticmethod
    def _observed_24h_metrics(
        *,
        daily_rows: Sequence[_DailyRow],
        tactical: Sequence[SubMinuteSnapshot],
        anchor: date,
        anchor_dt: datetime,
    ) -> tuple[float, float]:
        """Sum tactical buckets in the last 24h; fall back to merged daily rows."""
        since_day = (anchor_dt - timedelta(hours=OBSERVATION_WINDOW_HOURS)).date()
        daily_24h = [
            r
            for r in daily_rows
            if since_day <= r.day <= anchor
        ]
        observed_volume = sum(s.tx_volume_usd for s in tactical)
        observed_failures = float(sum(s.failed_auth_count for s in tactical))
        if observed_volume <= 0.0 and daily_24h:
            observed_volume = float(sum(r.tx_volume_usd for r in daily_24h))
        if observed_failures <= 0.0 and daily_24h:
            observed_failures = float(sum(r.failed_auth_count for r in daily_24h))
        return observed_volume, observed_failures

    def _build_z_score_validations(
        self,
        *,
        daily_rows: Sequence[_DailyRow],
        tactical: Sequence[SubMinuteSnapshot],
        anchor: date,
        anchor_dt: datetime,
    ) -> list[ZScoreValidation]:
        baseline_90 = _window_statistics(
            daily_rows, Z_SCORE_BASELINE_WINDOW_DAYS, anchor=anchor
        )
        observed_volume, observed_failures = self._observed_24h_metrics(
            daily_rows=daily_rows,
            tactical=tactical,
            anchor=anchor,
            anchor_dt=anchor_dt,
        )

        validations: list[ZScoreValidation] = []
        z_vol, sigma_vol = compute_z_score(
            float(observed_volume),
            baseline_90.tx_volume_mean,
            baseline_90.tx_volume_std,
        )
        validations.append(
            ZScoreValidation(
                metric="tx_volume_usd",
                observed_24h=float(observed_volume),
                baseline_mu=baseline_90.tx_volume_mean,
                baseline_sigma=baseline_90.tx_volume_std,
                sigma_used=sigma_vol,
                z_score=z_vol,
            )
        )
        z_fail, sigma_fail = compute_z_score(
            float(observed_failures),
            baseline_90.failed_auth_mean,
            baseline_90.failed_auth_std,
        )
        validations.append(
            ZScoreValidation(
                metric="failed_auth_count",
                observed_24h=float(observed_failures),
                baseline_mu=baseline_90.failed_auth_mean,
                baseline_sigma=baseline_90.failed_auth_std,
                sigma_used=sigma_fail,
                z_score=z_fail,
            )
        )
        return validations

    def insert_hil_override(
        self,
        tenant_id: str,
        entity_id: str,
        override_type: HilOverrideType | str,
        *,
        scope_key: str,
        expires_at: datetime,
        analyst_rationale: str,
    ) -> None:
        """Append an analyst feedback row to ``hil_context_overrides``."""
        if isinstance(override_type, HilOverrideType):
            otype = override_type.value
        else:
            otype = str(override_type).strip()
        sql = f"""
        INSERT INTO {HIL_OVERRIDES_TABLE} (
            tenant_id, entity_id, override_type, scope_key, expires_at, analyst_rationale
        ) VALUES (
            {{tenant_id:String}}, {{entity_id:String}}, {{override_type:String}},
            {{scope_key:String}}, {{expires_at:DateTime}}, {{analyst_rationale:String}}
        )
        """
        expires_naive = (
            expires_at.replace(tzinfo=None)
            if expires_at.tzinfo is not None
            else expires_at
        )
        self._query(
            sql,
            {
                "tenant_id": tenant_id.strip(),
                "entity_id": entity_id.strip(),
                "override_type": otype,
                "scope_key": scope_key.strip(),
                "expires_at": expires_naive,
                "analyst_rationale": analyst_rationale.strip(),
            },
            operation="insert_hil_override",
        )

    def compile_rag_matrix(
        self,
        tenant_id: str,
        entity_id: str,
        *,
        anchor: datetime | None = None,
        region_code: str = "",
    ) -> dict[str, Any]:
        """Aggregate multi-scale baselines and return a JSON-serializable RAG matrix."""
        tenant = (tenant_id or "").strip()
        entity = (entity_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id must be non-empty")
        if not entity:
            raise ValueError("entity_id must be non-empty")

        anchor_dt = anchor.astimezone(UTC) if anchor is not None else datetime.now(tz=UTC)
        anchor_day = anchor_dt.date()
        day_of_week = int(anchor_dt.isoweekday())
        day_of_year = int(anchor_dt.timetuple().tm_yday)

        daily_rows = self._fetch_daily_rollups(tenant, entity, anchor=anchor_day)
        tactical = self._fetch_sub_minute_snapshots(tenant, entity, anchor_dt=anchor_dt)
        hil_all = self._fetch_hil_overrides(tenant, entity)

        resolved_region = (region_code or "").strip()
        if not resolved_region and daily_rows:
            resolved_region = daily_rows[-1].region_code

        cascading: dict[str, WindowStatistics] = {}
        for window in CASCADE_WINDOW_DAYS:
            cascading[f"{window}d"] = _window_statistics(daily_rows, window, anchor=anchor_day)

        seasonal = _seasonal_slices(
            daily_rows,
            day_of_year=day_of_year,
            day_of_week=day_of_week,
            anchor=anchor_day,
        )

        active_hil: list[HilOverrideRecord] = list(hil_all)
        hil_exclusions: list[HilOverrideRecord] = []
        for record in hil_all:
            if record.override_type != HilOverrideType.ALLOW_SEASONAL_SPIKE:
                continue
            if _scope_matches_calendar(
                record.scope_key,
                day_of_year=day_of_year,
                day_of_week=day_of_week,
                region_code=resolved_region,
            ):
                hil_exclusions.append(record)

        z_validations = self._build_z_score_validations(
            daily_rows=daily_rows,
            tactical=tactical,
            anchor=anchor_day,
            anchor_dt=anchor_dt,
        )

        matrix = RagContextMatrix(
            tenant_id=tenant,
            entity_id=entity,
            compiled_at=anchor_dt,
            tactical_snapshots=tactical,
            cascading_baselines=cascading,
            seasonal_historical_3y=seasonal,
            active_hil_overrides=active_hil,
            active_hil_exclusions=hil_exclusions,
            z_score_validations=z_validations,
        )
        return matrix.model_dump(mode="json")
