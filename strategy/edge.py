from __future__ import annotations

from models import BucketProbability


def classify_edge(bucket: BucketProbability) -> str:
    if bucket.edge is None:
        return "NO PRICE"
    if bucket.edge >= 0.15:
        return "STRONG BUY"
    if bucket.edge >= 0.07:
        return "BUY"
    if bucket.edge >= 0.02:
        return "LEAN BUY"
    if bucket.edge <= -0.10:
        return "AVOID"
    return "PASS"


def edge_summary(bucket: BucketProbability) -> str:
    if bucket.market_price is None or bucket.edge is None:
        return "No live Polymarket price found for this bucket."
    return (
        f"Model {bucket.probability:.0%} vs market {bucket.market_price:.0%}; "
        f"edge {bucket.edge:+.0%}; signal {classify_edge(bucket)}."
    )
