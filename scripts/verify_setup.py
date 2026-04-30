import base64
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from db.db_config import get_connection
from ingest.optionchainingest import OptionChainIngestor
from utils.dhan_api import credentials_available, post_json
from utils.time_utils import IST


def print_result(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"{status}: {name}{suffix}")


def decode_jwt_payload(token):
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception:
        return {}


def previous_market_window():
    value = datetime.now(IST)
    if value.time() <= time(9, 15):
        value -= timedelta(days=1)

    while value.weekday() >= 5:
        value -= timedelta(days=1)

    start = value.replace(hour=9, minute=15, second=0, microsecond=0)
    end = value.replace(hour=15, minute=30, second=0, microsecond=0)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def check_database():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT extversion
                FROM pg_extension
                WHERE extname = 'timescaledb'
                """
            )
            timescaledb = cur.fetchone()

            cur.execute(
                """
                SELECT hypertable_name
                FROM timescaledb_information.hypertables
                ORDER BY hypertable_name
                """
            )
            hypertables = [row["hypertable_name"] for row in cur.fetchall()]

            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM optionchainsnapshot) AS option_chain_rows,
                    (SELECT COUNT(*) FROM index_ohlc) AS index_ohlc_rows,
                    (SELECT COUNT(*) FROM option_ohlc) AS option_ohlc_rows,
                    (SELECT COUNT(*) FROM market_depth) AS market_depth_rows,
                    (SELECT COUNT(*) FROM instrument_metadata) AS instrument_rows,
                    (SELECT COUNT(*) FROM expiry_calendar) AS expiry_rows
                """
            )
            counts = cur.fetchone()

    print_result(
        "TimescaleDB extension",
        bool(timescaledb),
        f"version {timescaledb['extversion']}" if timescaledb else "",
    )
    print_result("Hypertables", len(hypertables) >= 9, f"{len(hypertables)} found")
    print_result("Current row counts", True, dict(counts))


def check_credentials():
    ok = credentials_available()
    print_result("Dhan credentials present", ok)
    if not ok:
        return False

    payload = decode_jwt_payload(settings.DHAN_ACCESS_TOKEN)
    if not payload:
        print_result(
            "Dhan access token format",
            False,
            "JWT payload could not be decoded; generate/copy a fresh access token",
        )
        return False

    print_result("Dhan access token format", True)
    exp = payload.get("exp")
    client_id = payload.get("dhanClientId")
    if exp:
        expiry = datetime.fromtimestamp(int(exp), tz=timezone.utc).astimezone(IST)
        print_result("Dhan access token expiry", expiry > datetime.now(IST), expiry.isoformat())
    if client_id:
        print_result(
            "Token client id matches env",
            str(client_id) == str(settings.DHAN_CLIENT_ID),
            f"client_id={client_id}",
        )
    return True


def check_expiry_api():
    for symbol, underlying in settings.UNDERLYINGS.items():
        try:
            response = post_json(
                settings.DHAN_EXPIRY_LIST_PATH,
                {
                    "UnderlyingScrip": int(underlying["security_id"]),
                    "UnderlyingSeg": underlying["exchange_segment"],
                },
            )
            expiries = response.get("data") or []
            print_result(f"{symbol} expiry API", bool(expiries), f"{len(expiries)} expiries")
        except Exception as exc:
            print_result(f"{symbol} expiry API", False, str(exc))


def check_option_chain_api():
    try:
        ingestor = OptionChainIngestor(symbols=("NIFTY",))
        payload = ingestor.fetchoptionchain()
        rows = ingestor.parseoptionchain(payload)
        print_result("NIFTY option chain API parse", bool(rows), f"{len(rows)} strike rows")
    except Exception as exc:
        print_result("NIFTY option chain API parse", False, str(exc))


def check_intraday_api():
    from_date, to_date = previous_market_window()
    underlying = settings.UNDERLYINGS["NIFTY"]
    try:
        response = post_json(
            settings.DHAN_INTRADAY_PATH,
            {
                "securityId": str(underlying["security_id"]),
                "exchangeSegment": underlying["exchange_segment"],
                "instrument": underlying["instrument"],
                "interval": "1",
                "oi": False,
                "fromDate": from_date,
                "toDate": to_date,
            },
        )
        timestamps = response.get("timestamp") or []
        print_result(
            "NIFTY intraday chart API",
            bool(timestamps),
            f"{len(timestamps)} candles from {from_date} to {to_date}",
        )
    except Exception as exc:
        print_result("NIFTY intraday chart API", False, str(exc))


def main():
    check_database()
    if not check_credentials():
        return

    check_expiry_api()
    check_option_chain_api()
    check_intraday_api()


if __name__ == "__main__":
    main()
