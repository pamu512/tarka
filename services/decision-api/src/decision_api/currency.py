"""Multi-currency normalisation with exchange-rate caching.

Fetches live rates from a free API (exchangerate.host / frankfurter.app)
and falls back to static rates when the network call fails.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

log = logging.getLogger("decision-api.currency")

STATIC_RATES: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 149.50,
    "INR": 83.10,
    "BRL": 4.97,
    "AUD": 1.53,
    "CAD": 1.36,
    "CHF": 0.88,
    "CNY": 7.24,
}

RATE_API_URL = "https://api.frankfurter.app/latest?from=USD"
CACHE_TTL = 3600  # re-fetch at most once per hour


class ExchangeRateCache:
    """Thread-safe (single-event-loop) exchange rate cache."""

    def __init__(self) -> None:
        self._rates: dict[str, float] = dict(STATIC_RATES)
        self._last_fetch: float = 0.0
        self._fetching: bool = False

    @property
    def rates(self) -> dict[str, float]:
        return dict(self._rates)

    async def refresh(self, http: httpx.AsyncClient | None = None) -> bool:
        """Attempt to fetch live rates. Returns True on success."""
        if self._fetching:
            return False
        self._fetching = True
        try:
            client = http or httpx.AsyncClient(timeout=5.0)
            close_after = http is None
            try:
                resp = await client.get(RATE_API_URL)
                if resp.status_code == 200:
                    data: dict[str, Any] = resp.json()
                    fetched: dict[str, float] = data.get("rates", {})
                    if fetched:
                        new_rates = {"USD": 1.0}
                        for code, rate in fetched.items():
                            new_rates[code.upper()] = float(rate)
                        self._rates = new_rates
                        self._last_fetch = time.time()
                        log.info("refreshed exchange rates: %d currencies", len(new_rates))
                        return True
            finally:
                if close_after:
                    await client.aclose()
        except Exception as exc:
            log.warning("exchange rate fetch failed, using cached/static: %s", exc)
        finally:
            self._fetching = False
        return False

    async def ensure_fresh(self, http: httpx.AsyncClient | None = None) -> None:
        if time.time() - self._last_fetch > CACHE_TTL:
            await self.refresh(http)

    def get_rate(self, currency: str) -> float | None:
        """Return the rate for *currency* relative to USD, or None if unknown."""
        return self._rates.get(currency.upper())


_cache = ExchangeRateCache()


async def normalize_amount(
    amount: float,
    currency: str,
    target: str = "USD",
    http: httpx.AsyncClient | None = None,
) -> float:
    """Convert *amount* from *currency* to *target* (default USD).

    Falls back to static rates if live rates are unavailable.
    """
    currency = currency.upper()
    target = target.upper()
    if currency == target:
        return amount

    await _cache.ensure_fresh(http)

    src_rate = _cache.get_rate(currency)
    tgt_rate = _cache.get_rate(target)

    if src_rate is None or tgt_rate is None:
        log.warning("unknown currency pair %s→%s, returning original amount", currency, target)
        return amount

    usd_amount = amount / src_rate
    return round(usd_amount * tgt_rate, 4)


def get_cache() -> ExchangeRateCache:
    return _cache
