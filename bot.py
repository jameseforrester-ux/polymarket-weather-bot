from __future__ import annotations

import logging
from datetime import date

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from config import DATABASE_PATH, LOG_LEVEL, TELEGRAM_BOT_TOKEN, get_city
from formatters.keyboards import main_menu, market_menu
from formatters.messages import (
    help_message,
    markets_message,
    models_message,
    settings_message,
    start_message,
    strategy_message,
)
from scheduler import install_jobs
from services import WeatherBotServices
from storage.db import Database


logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))
log = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.application.bot_data["db"].ensure_user(update.effective_chat.id)
    await update.effective_message.reply_text(start_message(), parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(help_message(), parse_mode=ParseMode.HTML)


async def markets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    markets = await services.active_markets(force=True)
    await update.effective_message.reply_text(markets_message(markets), parse_mode=ParseMode.HTML, reply_markup=market_menu(markets))


async def track_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    services = context.application.bot_data["services"]
    chat_id = update.effective_chat.id
    markets = await services.active_markets()
    count = 0
    for market in markets:
        if market.city:
            await db.track_market(chat_id, market.market_id, market.city, market.target_date.isoformat() if market.target_date else None, market.question)
            count += 1
    await update.effective_message.reply_text(f"Tracking {count} supported active markets.", parse_mode=ParseMode.HTML)


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _multi_recommendation(update, context, 0)


async def tomorrow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _multi_recommendation(update, context, 1)


async def dayafter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _multi_recommendation(update, context, 2)


async def edge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services = context.application.bot_data["services"]
    ranked = await services.best_edges()
    if not ranked:
        await update.effective_message.reply_text("No priced edges found yet.", parse_mode=ParseMode.HTML)
        return
    lines = ["<b>BEST MODEL VS MARKET EDGE</b>", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    for edge, _consensus, rec in ranked[:10]:
        price = f"{rec.primary.market_price:.0%}" if rec.primary.market_price is not None else "n/a"
        lines.append(f"• <b>{rec.city}</b> {rec.primary.low_f:.0f}-{rec.primary.high_f:.0f}°F edge {edge:+.0%} price {price}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def city_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city_name = " ".join(context.args) if context.args else ""
    if not city_name:
        await update.effective_message.reply_text("Usage: /city Denver")
        return
    consensus, rec = await context.application.bot_data["services"].recommendation_for_city(city_name, 0)
    if not consensus:
        await update.effective_message.reply_text(f"Unsupported city: {city_name}")
        return
    await update.effective_message.reply_text(strategy_message(consensus, rec), parse_mode=ParseMode.HTML)


async def models_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city_name = " ".join(context.args) if context.args else ""
    city = get_city(city_name)
    if not city:
        await update.effective_message.reply_text("Usage: /models Denver")
        return
    consensus = await context.application.bot_data["services"].city_consensus(city, date.today(), "today")
    await update.effective_message.reply_text(models_message(consensus), parse_mode=ParseMode.HTML)


async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /alert Denver 74")
        return
    city_name = " ".join(context.args[:-1])
    city = get_city(city_name)
    if not city:
        await update.effective_message.reply_text(f"Unsupported city: {city_name}")
        return
    try:
        threshold = float(context.args[-1])
    except ValueError:
        await update.effective_message.reply_text("Threshold must be a number, e.g. /alert Denver 74")
        return
    await context.application.bot_data["db"].add_alert(update.effective_chat.id, city.name, threshold)
    await update.effective_message.reply_text(f"Alert set for {city.name} at {threshold:.1f}°F.")


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = await context.application.bot_data["db"].user_settings(update.effective_chat.id)
    await update.effective_message.reply_text(settings_message(settings), parse_mode=ParseMode.HTML)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "home":
        await _safe_edit(query, start_message(), parse_mode=ParseMode.HTML, reply_markup=main_menu())
    elif data == "markets":
        markets = await context.application.bot_data["services"].active_markets(force=True)
        await _safe_edit(query, markets_message(markets), parse_mode=ParseMode.HTML, reply_markup=market_menu(markets))
    elif data in {"today", "tomorrow", "dayafter"}:
        offset = {"today": 0, "tomorrow": 1, "dayafter": 2}[data]
        results = await context.application.bot_data["services"].recommendations_all(offset)
        text = "\n\n".join(strategy_message(c, r) for c, r in results[:3]) or "No recommendations available."
        await _safe_edit(query, text[:4000], parse_mode=ParseMode.HTML, reply_markup=main_menu())
    elif data == "edge":
        ranked = await context.application.bot_data["services"].best_edges()
        text = "\n".join(f"{rec.city}: {edge:+.0%}" for edge, _c, rec in ranked[:10]) or "No priced edges found yet."
        await _safe_edit(query, text, reply_markup=main_menu())
    elif data == "settings":
        settings = await context.application.bot_data["db"].user_settings(query.message.chat_id)
        await _safe_edit(query, settings_message(settings), parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def _safe_edit(query, text: str, **kwargs) -> None:
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        raise


async def _multi_recommendation(update: Update, context: ContextTypes.DEFAULT_TYPE, offset_days: int) -> None:
    results = await context.application.bot_data["services"].recommendations_all(offset_days)
    if not results:
        await update.effective_message.reply_text("No recommendations available.")
        return
    for consensus, rec in results:
        await update.effective_message.reply_text(strategy_message(consensus, rec), parse_mode=ParseMode.HTML)


async def post_init(application: Application) -> None:
    db = Database(DATABASE_PATH)
    await db.init()
    http = httpx.AsyncClient(headers={"User-Agent": "polymarket-weather-temp-bot/0.1"})
    application.bot_data["db"] = db
    application.bot_data["http"] = http
    application.bot_data["services"] = WeatherBotServices(http)
    install_jobs(application)


async def post_shutdown(application: Application) -> None:
    http = application.bot_data.get("http")
    if http:
        await http.aclose()


def build_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to .env before running.")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("markets", markets_cmd))
    app.add_handler(CommandHandler("track", track_cmd))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("tomorrow", tomorrow_cmd))
    app.add_handler(CommandHandler("dayafter", dayafter_cmd))
    app.add_handler(CommandHandler("edge", edge_cmd))
    app.add_handler(CommandHandler("city", city_cmd))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CommandHandler("alert", alert_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    return app


if __name__ == "__main__":
    build_app().run_polling(close_loop=False)
