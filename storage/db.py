from __future__ import annotations

from datetime import datetime
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    bucket_width_f INTEGER NOT NULL DEFAULT 2,
                    units TEXT NOT NULL DEFAULT 'F'
                );

                CREATE TABLE IF NOT EXISTS tracked_markets (
                    chat_id INTEGER NOT NULL,
                    market_id TEXT NOT NULL,
                    city TEXT,
                    target_date TEXT,
                    question TEXT,
                    PRIMARY KEY (chat_id, market_id)
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    city TEXT NOT NULL,
                    threshold_f REAL NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'cross',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS last_positions (
                    chat_id INTEGER NOT NULL,
                    city TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, city, target_date)
                );
                """
            )
            await db.commit()

    async def ensure_user(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO users(chat_id, created_at) VALUES (?, ?)",
                (chat_id, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def user_settings(self, chat_id: int) -> dict[str, Any]:
        await self.ensure_user(chat_id)
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))).fetchone()
            return dict(row)

    async def track_market(self, chat_id: int, market_id: str, city: str | None, target_date: str | None, question: str) -> None:
        await self.ensure_user(chat_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO tracked_markets(chat_id, market_id, city, target_date, question)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, market_id, city, target_date, question),
            )
            await db.commit()

    async def add_alert(self, chat_id: int, city: str, threshold_f: float) -> None:
        await self.ensure_user(chat_id)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO alerts(chat_id, city, threshold_f, created_at) VALUES (?, ?, ?, ?)",
                (chat_id, city, threshold_f, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def active_alerts(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("SELECT * FROM alerts WHERE active = 1")).fetchall()
            return [dict(row) for row in rows]

    async def subscribers(self) -> list[int]:
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute("SELECT chat_id FROM users")).fetchall()
            return [int(row[0]) for row in rows]

    async def last_position(self, chat_id: int, city: str, target_date: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            row = await (
                await db.execute(
                    "SELECT bucket FROM last_positions WHERE chat_id = ? AND city = ? AND target_date = ?",
                    (chat_id, city, target_date),
                )
            ).fetchone()
            return row[0] if row else None

    async def set_last_position(self, chat_id: int, city: str, target_date: str, bucket: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO last_positions(chat_id, city, target_date, bucket, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, city, target_date, bucket, datetime.utcnow().isoformat()),
            )
            await db.commit()
