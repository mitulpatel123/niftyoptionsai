import time

from config import settings
from config.settings import OHLC_INTERVAL_SECONDS, SYMBOLS, UNDERLYINGS
from db.db_config import get_connection
from utils.dhan_api import DhanHTTPError, post_json
from utils.logger import get_logger
from utils.time_utils import from_epoch_seconds, intraday_window


class IndexOHLCIngestor:
    def __init__(self, symbols=SYMBOLS, interval_seconds=OHLC_INTERVAL_SECONDS):
        self.symbols = symbols
        self.interval_seconds = interval_seconds
        self.logger = get_logger(self.__class__.__name__)
        self.chart_backoff_until = 0

    def fetchindexohlc(self, symbol=None):
        if self._in_chart_backoff():
            return []

        symbols = (symbol,) if symbol else self.symbols
        rows = []
        from_date, to_date = intraday_window(minutes=5)

        for item in symbols:
            underlying = UNDERLYINGS[item]
            payload = {
                "securityId": str(underlying["security_id"]),
                "exchangeSegment": underlying["exchange_segment"],
                "instrument": underlying["instrument"],
                "interval": "1",
                "oi": False,
                "fromDate": from_date,
                "toDate": to_date,
            }
            try:
                response = post_json(settings.DHAN_INTRADAY_PATH, payload)
                time.sleep(0.25)  # Enforce 4 req/sec (Dhan limit is 5/sec)
            except DhanHTTPError as exc:
                self._handle_chart_error(exc)
                return rows
            rows.extend(self._parse_response(item, response))

        return rows

    def _in_chart_backoff(self):
        if time.time() < self.chart_backoff_until:
            return True
        return False

    def _handle_chart_error(self, exc):
        if exc.status_code in (401, 429):
            backoff_seconds = 300 if exc.status_code == 401 else 120
            self.chart_backoff_until = time.time() + backoff_seconds
            self.logger.error(
                "Dhan intraday chart API returned HTTP %s. Pausing index OHLC for %s seconds. Body: %s",
                exc.status_code,
                backoff_seconds,
                (exc.body or "")[:300],
            )
            return
        raise exc

    def _parse_response(self, symbol, response):
        timestamps = response.get("timestamp") or []
        opens = response.get("open") or []
        highs = response.get("high") or []
        lows = response.get("low") or []
        closes = response.get("close") or []
        volumes = response.get("volume") or []

        rows = []
        for index, timestamp in enumerate(timestamps):
            rows.append(
                {
                    "time": from_epoch_seconds(timestamp),
                    "symbol": symbol,
                    "open": opens[index] if index < len(opens) else None,
                    "high": highs[index] if index < len(highs) else None,
                    "low": lows[index] if index < len(lows) else None,
                    "close": closes[index] if index < len(closes) else None,
                    "volume": volumes[index] if index < len(volumes) else None,
                }
            )
        return rows

    def insertintodb(self, rows):
        if not rows:
            return

        query = """
            INSERT INTO index_ohlc (time, symbol, open, high, low, close, volume)
            SELECT
                %(time)s, %(symbol)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s
            WHERE NOT EXISTS (
                SELECT 1
                FROM index_ohlc
                WHERE time = %(time)s
                  AND symbol = %(symbol)s
            )
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, rows)

    def run(self):
        self.logger.info("Starting index OHLC ingestor")
        while True:
            try:
                rows = self.fetchindexohlc()
                self.insertintodb(rows)
                self.logger.info("Inserted %s index OHLC rows", len(rows))
            except DhanHTTPError as exc:
                self.logger.error("Index OHLC Dhan API error: %s", exc)
            except Exception:
                self.logger.exception("Index OHLC ingestion failed")
            time.sleep(self.interval_seconds)
