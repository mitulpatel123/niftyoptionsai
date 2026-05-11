from datetime import date, datetime, time, timezone
from datetime import timedelta
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)
NSE_TRADING_HOLIDAYS_2026 = {
    date(2026, 1, 26),
    date(2026, 3, 3),
    date(2026, 3, 26),
    date(2026, 3, 31),
    date(2026, 4, 3),
    date(2026, 4, 14),
    date(2026, 5, 1),
    date(2026, 5, 28),
    date(2026, 6, 26),
    date(2026, 9, 14),
    date(2026, 10, 2),
    date(2026, 10, 20),
    date(2026, 11, 10),
    date(2026, 11, 24),
    date(2026, 12, 25),
}


def getcurrentist():
    return datetime.now(timezone.utc).astimezone(IST)


def roundtominute(value=None):
    value = value or getcurrentist()
    return value.replace(second=0, microsecond=0)


def is_trading_holiday(value=None):
    value = value or getcurrentist()
    return value.astimezone(IST).date() in NSE_TRADING_HOLIDAYS_2026


def is_market_day(value=None):
    value = value or getcurrentist()
    value = value.astimezone(IST)
    return value.weekday() < 5 and not is_trading_holiday(value)


def market_open(value=None):
    value = value or getcurrentist()
    value = value.astimezone(IST)
    return is_market_day(value) and value.time() >= MARKET_OPEN_TIME


def market_close(value=None):
    value = value or getcurrentist()
    value = value.astimezone(IST)
    return not is_market_day(value) or value.time() >= MARKET_CLOSE_TIME


def intraday_window(minutes=5):
    end = getcurrentist()
    start = end - timedelta(minutes=minutes)
    return format_dhan_datetime(start), format_dhan_datetime(end)


def format_dhan_datetime(value):
    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


def from_epoch_seconds(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone(IST)
