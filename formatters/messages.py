from __future__ import annotations

import re
from html import escape
from collections import defaultdict

from models import ConsensusResult, ForecastPoint, StrategyRecommendation, WeatherMarket
from strategy.edge import classify_edge
from strategy.positions import bucket_label


def confidence_icon(confidence: float) -> str:
    if confidence > 0.70:
        return "🟢"
    if confidence >= 0.50:
        return "🟡"
    return "🔴"


def agreement_icon(agreement: str) -> str:
    return {"Consensus": "🟢", "Split": "🟡", "High Divergence": "🔴"}.get(agreement, "⚪")


def start_message() -> str:
    return (
        "<b>Polymarket Weather Temp Bot</b>\n"
        "Tracks active high-temperature markets, cross-checks live Polymarket prices against weather consensus, "
        "and recommends day-of or bracket bucket strategy.\n\n"
        "Use the buttons below or commands like /markets, /today, /tomorrow, /edge, /city Denver."
    )


def markets_message(markets: list[WeatherMarket]) -> str:
    if not markets:
        return "No active high-temperature Polymarket markets were discovered."
    groups = grouped_market_keys(markets)
    lines = [
        "<b>ACTIVE HIGH TEMP MARKETS</b>",
        f"Found {len(markets)} bucket markets across {len(groups)} city/date groups.",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for (_city, _date, _event), grouped in groups[:40]:
        sample = grouped[0]
        prices = [o.price for m in grouped for o in m.outcomes if o.label.lower() == "yes" and o.price is not None]
        best = max(prices) if prices else None
        labels = [_market_bucket_text(m) for m in grouped]
        temp_range = _summarize_labels(labels)
        price = f"{best:.0%}" if best is not None else "n/a"
        unsupported = "" if sample.city else " ⚠️ unsupported"
        lines.append(
            f"• <b>{escape(sample.city or 'Unknown')}</b>{unsupported} | {escape(str(sample.target_date or 'date?'))} | "
            f"{len(grouped)} buckets {escape(temp_range)} | best YES {price}"
        )
    if len(groups) > 40:
        lines.append(f"… plus {len(groups) - 40} more groups.")
    return "\n".join(lines)


def strategy_message(consensus: ConsensusResult, rec: StrategyRecommendation | None) -> str:
    if rec is None:
        return f"<b>{escape(consensus.city.upper())}</b>\nNo recommendation. All forecast sources failed."

    primary = rec.primary
    lines = [
        f"<b>{escape(consensus.city.upper())} — {escape(rec.mode.upper())} POSITION</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Consensus High: <b>{consensus.consensus_high_f:.1f}°F</b>",
        f"{agreement_icon(consensus.agreement)} Model Agreement: {escape(consensus.agreement)} | Spread: {consensus.model_spread_f:.1f}°F",
        "",
        f"FINAL BUCKET: <b>{bucket_label(primary.low_f, primary.high_f)}</b>",
        f"Confidence: {confidence_icon(rec.confidence)} {rec.confidence:.0%}",
        f"Action: <b>{escape(rec.action)}</b>",
        f"Edge: {escape(rec.edge_summary or 'n/a')}",
    ]
    if rec.boundary_risk:
        lines.append("⚠️ BOUNDARY RISK: consensus is within 0.5°F of a bucket boundary. Split exposure.")

    lines.extend(["", "<b>Bracket sizing</b>", "<pre>"])
    for bucket, ratio in rec.bracket:
        price = f"{bucket.market_price:.0%}" if bucket.market_price is not None else "n/a"
        edge = f"{bucket.edge:+.0%}" if bucket.edge is not None else "n/a"
        lines.append(f"{bucket_label(bucket.low_f, bucket.high_f):>9}  size {ratio:>4.0%}  mkt {price:>4}  edge {edge:>5}")
    lines.append("</pre>")

    obs = [p for p in consensus.points if p.source.startswith("metar")]
    if obs:
        lines.extend(["", "<b>METAR monitoring</b>"])
        for p in obs:
            high = f"{p.observed_high_f:.1f}°F" if p.observed_high_f is not None else "n/a"
            current = f"{p.current_temp_f:.1f}°F" if p.current_temp_f is not None else "n/a"
            lines.append(f"{escape(p.station or p.source)} high {high}, current {current}")

    if rec.warnings:
        lines.extend(["", "<b>Warnings</b>"])
        lines.extend([f"• {escape(w)}" for w in rec.warnings[:5]])
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def models_message(consensus: ConsensusResult) -> str:
    lines = [
        f"<b>{escape(consensus.city.upper())} MODEL TABLE</b>",
        "<pre>",
        "source          high    current  station  status",
    ]
    for p in consensus.points:
        lines.append(_model_row(p))
    lines.append("</pre>")
    lines.append(f"Consensus: {consensus.consensus_high_f:.1f}°F" if consensus.consensus_high_f is not None else "Consensus: n/a")
    return "\n".join(lines)


def settings_message(settings: dict) -> str:
    return (
        "<b>SETTINGS</b>\n"
        f"Bucket width: {settings.get('bucket_width_f')}°F\n"
        f"Units: {escape(str(settings.get('units')))}\n\n"
        "Edit defaults in .env or extend /settings handlers for per-user controls."
    )


def help_message() -> str:
    return (
        "<b>COMMANDS</b>\n"
        "/markets - Discover active Polymarket high-temp markets\n"
        "/track - Track all supported discovered markets\n"
        "/today - Day-of HRRR-led recommendations\n"
        "/tomorrow - D+1 bracket recommendations\n"
        "/dayafter - D+2 bracket recommendations\n"
        "/edge - Best model-vs-market edge\n"
        "/city Denver - Detailed city breakdown\n"
        "/models Denver - Raw model comparison\n"
        "/alert Denver 74 - Temp threshold alert\n"
        "/settings - Current settings"
    )


def _yes_price(market: WeatherMarket) -> str:
    for outcome in market.outcomes:
        if outcome.label.lower() == "yes" and outcome.price is not None:
            return f"{outcome.price:.0%}"
    for outcome in market.outcomes:
        if outcome.price is not None:
            return f"{outcome.price:.0%}"
    return "n/a"


def _market_bucket_text(market: WeatherMarket) -> str:
    if market.market_label:
        return market.market_label
    if market.bucket_low_f is not None and market.bucket_high_f is not None:
        return f"{market.bucket_low_f:.0f}-{market.bucket_high_f:.0f}°F"
    if market.threshold_f is not None:
        return f">{market.threshold_f:.0f}°F"
    return "bucket?"


def grouped_market_keys(markets: list[WeatherMarket]):
    grouped = defaultdict(list)
    for market in markets:
        event_key = market.raw.get("eventSlug") or _base_slug(market.slug or "") or market.question
        grouped[(market.city or "Unknown", str(market.target_date or "date?"), event_key)].append(market)
    return sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0]))


def _base_slug(slug: str) -> str:
    return re.sub(r"-(?:\d{1,3})(?:c|f|corbelow|forbelow|corhigher|forhigher)?$", "", slug)


def _summarize_labels(labels: list[str]) -> str:
    clean = [label for label in labels if label and label != "bucket?"]
    if not clean:
        return ""
    if len(clean) <= 3:
        return ", ".join(clean)
    return f"{clean[0]} … {clean[-1]}"


def _model_row(p: ForecastPoint) -> str:
    high = f"{p.high_f:5.1f}" if p.high_f is not None else "  n/a"
    current = f"{p.current_temp_f:7.1f}" if p.current_temp_f is not None else "    n/a"
    station = (p.station or "-")[:7]
    status = "ok" if not p.error else "missing"
    return f"{p.source[:14]:14} {high}  {current}  {station:7}  {status}"
