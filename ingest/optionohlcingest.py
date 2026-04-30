import time

from config import settings
from config.settings import (
    AUTO_SELECT_ATM_CONTRACTS,
    OPTION_OHLC_ATM_STRIKES_EACH_SIDE,
    OPTION_OHLC_INTERVAL_SECONDS,
    OPTION_OHLC_SECURITY_IDS,
    SYMBOLS,
)
from db.db_config import get_connection
from ingest.contract_selector import ATMContractSelector
from utils.dhan_api import DhanHTTPError, post_json
from utils.logger import get_logger
from utils.time_utils import from_epoch_seconds, intraday_window


class OptionOHLCIngestor:
    def __init__(self, symbols=SYMBOLS, interval_seconds=OPTION_OHLC_INTERVAL_SECONDS):
        self.symbols = symbols
        self.interval_seconds = interval_seconds
        self.logger = get_logger(self.__class__.__name__)
        self.contract_selector = ATMContractSelector(
            symbols=symbols,
            strikes_each_side=OPTION_OHLC_ATM_STRIKES_EACH_SIDE,
        )
        self.chart_backoff_until = 0

    def _load_contracts(self):
        if AUTO_SELECT_ATM_CONTRACTS and not OPTION_OHLC_SECURITY_IDS:
            return self.contract_selector.get_contracts()

        if not OPTION_OHLC_SECURITY_IDS:
            self.logger.info(
                "OPTION_OHLC_SECURITY_IDS is empty and auto selection is disabled; skipping option OHLC fetch"
            )
            return []

        placeholders = ", ".join(["%s"] * len(OPTION_OHLC_SECURITY_IDS))
        query = f"""
            SELECT security_id, symbol, expiry, strike, option_type
            FROM instrument_metadata
            WHERE security_id IN ({placeholders})
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, OPTION_OHLC_SECURITY_IDS)
                rows = cur.fetchall()

        found_ids = {str(row["security_id"]) for row in rows}
        missing_ids = sorted(set(OPTION_OHLC_SECURITY_IDS) - found_ids)
        for security_id in missing_ids:
            self.logger.warning(
                "Security ID %s was not found in instrument_metadata", security_id
            )

        return rows

    def fetchoptionohlc(self, security_id=None):
        if self._in_chart_backoff():
            return []

        from_date, to_date = intraday_window(minutes=5)
        contracts = self._load_contracts()
        if security_id:
            contracts = [row for row in contracts if str(row["security_id"]) == str(security_id)]

        rows = []
        for contract in contracts:
            payload = {
                "securityId": str(contract["security_id"]),
                "exchangeSegment": "NSE_FNO",
                "instrument": "OPTIDX",
                "interval": "1",
                "oi": False,
                "fromDate": from_date,
                "toDate": to_date,
            }
            try:
                response = post_json(settings.DHAN_INTRADAY_PATH, payload)
            except DhanHTTPError as exc:
                self._handle_chart_error(exc)
                return rows
            rows.extend(self._parse_response(contract, response))

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
                "Dhan intraday chart API returned HTTP %s. Pausing option OHLC for %s seconds. Body: %s",
                exc.status_code,
                backoff_seconds,
                (exc.body or "")[:300],
            )
            return
        raise exc

    def _parse_response(self, contract, response):
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
                    "symbol": contract["symbol"],
                    "expiry": contract["expiry"],
                    "strike": contract["strike"],
                    "option_type": contract["option_type"],
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
            INSERT INTO option_ohlc (
                time, symbol, expiry, strike, option_type,
                open, high, low, close, volume
            )
            SELECT
                %(time)s, %(symbol)s, %(expiry)s, %(strike)s, %(option_type)s,
                %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s
            WHERE NOT EXISTS (
                SELECT 1
                FROM option_ohlc
                WHERE time = %(time)s
                  AND symbol = %(symbol)s
                  AND expiry = %(expiry)s
                  AND strike = %(strike)s
                  AND option_type = %(option_type)s
            )
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, rows)

    def run(self):
        self.logger.info("Starting option OHLC ingestor")
        while True:
            try:
                rows = self.fetchoptionohlc()
                self.insertintodb(rows)
                self.logger.info("Inserted %s option OHLC rows", len(rows))
            except DhanHTTPError as exc:
                self.logger.error("Option OHLC Dhan API error: %s", exc)
            except Exception:
                self.logger.exception("Option OHLC ingestion failed")
            time.sleep(self.interval_seconds)
