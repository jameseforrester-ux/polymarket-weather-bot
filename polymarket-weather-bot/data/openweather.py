from __future__ import annotations

from datetime import date, datetime

import httpx

from config import CACHE_TTL_SECONDS, OPENWEATHER_API_KEY, CityConfig
from data.cache import TTLCache
from models import ForecastPoint


class OpenWeatherClient:
    def __init__(self, http: httpx.AsyncClient, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.http = http
        self.cache = TTLCache(ttl_seconds)

    async def forecast(self, city: CityConfig, target_date: date) -> ForecastPoint:
        if not OPENWEATHER_API_KEY:
            return ForecastPoint(source="openweather", high_f=None, error="OPENWEATHER_API_KEY not set", confidence=0.0)
        key = f"openweather:{city.name}:{target_date}"
        cached = self.cache.get(key)
        if cached:
            return cached

        params = {
            "lat": city.lat,
            "lon": city.lon,
            "appid": OPENWEATHER_API_KEY,
            "units": "imperial",
            "exclude": "minutely,alerts",
        }
        try:
            response = await self.http.get("https://api.openweathermap.org/data/3.0/onecall", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            high = self._daily_high(data, target_date)
            hourly = self._hourly(data)
            current = data.get("current", {}).get("temp")
            point = ForecastPoint(
                source="openweather",
                high_f=high,
                hourly_f=hourly,
                current_temp_f=float(current) if current is not None else None,
                confidence=0.58,
            )
        except Exception as exc:
            point = ForecastPoint(source="openweather", high_f=None, error=str(exc), confidence=0.0)
        self.cache.set(key, point)
        return point

    def _daily_high(self, data: dict, target_date: date) -> float | None:
        for day in data.get("daily", []):
            try:
                dt = datetime.fromtimestamp(day["dt"]).date()
                if dt == target_date:
                    return float(day["temp"]["max"])
            except Exception:
                continue
        return None

    def _hourly(self, data: dict) -> list[tuple[datetime, float]]:
        rows = []
        for row in data.get("hourly", []):
            try:
                rows.append((datetime.fromtimestamp(row["dt"]), float(row["temp"])))
            except Exception:
                continue
        return rows
