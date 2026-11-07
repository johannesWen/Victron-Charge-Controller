"""Explicit UTC intervals for legacy hourly regression fixtures."""

from datetime import datetime, timedelta, timezone


def utc_slot(date: str, hour: int, minute: int = 0, minutes: int = 60):
    start = datetime.fromisoformat(date).replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    return start, start + timedelta(minutes=minutes)


def stored_slot(date: str, hour: int):
    return [value.isoformat() for value in utc_slot(date, hour)]


def public_slot(date: str, hour: int):
    start, end = stored_slot(date, hour)
    return {"date": date, "hour": hour, "minute": 0, "start_time": start, "end_time": end}


def public_day(date: str, prices=None):
    prices = prices or {}
    return [public_slot(date, hour) | ({"price": prices[hour]} if hour in prices else {}) for hour in range(24)]
