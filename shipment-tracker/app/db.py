from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

_settings = get_settings()

if _settings.database_url.startswith("sqlite"):
    _path = _settings.database_url.split("///", 1)[-1]
    if _path and _path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(_path)), exist_ok=True)

engine = create_async_engine(_settings.database_url, pool_pre_ping=True)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# Columns added after the first release: (table, column, SQL type + default). create_all() only
# creates missing tables, so existing databases get these via ALTER TABLE on startup.
_ADDED_COLUMNS = [
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("users", "password_changed_at", "TIMESTAMP NULL"),
    ("users", "whatsapp_alerts", "BOOLEAN NOT NULL DEFAULT TRUE"),
]


def _add_missing_columns(sync_conn) -> None:
    insp = inspect(sync_conn)
    for table, column, ddl in _ADDED_COLUMNS:
        if table in insp.get_table_names() and column not in {c["name"] for c in insp.get_columns(table)}:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


async def get_session():
    async with SessionLocal() as session:
        yield session


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything stored here is UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
