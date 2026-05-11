import signal
import threading
import time

from db.db_config import get_connection
from ingest.indexohlcingest import IndexOHLCIngestor
from ingest.metadata_loader import MetadataLoader
from ingest.optionchainingest import OptionChainIngestor
from ingest.optionohlcingest import OptionOHLCIngestor
from ingest.websocket_listener import WebsocketListener
from utils.dhan_api import DhanCredentialsExpired, DhanCredentialsMissing, validate_credentials_or_raise
from utils.logger import get_logger
from utils.time_utils import getcurrentist, is_market_day, is_trading_holiday


LOGGER = get_logger("runallingestors")
STOP_REQUESTED = False


def _handle_stop(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    LOGGER.info("Stop requested")


def _start_thread(name, target):
    thread = threading.Thread(name=name, target=target, daemon=True)
    thread.start()
    return thread


def _wait_for_option_chain_snapshot(timeout_seconds=45):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM optionchainsnapshot
                    WHERE time >= now() - INTERVAL '5 minutes'
                    """
                )
                if cur.fetchone()["count"] > 0:
                    LOGGER.info("Fresh option chain snapshot is available")
                    return True
        time.sleep(3)
    LOGGER.warning("No option chain snapshot found after %s seconds", timeout_seconds)
    return False


def main():
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    now = getcurrentist()
    if not is_market_day(now):
        if is_trading_holiday(now):
            LOGGER.warning("Today is an NSE trading holiday in IST; ingestion services will not be started")
        else:
            LOGGER.warning("Today is not a weekday in IST; ingestion services will not be started")
        return

    try:
        validate_credentials_or_raise()
    except (DhanCredentialsMissing, DhanCredentialsExpired) as exc:
        LOGGER.error("%s", exc)
        return

    MetadataLoader().run_once()

    threads = [_start_thread("option-chain", OptionChainIngestor().run)]
    _wait_for_option_chain_snapshot()

    services = [
        ("index-ohlc", IndexOHLCIngestor().run),
        ("option-ohlc", OptionOHLCIngestor().run),
        ("websocket", WebsocketListener().run),
    ]

    threads.extend(_start_thread(name, target) for name, target in services)
    LOGGER.info("Started %s ingestion services", len(threads))

    while not STOP_REQUESTED:
        time.sleep(1)

    LOGGER.info("Ingestion runner stopped")


if __name__ == "__main__":
    main()
