from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import httpx

from config import CACHE_TTL_SECONDS, CityConfig
from data.cache import TTLCache
from models import ForecastPoint


class ECMWFClient:
    def __init__(self, http: httpx.AsyncClient, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.http = http
        self.cache = TTLCache(ttl_seconds)

    async def forecast(self, city: CityConfig, target_date: date) -> ForecastPoint:
        key = f"ecmwf:{city.name}:{target_date}"
        cached = self.cache.get(key)
        if cached:
            return cached

        params = {
            "latitude": city.lat,
            "longitude": city.lon,
            "timezone": city.timezone,
            "temperature_unit": "fahrenheit",
            "models": "ecmwf_ifs025",
            "hourly": "temperature_2m",
            "daily": "temperature_2m_max,temperature_2m_min",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        }
        try:
            response = await self.http.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            high = self._first(data.get("daily", {}).get("temperature_2m_max"))
            hourly = self._hourly(data)
            point = ForecastPoint(source="ecmwf", high_f=high, hourly_f=hourly, confidence=0.72)
        except Exception as exc:
            point = ForecastPoint(source="ecmwf", high_f=None, error=str(exc), confidence=0.0)
        self.cache.set(key, point)
        return point

    def _first(self, values: Optional[list[float]]) -> Optional[float]:
        return float(values[0]) if values else None

    def _hourly(self, data: dict) -> list[tuple[datetime, float]]:
        times = data.get("hourly", {}).get("time") or []
        temps = data.get("hourly", {}).get("temperature_2m") or []
        rows = []
        for t, temp in zip(times, temps):
            try:
                rows.append((datetime.fromisoformat(t), float(temp)))
            except Exception:
                continue
        return rows
