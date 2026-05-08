from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from config import CACHE_TTL_SECONDS, CityConfig
from data.cache import TTLCache
from models import ForecastPoint


log = logging.getLogger(__name__)


class HRRRClient:
    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.cache = TTLCache(ttl_seconds)

    async def forecast(self, city: CityConfig, target_date: date) -> ForecastPoint:
        key = f"hrrr:{city.name}:{target_date}"
        cached = self.cache.get(key)
        if cached:
            return cached
        try:
            point = await asyncio.to_thread(self._forecast_sync, city, target_date)
        except Exception as exc:
            log.warning("HRRR forecast failed for %s: %s", city.name, exc)
            point = ForecastPoint(source="hrrr", high_f=None, error=str(exc), confidence=0.0)
        self.cache.set(key, point)
        return point

    def _forecast_sync(self, city: CityConfig, target_date: date) -> ForecastPoint:
        try:
            from herbie import Herbie
        except Exception as exc:
            raise RuntimeError("Install optional HRRR dependencies: herbie-data, xarray, cfgrib") from exc

        now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        run_time = now_utc - timedelta(hours=2)
        run_time = run_time.replace(hour=run_time.hour)

        hourly: list[tuple[datetime, float]] = []
        max_f: Optional[float] = None
        for fxx in range(0, 37):
            valid = run_time + timedelta(hours=fxx)
            if valid.date() != target_date:
                continue
            try:
                h = Herbie(run_time.strftime("%Y-%m-%d %H:00"), model="hrrr", product="sfc", fxx=fxx)
                ds = h.xarray("TMP:2 m")
                picked = ds.herbie.nearest_points(points=[(city.lon, city.lat)], names=[city.name])
                kelvin = float(picked.t2m.values[0])
                temp_f = (kelvin - 273.15) * 9 / 5 + 32
                hourly.append((valid.replace(tzinfo=None), temp_f))
                max_f = temp_f if max_f is None else max(max_f, temp_f)
            except Exception as exc:
                log.debug("Skipping HRRR f%02d for %s: %s", fxx, city.name, exc)
                continue

        if max_f is None:
            raise RuntimeError("No HRRR 2m temperature points available")
        return ForecastPoint(source="hrrr", high_f=max_f, hourly_f=hourly, confidence=0.82)
