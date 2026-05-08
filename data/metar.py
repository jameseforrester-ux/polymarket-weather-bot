from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx

from config import CACHE_TTL_SECONDS, CityConfig
from data.cache import TTLCache
from models import ForecastPoint


class MetarClient:
    def __init__(self, http: httpx.AsyncClient, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.http = http
        self.cache = TTLCache(ttl_seconds)

    async def rolling_high(self, city: CityConfig, target_date: date, secondary: bool = False) -> ForecastPoint:
        station = city.asos_station if secondary else city.metar_station
        if not station:
            return ForecastPoint(source="metar_secondary" if secondary else "metar", high_f=None, error="No station configured")

        key = f"metar:{station}:{target_date}"
        cached = self.cache.get(key)
        if cached:
            return cached

        local_start = datetime.combine(target_date, time.min, tzinfo=ZoneInfo(city.timezone))
        hours = max(1, int((datetime.now(tz=ZoneInfo(city.timezone)) - local_start).total_seconds() // 3600) + 2)
        params = {"ids": station, "format": "json", "hours": min(hours, 30)}
        try:
            response = await self.http.get("https://aviationweather.gov/api/data/metar", params=params, timeout=20)
            if response.status_code == 204:
                raise RuntimeError("No METAR data returned")
            response.raise_for_status()
            rows = response.json()
            temps = []
            latest_temp = None
            for row in rows:
                obs_time = self._obs_time(row)
                if obs_time is None:
                    continue
                local_obs = obs_time.astimezone(ZoneInfo(city.timezone))
                if local_obs.date() != target_date:
                    continue
                temp_c = row.get("temp") or row.get("temp_c")
                if temp_c is None:
                    continue
                temp_f = float(temp_c) * 9 / 5 + 32
                temps.append(temp_f)
                latest_temp = temp_f
            high = max(temps) if temps else None
            point = ForecastPoint(
                source="metar_secondary" if secondary else "metar",
                high_f=high,
                observed_high_f=high,
                current_temp_f=latest_temp,
                station=station,
                confidence=0.55,
            )
        except Exception as exc:
            point = ForecastPoint(
                source="metar_secondary" if secondary else "metar",
                high_f=None,
                station=station,
                error=str(exc),
                confidence=0.0,
            )
        self.cache.set(key, point, ttl_seconds=600)
        return point

    def _obs_time(self, row: dict) -> datetime | None:
        for key in ("obsTime", "reportTime", "receiptTime"):
            value = row.get(key)
            if value is None:
                continue
            try:
                if isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value, tz=ZoneInfo("UTC"))
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
                return parsed
            except Exception:
                continue
        return None
