import time

from config.settings import (
    AUTO_ATM_STRIKES_EACH_SIDE,
    AUTO_CONTRACT_REFRESH_SECONDS,
    SYMBOLS,
)
from db.db_config import get_connection
from utils.logger import get_logger


class ATMContractSelector:
    def __init__(
        self,
        symbols=SYMBOLS,
        strikes_each_side=AUTO_ATM_STRIKES_EACH_SIDE,
        refresh_seconds=AUTO_CONTRACT_REFRESH_SECONDS,
    ):
        self.symbols = tuple(symbols)
        self.strikes_each_side = strikes_each_side
        self.refresh_seconds = refresh_seconds
        self.logger = get_logger(self.__class__.__name__)
        self._cache = []
        self._last_refresh = 0

    def get_contracts(self, force=False):
        now = time.time()
        if not force and self._cache and now - self._last_refresh < self.refresh_seconds:
            return self._cache

        contracts = []
        for symbol in self.symbols:
            contracts.extend(self._contracts_for_symbol(symbol))

        self._cache = contracts
        self._last_refresh = now
        if contracts:
            self.logger.info("Auto-selected %s ATM option contracts", len(contracts))
        else:
            self.logger.warning(
                "No ATM contracts selected yet. Waiting for option chain snapshots."
            )
        return contracts

    def websocket_subscriptions(self, force=False):
        return [
            {"exchange_segment": "NSE_FNO", "security_id": contract["security_id"]}
            for contract in self.get_contracts(force=force)
        ]

    def _contracts_for_symbol(self, symbol):
        latest_snapshot = self._latest_snapshot_time(symbol)
        if not latest_snapshot:
            return []

        rows = self._snapshot_rows(symbol, latest_snapshot)
        if not rows:
            return []

        index_close = self._latest_index_close(symbol)
        atm_strike = self._atm_strike(rows, index_close=index_close)
        if atm_strike is None:
            return []

        strikes = sorted({int(row["strike"]) for row in rows})
        atm_index = min(range(len(strikes)), key=lambda idx: abs(strikes[idx] - atm_strike))
        selected_strikes = set(
            strikes[
                max(0, atm_index - self.strikes_each_side) : atm_index + self.strikes_each_side + 1
            ]
        )

        contracts = []
        for row in rows:
            if int(row["strike"]) not in selected_strikes:
                continue
            for option_type, column in (("CE", "cesecurityid"), ("PE", "pesecurityid")):
                security_id = row.get(column)
                if security_id is None:
                    continue
                contracts.append(
                    {
                        "security_id": int(security_id),
                        "symbol": row["underlying_symbol"],
                        "expiry": row["expiry"],
                        "strike": int(row["strike"]),
                        "option_type": option_type,
                    }
                )
        return contracts

    def _latest_snapshot_time(self, symbol):
        query = """
            SELECT MAX(time) AS latest_time
            FROM optionchainsnapshot
            WHERE underlying_symbol = %s
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (symbol,))
                row = cur.fetchone()
        return row["latest_time"] if row else None

    def _snapshot_rows(self, symbol, snapshot_time):
        query = """
            SELECT
                time, underlying_symbol, expiry, strike,
                ce_ltp, pe_ltp, ce_oi, pe_oi, cesecurityid, pesecurityid
            FROM optionchainsnapshot
            WHERE underlying_symbol = %s AND time = %s
            ORDER BY strike
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (symbol, snapshot_time))
                return [dict(row) for row in cur.fetchall()]

    def _latest_index_close(self, symbol):
        query = """
            SELECT close
            FROM index_ohlc
            WHERE symbol = %s
            ORDER BY time DESC
            LIMIT 1
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (symbol,))
                row = cur.fetchone()
        if not row or row["close"] is None:
            return None
        return float(row["close"])

    def _atm_strike(self, rows, index_close=None):
        if index_close is not None:
            return int(
                min(rows, key=lambda row: abs(float(row["strike"]) - index_close))["strike"]
            )

        best_row = None
        best_diff = None
        for row in rows:
            ce_ltp = row.get("ce_ltp")
            pe_ltp = row.get("pe_ltp")
            if ce_ltp is None or pe_ltp is None:
                continue
            if float(ce_ltp) <= 0 or float(pe_ltp) <= 0:
                continue
            diff = abs(float(ce_ltp) - float(pe_ltp))
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_row = row

        if best_row:
            return int(best_row["strike"])

        liquid_rows = sorted(
            rows,
            key=lambda item: (item.get("ce_oi") or 0) + (item.get("pe_oi") or 0),
            reverse=True,
        )
        return int(liquid_rows[0]["strike"]) if liquid_rows else None
