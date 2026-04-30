from datetime import datetime, time, timezone
from datetime import timedelta
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)


def getcurrentist():
    return datetime.now(timezone.utc).astimezone(IST)


def roundtominute(value=None):
    value = value or getcurrentist()
    return value.replace(second=0, microsecond=0)


def market_open(value=None):
    value = value or getcurrentist()
    return value.weekday() < 5 and value.time() >= MARKET_OPEN_TIME


def market_close(value=None):
    value = value or getcurrentist()
    return value.weekday() >= 5 or value.time() >= MARKET_CLOSE_TIME


def intraday_window(minutes=5):
    end = getcurrentist()
    start = end - timedelta(minutes=minutes)
    return format_dhan_datetime(start), format_dhan_datetime(end)


def format_dhan_datetime(value):
    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def from_epoch_seconds(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone(IST)
