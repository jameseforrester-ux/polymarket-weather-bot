from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from models import WeatherMarket
from formatters.messages import grouped_market_keys


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Active Markets", callback_data="markets"), InlineKeyboardButton("Today", callback_data="today")],
            [InlineKeyboardButton("Tomorrow", callback_data="tomorrow"), InlineKeyboardButton("Day After", callback_data="dayafter")],
            [InlineKeyboardButton("Best Edge", callback_data="edge"), InlineKeyboardButton("Settings", callback_data="settings")],
        ]
    )


def market_menu(markets: list[WeatherMarket], prefix: str = "market") -> InlineKeyboardMarkup:
    rows = []
    for idx, (_key, grouped) in enumerate(grouped_market_keys(markets)[:20]):
        sample = grouped[0]
        label = f"{sample.city or 'Unknown'} {sample.target_date or ''} ({len(grouped)} buckets)".strip()
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"{prefix}:group:{idx}")])
    rows.append([InlineKeyboardButton("Refresh", callback_data="markets"), InlineKeyboardButton("Back", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def city_menu(cities: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(city, callback_data=f"city:{city}")] for city in cities]
    rows.append([InlineKeyboardButton("Back", callback_data="home")])
    return InlineKeyboardMarkup(rows)
