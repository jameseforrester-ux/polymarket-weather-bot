from __future__ import annotations

import logging
from datetime import date, time

from telegram.ext import Application

from config import ALERT_POLL_SECONDS
from formatters.messages import strategy_message
from strategy.positions import bucket_label


log = logging.getLogger(__name__)


async def refresh_markets_job(context) -> None:
    services = context.application.bot_data["services"]
    await services.active_markets(force=True)


async def alert_poll_job(context) -> None:
    app: Application = context.application
    services = app.bot_data["services"]
    db = app.bot_data["db"]
    alerts = await db.active_alerts()
    for alert in alerts:
        consensus, rec = await services.recommendation_for_city(alert["city"], 0)
        if not consensus or not rec:
            continue
        observed = None
        for point in consensus.points:
            if point.source == "metar":
                observed = point.observed_high_f or point.current_temp_f
                break
        projected = consensus.consensus_high_f
        threshold = float(alert["threshold_f"])
        if (observed is not None and observed >= threshold) or (projected is not None and projected >= threshold):
            await app.bot.send_message(
                chat_id=alert["chat_id"],
                text=(
                    f"Threshold alert for {alert['city']}: {threshold:.1f}°F crossed or projected.\n\n"
                    + strategy_message(consensus, rec)
                ),
                parse_mode="HTML",
            )


async def position_change_job(context) -> None:
    app: Application = context.application
    services = app.bot_data["services"]
    db = app.bot_data["db"]
    for chat_id in await db.subscribers():
        for consensus, rec in await services.recommendations_all(0):
            bucket = bucket_label(rec.primary.low_f, rec.primary.high_f)
            target = date.today().isoformat()
            previous = await db.last_position(chat_id, rec.city, target)
            if previous and previous != bucket:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=f"Position shift detected: {rec.city} moved from {previous} to {bucket}.\n\n" + strategy_message(consensus, rec),
                    parse_mode="HTML",
                )
            await db.set_last_position(chat_id, rec.city, target, bucket)


def install_jobs(application: Application) -> None:
    jq = application.job_queue
    jq.run_repeating(refresh_markets_job, interval=4 * 60 * 60, first=10, name="refresh_markets")
    jq.run_repeating(alert_poll_job, interval=ALERT_POLL_SECONDS, first=60, name="alerts")
    jq.run_repeating(position_change_job, interval=60 * 60, first=120, name="position_changes")
    jq.run_daily(position_change_job, time=time(hour=15, minute=0), name="daily_position_check")
