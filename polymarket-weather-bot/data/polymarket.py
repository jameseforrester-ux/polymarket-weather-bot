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
    re.compile(r"\bwhat\s+will\s+the\s+high\s+be\b", re.I),
    re.compile(r"\bwill\s+the\s+highest\s+temperature\b", re.I),
    re.compile(r"\bdaily\s+high\b", re.I),
    re.compile(r"\breach(?:es)?\s+\d{2,3}\s*(?:°|degrees?)", re.I),
]
BUCKET_PATTERNS = [
    re.compile(r"(?P<low>\d{1,3})\s*(?:-|to|–)\s*(?P<high>\d{1,3})\s*(?:°|degrees?|[fc])?", re.I),
    re.compile(r"between\s+(?P<low>\d{2,3})\s+and\s+(?P<high>\d{2,3})", re.I),
]
THRESHOLD_PATTERN = re.compile(r"(?:above|over|at least|reach(?:es)?|be)\s+(?P<threshold>\d{1,3})\s*(?:°|degrees?|[fc])?", re.I)


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

        rows = await self._collect_market_candidates()
        unique_rows = self._dedupe_rows(rows)
        markets = [m for m in (self._parse_market(row) for row in unique_rows) if m is not None]
        log.info(
            "Polymarket discovery: raw=%s deduped=%s matched_high_temp=%s",
            len(rows),
            len(unique_rows),
            len(markets),
        )
        await self.refresh_prices(markets)
        self.cache.set(cache_key, markets)
        return markets

    async def _collect_market_candidates(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []

        weather_tag_ids = await self._weather_tag_ids()
        log.info("Resolved Polymarket weather tag ids: %s", weather_tag_ids)
        for tag_id in weather_tag_ids:
            rows.extend(await self._markets_from_events({"tag_id": tag_id, "related_tags": "true"}))

        for query in ("highest temperature", "high temperature", "temperature", "weather"):
            rows.extend(await self._markets_from_public_search(query))

        # Last-resort fallback: page through active markets because Gamma silently ignores
        # unsupported parameters like tag=weather.
        for offset in range(0, 1000, 100):
            try:
                payload = await self._get_json(
                    f"{GAMMA_BASE}/markets",
                    {"active": "true", "closed": "false", "limit": "100", "offset": str(offset)},
                )
                page = self._as_rows(payload)
                if not page:
                    break
                rows.extend([row for row in page if self._has_weather_hint(row)])
            except Exception as exc:
                log.warning("Broad Gamma market fallback failed at offset %s: %s", offset, exc)
                break
        return rows

    async def _weather_tag_ids(self) -> list[str]:
        # Weather has historically been tag id 84 on Gamma. Keep discovery too,
        # because tag ids are not guaranteed to remain stable.
        tag_ids: list[str] = ["84"]
        for offset in range(0, 1000, 100):
            try:
                payload = await self._get_json(f"{GAMMA_BASE}/tags", {"limit": "100", "offset": str(offset)})
            except Exception as exc:
                log.warning("Tag lookup failed: %s", exc)
                break
            tags = self._as_rows(payload)
            if not tags:
                break
            for tag in tags:
                label = str(tag.get("label") or "").lower()
                slug = str(tag.get("slug") or "").lower()
                if slug in {"weather", "daily-temperature", "highest-temperature"} or label in {"weather", "daily temperature", "highest temperature"}:
                    tag_ids.append(str(tag.get("id")))
        return list(dict.fromkeys(tag_ids))

    async def _markets_from_events(self, extra_params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for offset in range(0, 500, 100):
            params = {"active": "true", "closed": "false", "limit": "100", "offset": str(offset), **extra_params}
            try:
                payload = await self._get_json(f"{GAMMA_BASE}/events", params)
            except Exception as exc:
                log.warning("Gamma events request failed: %s", exc)
                break
            events = self._as_rows(payload)
            if not events:
                break
            for event in events:
                rows.extend(self._flatten_event_markets(event))
        return rows

    async def _markets_from_public_search(self, query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, 4):
            params = {
                "q": query,
                "limit_per_type": "50",
                "page": str(page),
                "events_status": "active",
                "keep_closed_markets": "0",
                "search_profiles": "false",
            }
            try:
                payload = await self._get_json(f"{GAMMA_BASE}/public-search", params)
            except Exception as exc:
                log.warning("Gamma public-search failed for %s: %s", query, exc)
                break
            for event in payload.get("events", []) if isinstance(payload, dict) else []:
                rows.extend(self._flatten_event_markets(event))
            for market in payload.get("markets", []) if isinstance(payload, dict) else []:
                rows.append(market)
        return rows

    def _flatten_event_markets(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        markets = event.get("markets") or []
        flattened = []
        for market in markets:
            row = {**market}
            row.setdefault("eventTitle", event.get("title"))
            row.setdefault("eventSlug", event.get("slug"))
            row.setdefault("eventDate", event.get("eventDate") or event.get("startTime") or event.get("endDate"))
            row.setdefault("tags", event.get("tags"))
            flattened.append(row)
        return flattened

    def _dedupe_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get("conditionId") or row.get("id") or row.get("slug") or row.get("question"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    async def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        response = await self.http.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def _as_rows(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("markets", "events", "data"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    def _has_weather_hint(self, row: dict[str, Any]) -> bool:
        haystack = self._market_text(row)
        return "temperature" in haystack or "weather" in haystack or "daily high" in haystack

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
        question = str(row.get("question") or row.get("title") or row.get("eventTitle") or "")
        text = self._market_text(row)
        if not question or not any(pattern.search(text) for pattern in HIGH_TEMP_PATTERNS):
            return None

        city = self._extract_city(question, row)
        target_date = self._extract_date(question, row)
        bucket_low, bucket_high = self._extract_bucket(text)
        threshold = self._extract_threshold(text)
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
        haystack = self._market_text(row)
        match = re.search(r"(?:highest|high|max(?:imum)?)\s+temperature\s+in\s+(.+?)\s+(?:be|on)\b", haystack, re.I)
        if match:
            return match.group(1).strip().title()
        for city in CITIES.values():
            for keyword in city.polymarket_keywords:
                if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", haystack):
                    return city.name
        return None

    def _extract_date(self, question: str, row: dict[str, Any]) -> Optional[date]:
        for key in ("eventDate", "endDate", "end_date", "startDate", "start_date", "startTime"):
            parsed = self._parse_datetime(row.get(key))
            if parsed:
                return parsed.date()
        haystack = self._market_text(row)
        match = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s+\d{4})?", haystack, re.I)
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
                # Avoid parsing dates in slugs such as may-8-2026 as temperature
                # buckets. Highest-temp buckets are narrow in either F or C.
                if high > low and high <= 150 and (high - low) <= 20:
                    return low, high
        return None, None

    def _extract_threshold(self, question: str) -> Optional[float]:
        match = THRESHOLD_PATTERN.search(question)
        if not match:
            return None
        return float(match.group("threshold"))

    def _market_text(self, row: dict[str, Any]) -> str:
        tags = row.get("tags") or []
        tag_text = " ".join(str(tag.get("label") or tag.get("slug") or "") for tag in tags if isinstance(tag, dict))
        outcomes = " ".join(str(x) for x in self._loads(row.get("outcomes"), []))
        return " ".join(
            str(x or "")
            for x in [
                row.get("question"),
                row.get("title"),
                row.get("eventTitle"),
                row.get("slug"),
                row.get("eventSlug"),
                row.get("description"),
                tag_text,
                outcomes,
            ]
        ).lower()

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
