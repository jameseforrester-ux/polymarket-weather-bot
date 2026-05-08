from __future__ import annotations

from datetime import date
from statistics import mean

from config import CONSENSUS_WEIGHTS_DAY_OF, CONSENSUS_WEIGHTS_D_PLUS
from models import ConsensusResult, ForecastPoint


def build_consensus(
    city_name: str,
    target_date: date,
    mode: str,
    points: list[ForecastPoint],
) -> ConsensusResult:
    usable = [p for p in points if p.high_f is not None]
    warnings = [f"{p.source} unavailable: {p.error}" for p in points if p.error]
    if not usable:
        return ConsensusResult(city_name, target_date, mode, None, None, "High Divergence", points, warnings)

    values = [float(p.high_f) for p in usable]
    model_spread = max(values) - min(values) if len(values) > 1 else 0.0
    agreement = "Consensus" if model_spread <= 3 else "Split" if model_spread <= 5 else "High Divergence"

    weights = CONSENSUS_WEIGHTS_DAY_OF if mode == "today" else CONSENSUS_WEIGHTS_D_PLUS
    preliminary = _weighted_average(usable, weights)

    # User-specific rule: METAR is primarily monitoring/alert data. It only nudges
    # day-of consensus when observed high/current temp is close to model consensus.
    if mode == "today":
        model_only = [p for p in usable if not p.source.startswith("metar")]
        metars = [p for p in usable if p.source.startswith("metar")]
        model_anchor = _weighted_average(model_only, weights) if model_only else preliminary
        included = model_only[:]
        for metar in metars:
            obs = metar.observed_high_f or metar.current_temp_f or metar.high_f
            if obs is not None and abs(obs - model_anchor) <= 2.0:
                included.append(metar)
            else:
                warnings.append(f"{metar.station or metar.source} monitoring only; not in consensus because it diverges from model anchor")
        consensus = _weighted_average(included, weights) if included else model_anchor
    else:
        consensus = preliminary

    return ConsensusResult(
        city=city_name,
        target_date=target_date,
        mode=mode,
        consensus_high_f=consensus,
        model_spread_f=model_spread,
        agreement=agreement,
        points=points,
        warnings=warnings,
    )


def _weighted_average(points: list[ForecastPoint], weights: dict[str, float]) -> float:
    weighted_sum = 0.0
    total_weight = 0.0
    for point in points:
        if point.high_f is None:
            continue
        source = "metar" if point.source.startswith("metar") else point.source
        weight = weights.get(source, 0.10) * max(point.confidence, 0.05)
        weighted_sum += point.high_f * weight
        total_weight += weight
    if total_weight == 0:
        return mean([p.high_f for p in points if p.high_f is not None])
    return weighted_sum / total_weight
