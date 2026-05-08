from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Optional


@dataclass
class MarketOutcome:
    label: str
    token_id: Optional[str] = None
    price: Optional[float] = None
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None


@dataclass
class WeatherMarket:
    market_id: str
    condition_id: Optional[str]
    question: str
    slug: Optional[str]
    city: Optional[str]
    target_date: Optional[date]
    bucket_low_f: Optional[float]
    bucket_high_f: Optional[float]
    threshold_f: Optional[float]
    market_unit: str = "F"
    market_label: Optional[str] = None
    outcomes: list[MarketOutcome] = field(default_factory=list)
    end_time: Optional[datetime] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ForecastPoint:
    source: str
    high_f: Optional[float]
    hourly_f: list[tuple[datetime, float]] = field(default_factory=list)
    observed_high_f: Optional[float] = None
    current_temp_f: Optional[float] = None
    station: Optional[str] = None
    confidence: float = 0.5
    error: Optional[str] = None


@dataclass
class ConsensusResult:
    city: str
    target_date: date
    mode: str
    consensus_high_f: Optional[float]
    model_spread_f: Optional[float]
    agreement: str
    points: list[ForecastPoint]
    warnings: list[str] = field(default_factory=list)


@dataclass
class BucketProbability:
    low_f: float
    high_f: float
    probability: float
    market_price: Optional[float] = None
    edge: Optional[float] = None
    outcome_token_id: Optional[str] = None
    label: Optional[str] = None


@dataclass
class StrategyRecommendation:
    city: str
    target_date: date
    mode: str
    primary: BucketProbability
    bracket: list[tuple[BucketProbability, float]]
    action: str
    confidence: float
    boundary_risk: bool
    edge_summary: Optional[str]
    warnings: list[str] = field(default_factory=list)
