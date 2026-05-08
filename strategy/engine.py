from __future__ import annotations

from datetime import date

from models import ConsensusResult, StrategyRecommendation, WeatherMarket
from strategy.edge import edge_summary
from strategy.positions import build_bucket_ladder, bucket_for_temp


class StrategyEngine:
    def __init__(self, bucket_width_f: int = 2):
        self.bucket_width_f = bucket_width_f

    def recommend(
        self,
        consensus: ConsensusResult,
        markets: list[WeatherMarket],
    ) -> StrategyRecommendation | None:
        if consensus.consensus_high_f is None:
            return None
        ladder = build_bucket_ladder(
            consensus_f=consensus.consensus_high_f,
            market_date=consensus.target_date,
            width_f=self.bucket_width_f,
            spread_f=consensus.model_spread_f,
            markets=markets,
        )
        primary = max(ladder, key=lambda b: (b.edge if b.edge is not None else -99, b.probability))
        if primary.edge is None or primary.edge < 0:
            center_low, center_high = bucket_for_temp(consensus.consensus_high_f, self.bucket_width_f)
            primary = min(ladder, key=lambda b: abs(b.low_f - center_low) + abs(b.high_f - center_high))

        adjacent = sorted(
            [b for b in ladder if b is not primary],
            key=lambda b: abs(((b.low_f + b.high_f) / 2) - consensus.consensus_high_f),
        )[:2]
        total = primary.probability + sum(b.probability for b in adjacent)
        bracket = []
        for bucket in [primary] + adjacent:
            ratio = bucket.probability / total if total else 0
            bracket.append((bucket, ratio))

        distance_to_boundary = min(
            abs(consensus.consensus_high_f - primary.low_f),
            abs(consensus.consensus_high_f - primary.high_f),
        )
        boundary_risk = distance_to_boundary <= 0.5
        confidence = min(0.92, max(0.35, primary.probability + (0.15 if consensus.agreement == "Consensus" else 0.0)))
        action = "HOLD" if consensus.mode == "today" else "BRACKET"
        if boundary_risk:
            action = "SPLIT"
        if primary.edge is not None and primary.edge >= 0.07:
            action = "BUY" if consensus.mode != "today" else "HOLD/BUY"

        return StrategyRecommendation(
            city=consensus.city,
            target_date=consensus.target_date,
            mode=consensus.mode,
            primary=primary,
            bracket=bracket,
            action=action,
            confidence=confidence,
            boundary_risk=boundary_risk,
            edge_summary=edge_summary(primary),
            warnings=consensus.warnings[:],
        )
