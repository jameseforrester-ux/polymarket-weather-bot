from __future__ import annotations

import json
import logging
import re
from datetime import datetime, date
from typing import Any, Iterable, Optional

import httpx
from dateutil import parser as date_parser

from config import CITIES, CACHE_TTL_SECONDS
from data.cache import TTLCache
from models import MarketOutcome, WeatherMarket


log = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

HIGH_TEMP_PATTERNS = [
    re.compile(r"\b(high|highest|maximum|max)\b.*\b(temp|temperature|degrees?)\b", re.I),
    re.compile(r"\b(temp|temperature)\b.*\b(high|highest|maximum|max)\b", re.I),
    re.compile(r"\breach(?:es)?\s+\d{2,3}\s*(?:°|degrees?)", re.I),
]
BUCKET_PATTERNS = [
    re.compile(r"(?P<low>\d{2,3})\s*(?:-|to|–)\s*(?P<high>\d{2,3})\s*(?:°|degrees?|f)?", re.I),
    re.compile(r"between\s+(?P<low>\d{2,3})\s+and\s+(?P<high>\d{2,3})", re.I),
]
THRESHOLD_PATTERN = re.compile(r"(?:above|over|at least|reach(?:es)?)\s+(?P<threshold>\d{2,3})\s*(?:°|degrees?|f)?", re.I)


class PolymarketClient:
    def __init__(self, http: httpx.AsyncClient, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.http = http
        self.cache = TTLCache(ttl_seconds)

    async def discover_weather_markets(self, force: bool = False) -> list[WeatherMarket]:
        cache_key = "polymarket:weather_markets"
        if not force:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        params = {
            "tag": "weather",
            "active": "true",
            "closed": "false",
            "limit": "500",
        }
        response = await self.http.get(f"{GAMMA_BASE}/markets", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("markets", payload.get("data", []))

        markets = [m for m in (self._parse_market(row) for row in rows) if m is not None]
        await self.refresh_prices(markets)
        self.cache.set(cache_key, markets)
        return markets

    async def refresh_prices(self, markets: Iterable[WeatherMarket]) -> None:
        token_ids = [
            outcome.token_id
            for market in markets
            for outcome in market.outcomes
            if outcome.token_id
        ]
        if not token_ids:
            return

        body = [{"token_id": token_id, "side": "BUY"} for token_id in token_ids[:500]]
        try:
            response = await self.http.post(f"{CLOB_BASE}/prices", json=body, timeout=20)
            response.raise_for_status()
            prices = response.json()
        except Exception as exc:
            log.warning("CLOB prices request failed: %s", exc)
            prices = {}

        for market in markets:
            for outcome in market.outcomes:
                if not outcome.token_id:
                    continue
                price_obj = prices.get(outcome.token_id) or prices.get(str(outcome.token_id)) or {}
                value = price_obj.get("BUY") if isinstance(price_obj, dict) else None
                try:
                    outcome.price = float(value) if value is not None else outcome.price
                except (TypeError, ValueError):
                    pass

    async def get_orderbook_top(self, token_id: str) -> tuple[Optional[float], Optional[float]]:
        try:
            response = await self.http.get(f"{CLOB_BASE}/book", params={"token_id": token_id}, timeout=20)
            response.raise_for_status()
            payload = response.json()
            bids = payload.get("bids") or []
            asks = payload.get("asks") or []
            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None
            return best_bid, best_ask
        except Exception as exc:
            log.warning("Orderbook request failed for %s: %s", token_id, exc)
            return None, None

    def _parse_market(self, row: dict[str, Any]) -> Optional[WeatherMarket]:
        question = str(row.get("question") or row.get("title") or "")
        if not question or not any(pattern.search(question) for pattern in HIGH_TEMP_PATTERNS):
            return None

        city = self._extract_city(question, row)
        target_date = self._extract_date(question, row)
        bucket_low, bucket_high = self._extract_bucket(question)
        threshold = self._extract_threshold(question)
        outcomes = self._extract_outcomes(row)

        market = WeatherMarket(
            market_id=str(row.get("id") or row.get("marketId") or row.get("conditionId") or ""),
            condition_id=row.get("conditionId"),
            question=question,
            slug=row.get("slug"),
            city=city,
            target_date=target_date,
            bucket_low_f=bucket_low,
            bucket_high_f=bucket_high,
            threshold_f=threshold,
            outcomes=outcomes,
            end_time=self._parse_datetime(row.get("endDate") or row.get("end_date") or row.get("endTime")),
            raw=row,
        )
        return market

    def _extract_city(self, question: str, row: dict[str, Any]) -> Optional[str]:
        haystack = " ".join(
            str(x or "")
            for x in [question, row.get("slug"), row.get("description"), row.get("eventSlug")]
        ).lower()
        for city in CITIES.values():
            if any(keyword in haystack for keyword in city.polymarket_keywords):
                return city.name
        return None

    def _extract_date(self, question: str, row: dict[str, Any]) -> Optional[date]:
        for key in ("endDate", "end_date", "startDate", "start_date"):
            parsed = self._parse_datetime(row.get(key))
            if parsed:
                return parsed.date()
        match = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s+\d{4})?", question, re.I)
        if match:
            try:
                return date_parser.parse(match.group(0), fuzzy=True).date()
            except Exception:
                return None
        return None

    def _extract_bucket(self, question: str) -> tuple[Optional[float], Optional[float]]:
        for pattern in BUCKET_PATTERNS:
            match = pattern.search(question)
            if match:
                low = float(match.group("low"))
                high = float(match.group("high"))
                if high > low:
                    return low, high
        return None, None

    def _extract_threshold(self, question: str) -> Optional[float]:
        match = THRESHOLD_PATTERN.search(question)
        if not match:
            return None
        return float(match.group("threshold"))

    def _extract_outcomes(self, row: dict[str, Any]) -> list[MarketOutcome]:
        outcomes_raw = self._loads(row.get("outcomes"), [])
        prices_raw = self._loads(row.get("outcomePrices"), [])
        token_ids_raw = self._loads(row.get("clobTokenIds"), [])

        outcomes: list[MarketOutcome] = []
        for idx, label in enumerate(outcomes_raw or []):
            price = None
            if idx < len(prices_raw):
                try:
                    price = float(prices_raw[idx])
                except (TypeError, ValueError):
                    price = None
            token_id = str(token_ids_raw[idx]) if idx < len(token_ids_raw) else None
            outcomes.append(MarketOutcome(label=str(label), token_id=token_id, price=price))
        return outcomes

    def _loads(self, value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return date_parser.parse(str(value))
        except Exception:
            return None
