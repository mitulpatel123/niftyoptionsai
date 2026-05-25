import csv
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

from config import settings
from config.settings import SYMBOLS, UNDERLYINGS
from db.db_config import get_connection
from utils.dhan_api import credentials_available, get_url, post_json
from utils.logger import get_logger


class MetadataLoader:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def fetchexpirylist(self):
        if not credentials_available():
            self.logger.warning("Dhan credentials missing; skipping expiry API fetch")
            return []

        rows = []
        for symbol in SYMBOLS:
            underlying = UNDERLYINGS[symbol]
            payload = {
                "UnderlyingScrip": int(underlying["security_id"]),
                "UnderlyingSeg": underlying["exchange_segment"],
            }
            response = post_json(settings.DHAN_EXPIRY_LIST_PATH, payload)
            for expiry in response.get("data") or []:
                rows.append({"symbol": symbol, "expiry_date": expiry})
        return rows

    def fetchinstrumentmetadata(self):
        # FIX #5: Cache instrument metadata locally to avoid re-downloading on every run
        cache_file = Path("/tmp/dhan_instrument_master.csv")
        
        # Use cached file if it exists and is less than 24 hours old
        if cache_file.exists():
            try:
                file_mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
                age = datetime.now() - file_mtime
                if age < timedelta(hours=24):
                    self.logger.info(f"Using cached instrument master (age: {age.total_seconds()/3600:.1f}h)")
                    with open(cache_file, 'r') as f:
                        csv_text = f.read()
                    return self._parse_csv_text(csv_text)
            except Exception as e:
                self.logger.debug(f"Failed to use cache: {e}, fetching fresh data")
        
        # Download fresh metadata from Dhan
        self.logger.info("Downloading fresh instrument master from Dhan")
        response = get_url(settings.DHAN_INSTRUMENT_MASTER_URL)
        
        # Cache for next run
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(response.text)
            self.logger.info(f"Cached instrument master to {cache_file}")
        except Exception as e:
            self.logger.warning(f"Failed to cache instrument master: {e}")
        
        return self._parse_csv_text(response.text)
    
    def _parse_csv_text(self, csv_text):
        """Parse CSV text and return parsed instruments"""
        reader = csv.DictReader(StringIO(csv_text))
        rows = []

        for item in reader:
            if item.get("EXCH_ID") != "NSE":
                continue
            if item.get("SEGMENT") != "D":
                continue
            if item.get("INSTRUMENT") != "OPTIDX":
                continue
            if item.get("UNDERLYING_SYMBOL") not in SYMBOLS:
                continue

            parsed = self._parse_instrument_row(item)
            if parsed:
                rows.append(parsed)

        return rows

    def _parse_instrument_row(self, item):
        try:
            strike = int(float(item["STRIKE_PRICE"]))
            security_id = int(item["SECURITY_ID"])
            lot_size = int(float(item["LOT_SIZE"]))
        except (KeyError, TypeError, ValueError):
            self.logger.debug("Skipping malformed instrument row: %s", item)
            return None

        return {
            "security_id": security_id,
            "symbol": item["UNDERLYING_SYMBOL"],
            "expiry": item.get("SM_EXPIRY_DATE") or None,
            "strike": strike,
            "option_type": item.get("OPTION_TYPE") or None,
            "lot_size": lot_size,
        }

    def insertintodb(self, expiries, instruments):
        with get_connection() as conn:
            with conn.cursor() as cur:
                if expiries:
                    cur.executemany(
                        """
                        INSERT INTO expiry_calendar (symbol, expiry_date)
                        VALUES (%(symbol)s, %(expiry_date)s)
                        ON CONFLICT (symbol, expiry_date) DO NOTHING
                        """,
                        expiries,
                    )

                if instruments:
                    cur.executemany(
                        """
                        INSERT INTO instrument_metadata (
                            security_id, symbol, expiry, strike, option_type, lot_size
                        )
                        VALUES (
                            %(security_id)s, %(symbol)s, %(expiry)s, %(strike)s,
                            %(option_type)s, %(lot_size)s
                        )
                        ON CONFLICT (security_id) DO UPDATE SET
                            symbol = EXCLUDED.symbol,
                            expiry = EXCLUDED.expiry,
                            strike = EXCLUDED.strike,
                            option_type = EXCLUDED.option_type,
                            lot_size = EXCLUDED.lot_size
                        """,
                        instruments,
                    )

    def run_once(self):
        self.logger.info("Loading metadata")
        expiries = self.fetchexpirylist()
        instruments = self.fetchinstrumentmetadata()
        self.insertintodb(expiries, instruments)
        self.logger.info(
            "Loaded %s expiries and %s instruments",
            len(expiries),
            len(instruments),
        )
