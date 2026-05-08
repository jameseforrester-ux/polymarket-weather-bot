# Polymarket Weather Temperature Telegram Bot

A Python Telegram bot that discovers active Polymarket high-temperature markets, tracks them by city/date/bucket, pulls weather model forecasts, compares model probabilities to live market prices, and recommends bucket/bracket strategies.

## What it does

- Discovers active weather temperature markets from Polymarket Gamma.
- Fetches live YES pricing from the Polymarket CLOB.
- Pulls ECMWF via Open-Meteo, OpenWeather, HRRR via Herbie, and METAR/ASOS observations.
- For D+1/D+2, builds a bracket strategy around model consensus.
- For day-of, uses HRRR as the primary ground-truth forecast anchor.
- Uses METAR/ASOS for rolling high monitoring and alerts. METAR only influences consensus when it is close to model consensus.
- Shows menu buttons for active markets, tracked markets, city drilldowns, edge ranking, and alert setup.
- Stores subscriptions, tracked markets, settings, and alerts in SQLite.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your Telegram bot token and OpenWeather key.

Then run:

```bash
python bot.py
```

## Telegram commands

- `/start` - Welcome menu and market refresh.
- `/markets` - Active discovered Polymarket high-temp markets.
- `/track` - Track all discovered supported markets.
- `/today` - Day-of recommendations.
- `/tomorrow` - D+1 bracket recommendations.
- `/dayafter` - D+2 bracket recommendations.
- `/edge` - Rank market/model edge.
- `/city Denver` - Detailed city breakdown.
- `/models Denver` - Raw model comparison table.
- `/alert Denver 74` - Alert when observed/projected temp crosses a threshold.
- `/settings` - Current settings.
- `/help` - Command reference.

## Notes

This bot is an assistant, not an execution bot. It does not place trades. HRRR support depends on optional scientific Python dependencies and remote model availability. If HRRR fails, the bot degrades gracefully and flags the missing source.
