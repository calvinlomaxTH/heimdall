from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_TICKERS = (
    "UNH",
    "CVS",
    "ELV",
    "HUM",
    "CI",
    "CNC",
    "MOH",
    "HCA",
    "THC",
    "UHS",
    "PFE",
    "JNJ",
    "MRK",
    "ABBV",
    "MDT",
    "ISRG",
)


@dataclass(frozen=True)
class Settings:
    database_path: str
    refresh_minutes: int
    lookback_hours: int
    tickers: tuple[str, ...]


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_settings() -> Settings:
    tickers = tuple(
        ticker.strip().upper()
        for ticker in os.getenv("HEALTHCARE_TICKERS", ",".join(DEFAULT_TICKERS)).split(",")
        if ticker.strip()
    )
    return Settings(
        database_path=os.getenv("DATABASE_PATH", "./heimdall.db"),
        refresh_minutes=max(5, _int_env("NEWS_REFRESH_MINUTES", 60)),
        lookback_hours=max(1, _int_env("NEWS_LOOKBACK_HOURS", 72)),
        tickers=tickers or DEFAULT_TICKERS,
    )
