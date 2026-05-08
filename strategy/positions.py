from __future__ import annotations

import math
import re
from datetime import date
from typing import Optional

from models import BucketProbability, WeatherMarket


def bucket_for_temp(temp_f: float, width_f: int) -> tuple[float, float]:
    low = math.floor(temp_f / width_f) * width_f
    return float(low), float(low + width_f)


def bucket_label(low_f: float, high_f: float) -> str:
    return f"{low_f:.0f}-{high_f:.0f}°F"


def bucket_distance(temp_f: float, low_f: float, high_f: float) -> float:
    if low_f <= temp_f < high_f:
        return 0.0
    return min(abs(temp_f - low_f), abs(temp_f - high_f))


def probability_for_bucket(consensus_f: float, low_f: float, high_f: float, sigma_f: float) -> float:
    cdf_high = _normal_cdf((high_f - consensus_f) / sigma_f)
    cdf_low = _normal_cdf((low_f - consensus_f) / sigma_f)
    return max(0.0, min(1.0, cdf_high - cdf_low))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def market_bucket_from_question(market: WeatherMarket, default_width_f: int) -> Optional[tuple[float, float]]:
    if market.bucket_low_f is not None and market.bucket_high_f is not None:
        return market.bucket_low_f, market.bucket_high_f
    if market.threshold_f is not None:
        return market.threshold_f, market.threshold_f + default_width_f
    for outcome in market.outcomes:
        match = re.search(r"(\d{2,3})\s*(?:-|to|–)\s*(\d{2,3})", outcome.label)
        if match:
            return float(match.group(1)), float(match.group(2))
    return None


def match_yes_price(market: WeatherMarket) -> tuple[Optional[str], Optional[float]]:
    for outcome in market.outcomes:
        if outcome.label.lower() == "yes":
            return outcome.token_id, outcome.price
    if market.outcomes:
        outcome = market.outcomes[0]
        return outcome.token_id, outcome.price
    return None, None


def build_bucket_ladder(
    consensus_f: float,
    market_date: date,
    width_f: int,
    spread_f: Optional[float],
    markets: list[WeatherMarket],
) -> list[BucketProbability]:
    sigma = max(1.5, (spread_f or 2.5) / 1.35)
    center_low, _ = bucket_for_temp(consensus_f, width_f)
    lows = [center_low + width_f * offset for offset in range(-3, 4)]
    market_map: dict[tuple[float, float], WeatherMarket] = {}
    for market in markets:
        if market.target_date and market.target_date != market_date:
            continue
        bucket = market_bucket_from_question(market, width_f)
        if bucket:
            market_map[(bucket[0], bucket[1])] = market

    ladder = []
    for low in lows:
        high = low + width_f
        token_id = None
        price = None
        label = bucket_label(low, high)
        market = market_map.get((float(low), float(high)))
        if market:
            token_id, price = match_yes_price(market)
            label = market.question
        probability = probability_for_bucket(consensus_f, low, high, sigma)
        edge = probability - price if price is not None else None
        ladder.append(
            BucketProbability(
                low_f=float(low),
                high_f=float(high),
                probability=probability,
                market_price=price,
                edge=edge,
                outcome_token_id=token_id,
                label=label,
            )
        )
    return ladder
