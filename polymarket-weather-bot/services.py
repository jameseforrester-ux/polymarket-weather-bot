from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx

from config import CITIES, DEFAULT_BUCKET_WIDTH_F, CityConfig, get_city
from data.ecmwf import ECMWFClient
from data.hrrr import HRRRClient
from data.metar import MetarClient
from data.openweather import OpenWeatherClient
from data.polymarket import PolymarketClient
from models import ConsensusResult, WeatherMarket
from strategy.consensus import build_consensus
from strategy.engine import StrategyEngine


class WeatherBotServices:
    def __init__(self, http: httpx.AsyncClient, bucket_width_f: int = DEFAULT_BUCKET_WIDTH_F):
        self.http = http
        self.polymarket = PolymarketClient(http)
        self.ecmwf = ECMWFClient(http)
        self.openweather = OpenWeatherClient(http)
        self.metar = MetarClient(http)
        self.hrrr = HRRRClient()
        self.engine = StrategyEngine(bucket_width_f)

    async def active_markets(self, force: bool = False) -> list[WeatherMarket]:
        return await self.polymarket.discover_weather_markets(force=force)

    async def city_consensus(self, city: CityConfig, target: date, mode: str) -> ConsensusResult:
        tasks = [
            self.ecmwf.forecast(city, target),
            self.openweather.forecast(city, target),
        ]
        # HRRR has short useful horizon; try it for today/tomorrow, fail gracefully otherwise.
        if mode in {"today", "tomorrow"}:
            tasks.append(self.hrrr.forecast(city, target))
        if mode == "today":
            tasks.append(self.metar.rolling_high(city, target, secondary=False))
            if city.asos_station:
                tasks.append(self.metar.rolling_high(city, target, secondary=True))
        points = await asyncio.gather(*tasks)

        # Secondary station discrepancy warning.
        consensus = build_consensus(city.name, target, mode, list(points))
        primary = next((p for p in points if p.source == "metar"), None)
        secondary = next((p for p in points if p.source == "metar_secondary"), None)
        if primary and secondary and primary.observed_high_f is not None and secondary.observed_high_f is not None:
            gap = abs(primary.observed_high_f - secondary.observed_high_f)
            if gap > 2:
                consensus.warnings.append(f"{primary.station}/{secondary.station} observed highs diverge by {gap:.1f}°F")
        return consensus

    async def recommendation_for_city(self, city_name: str, offset_days: int):
        city = get_city(city_name)
        if city is None:
            return None, None
        target = date.today() + timedelta(days=offset_days)
        mode = "today" if offset_days == 0 else "tomorrow" if offset_days == 1 else "dayafter"
        markets = [m for m in await self.active_markets() if m.city == city.name]
        consensus = await self.city_consensus(city, target, mode)
        rec = self.engine.recommend(consensus, markets)
        return consensus, rec

    async def recommendations_all(self, offset_days: int):
        results = []
        for city in CITIES.values():
            consensus, rec = await self.recommendation_for_city(city.name, offset_days)
            if consensus and rec:
                results.append((consensus, rec))
        return results

    async def best_edges(self):
        results = await self.recommendations_all(1)
        ranked = []
        for consensus, rec in results:
            if rec.primary.edge is not None:
                ranked.append((rec.primary.edge, consensus, rec))
        return sorted(ranked, key=lambda x: x[0], reverse=True)
