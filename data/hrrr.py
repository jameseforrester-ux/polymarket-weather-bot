from __future__ import annotations

from datetime import date, datetime

import httpx

from config import CACHE_TTL_SECONDS, CityConfig
from data.cache import TTLCache
from models import ForecastPoint


class HRRRClient:
    """HRRR-backed forecast via Open-Meteo's GFS/HRRR API.

    This avoids noisy Herbie/GRIB downloads in the Telegram bot process while
    still using hourly HRRR-updated guidance for CONUS day-of checks.
    """

    def __init__(self, http: httpx.AsyncClient, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.http = http
        self.cache = TTLCache(ttl_seconds)

    async def forecast(self, city: CityConfig, target_date: date) -> ForecastPoint:
        key = f"hrrr_openmeteo:{city.name}:{target_date}"
        cached = self.cache.get(key)
        if cached:
            return cached

        params = {
            "latitude": city.lat,
            "longitude": city.lon,
            "timezone": city.timezone,
            "temperature_unit": "fahrenheit",
            "hourly": "temperature_2m",
            "daily": "temperature_2m_max",
            # Open-Meteo's GFS endpoint uses best_match to blend HRRR updates
            # into CONUS hourly forecasts when HRRR is available.
            "models": "best_match",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        }
        try:
            response = await self.http.get("https://api.open-meteo.com/v1/gfs", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            high = self._first(data.get("daily", {}).get("temperature_2m_max"))
            hourly = self._hourly(data)
            if high is None and hourly:
                high = max(temp for _, temp in hourly)
            point = ForecastPoint(source="hrrr", high_f=high, hourly_f=hourly, confidence=0.80)
        except Exception as exc:
            point = ForecastPoint(source="hrrr", high_f=None, error=f"HRRR unavailable via Open-Meteo: {exc}", confidence=0.0)
        self.cache.set(key, point, ttl_seconds=900)
        return point

    def _first(self, values):
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
