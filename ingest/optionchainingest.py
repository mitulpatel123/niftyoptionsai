import time

from config import settings
from config.settings import OPTION_CHAIN_INTERVAL_SECONDS, SYMBOLS, UNDERLYINGS
from db.db_config import get_connection
from utils.dhan_api import build_headers, post_json
from utils.logger import get_logger
from utils.time_utils import getcurrentist


class OptionChainIngestor:
    def __init__(self, symbols=SYMBOLS, interval_seconds=OPTION_CHAIN_INTERVAL_SECONDS):
        self.symbols = symbols
        self.interval_seconds = interval_seconds
        self.logger = get_logger(self.__class__.__name__)
        self._expiry_cache = {}

    def build_headers(self):
        return build_headers()

    def _fetch_expiry(self, symbol):
        if symbol in self._expiry_cache:
            return self._expiry_cache[symbol]

        underlying = UNDERLYINGS[symbol]
        payload = {
            "UnderlyingScrip": int(underlying["security_id"]),
            "UnderlyingSeg": underlying["exchange_segment"],
        }
        response = post_json(settings.DHAN_EXPIRY_LIST_PATH, payload)
        expiries = response.get("data") or []
        if not expiries:
            raise RuntimeError(f"No expiries returned by Dhan for {symbol}")

        self._expiry_cache[symbol] = expiries[0]
        return self._expiry_cache[symbol]

    def fetchoptionchain(self):
        payloads = []
        for symbol in self.symbols:
            underlying = UNDERLYINGS[symbol]
            expiry = self._fetch_expiry(symbol)
            request_payload = {
                "UnderlyingScrip": int(underlying["security_id"]),
                "UnderlyingSeg": underlying["exchange_segment"],
                "Expiry": expiry,
            }
            response = post_json(settings.DHAN_OPTION_CHAIN_PATH, request_payload)
            time.sleep(0.5)  # Prevent Dhan HTTP 429 Rate Limiting
            payloads.append(
                {
                    "symbol": symbol,
                    "expiry": expiry,
                    "response": response,
                }
            )
        return payloads

    def parseoptionchain(self, payload):
        rows = []
        received_at = getcurrentist()

        for item in payload:
            symbol = item["symbol"]
            expiry = item["expiry"]
            oc = ((item.get("response") or {}).get("data") or {}).get("oc") or {}

            for strike_text, strike_data in oc.items():
                ce = strike_data.get("ce") or {}
                pe = strike_data.get("pe") or {}
                ce_greeks = ce.get("greeks") or {}
                pe_greeks = pe.get("greeks") or {}

                rows.append(
                    {
                        "time": received_at,
                        "underlying_symbol": symbol,
                        "expiry": expiry,
                        "strike": int(float(strike_text)),
                        "ce_ltp": ce.get("last_price"),
                        "pe_ltp": pe.get("last_price"),
                        "ce_oi": ce.get("oi"),
                        "pe_oi": pe.get("oi"),
                        "ceprevoi": ce.get("previous_oi"),
                        "peprevoi": pe.get("previous_oi"),
                        "ce_iv": ce.get("implied_volatility"),
                        "pe_iv": pe.get("implied_volatility"),
                        "ce_delta": ce_greeks.get("delta"),
                        "ce_gamma": ce_greeks.get("gamma"),
                        "ce_theta": ce_greeks.get("theta"),
                        "ce_vega": ce_greeks.get("vega"),
                        "pe_delta": pe_greeks.get("delta"),
                        "pe_gamma": pe_greeks.get("gamma"),
                        "pe_theta": pe_greeks.get("theta"),
                        "pe_vega": pe_greeks.get("vega"),
                        "ce_bid": ce.get("top_bid_price"),
                        "cebidqty": ce.get("top_bid_quantity"),
                        "ce_ask": ce.get("top_ask_price"),
                        "ceaskqty": ce.get("top_ask_quantity"),
                        "pe_bid": pe.get("top_bid_price"),
                        "pebidqty": pe.get("top_bid_quantity"),
                        "pe_ask": pe.get("top_ask_price"),
                        "peaskqty": pe.get("top_ask_quantity"),
                        "ceavgprice": ce.get("average_price"),
                        "peavgprice": pe.get("average_price"),
                        "cesecurityid": ce.get("security_id"),
                        "pesecurityid": pe.get("security_id"),
                    }
                )

        return rows

    def insertintodb(self, rows):
        if not rows:
            return

        query = """
            INSERT INTO optionchainsnapshot (
                time, underlying_symbol, expiry, strike,
                ce_ltp, pe_ltp, ce_oi, pe_oi, ceprevoi, peprevoi,
                ce_iv, pe_iv, ce_delta, ce_gamma, ce_theta, ce_vega,
                pe_delta, pe_gamma, pe_theta, pe_vega,
                ce_bid, cebidqty, ce_ask, ceaskqty,
                pe_bid, pebidqty, pe_ask, peaskqty,
                ceavgprice, peavgprice, cesecurityid, pesecurityid
            )
            VALUES (
                %(time)s, %(underlying_symbol)s, %(expiry)s, %(strike)s,
                %(ce_ltp)s, %(pe_ltp)s, %(ce_oi)s, %(pe_oi)s, %(ceprevoi)s, %(peprevoi)s,
                %(ce_iv)s, %(pe_iv)s, %(ce_delta)s, %(ce_gamma)s, %(ce_theta)s, %(ce_vega)s,
                %(pe_delta)s, %(pe_gamma)s, %(pe_theta)s, %(pe_vega)s,
                %(ce_bid)s, %(cebidqty)s, %(ce_ask)s, %(ceaskqty)s,
                %(pe_bid)s, %(pebidqty)s, %(pe_ask)s, %(peaskqty)s,
                %(ceavgprice)s, %(peavgprice)s, %(cesecurityid)s, %(pesecurityid)s
            )
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(query, rows)

    def run(self):
        self.logger.info("Starting option chain ingestor")
        while True:
            try:
                payload = self.fetchoptionchain()
                rows = self.parseoptionchain(payload)
                self.insertintodb(rows)
                self.logger.info("Inserted %s option chain rows", len(rows))
            except Exception:
                self.logger.exception("Option chain ingestion failed")
            time.sleep(self.interval_seconds)
