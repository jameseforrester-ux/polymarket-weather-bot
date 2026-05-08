from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CityConfig:
    name: str
    lat: float
    lon: float
    metar_station: str
    asos_station: Optional[str]
    polymarket_keywords: tuple[str, ...]
    timezone: str


CITIES: dict[str, CityConfig] = {
    "denver": CityConfig("Denver", 39.7392, -104.9903, "KDEN", "KBKF", ("denver",), "America/Denver"),
    "chicago": CityConfig("Chicago", 41.8781, -87.6298, "KORD", "KMDW", ("chicago",), "America/Chicago"),
    "new york": CityConfig("New York", 40.7128, -74.0060, "KNYC", "KLGA", ("new york", "nyc", "manhattan"), "America/New_York"),
    "los angeles": CityConfig("Los Angeles", 34.0522, -118.2437, "KCQT", "KLAX", ("los angeles", "la"), "America/Los_Angeles"),
    "miami": CityConfig("Miami", 25.7617, -80.1918, "KMIA", "KOPF", ("miami",), "America/New_York"),
    "dallas": CityConfig("Dallas", 32.7767, -96.7970, "KDAL", "KDFW", ("dallas",), "America/Chicago"),
    "phoenix": CityConfig("Phoenix", 33.4484, -112.0740, "KPHX", "KDVT", ("phoenix",), "America/Phoenix"),
    "atlanta": CityConfig("Atlanta", 33.7490, -84.3880, "KATL", "KFTY", ("atlanta",), "America/New_York"),
}


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", str(ROOT / "bot.db"))
DEFAULT_BUCKET_WIDTH_F = int(os.getenv("DEFAULT_BUCKET_WIDTH_F", "2"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "1800"))
POLYMARKET_REFRESH_SECONDS = int(os.getenv("POLYMARKET_REFRESH_SECONDS", "14400"))
ALERT_POLL_SECONDS = int(os.getenv("ALERT_POLL_SECONDS", "3600"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


CONSENSUS_WEIGHTS_D_PLUS = {
    "ecmwf": 0.50,
    "openweather": 0.30,
    "hrrr": 0.20,
}

CONSENSUS_WEIGHTS_DAY_OF = {
    "hrrr": 0.70,
    "ecmwf": 0.15,
    "openweather": 0.10,
    "metar": 0.05,
}


def get_city(name: str) -> Optional[CityConfig]:
    normalized = name.strip().lower()
    if normalized in CITIES:
        return CITIES[normalized]
    for city in CITIES.values():
        if normalized in city.polymarket_keywords:
            return city
    return None
