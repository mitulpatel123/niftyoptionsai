from datetime import date, datetime, time

import pandas as pd

from db.db_config import get_connection
from features.feature_definitions import (
    expiry_features,
    index_features,
    microstructure_features,
    option_chain_features,
    option_price_features,
)
from utils.logger import get_logger
from utils.time_utils import IST


class FeatureEngineer:
    def __init__(self, decision_frequency="1min"):
        self.decision_frequency = decision_frequency
        self.logger = get_logger(self.__class__.__name__)

    def build_features_for_date(self, target_date=None, symbols=("NIFTY", "BANKNIFTY")):
        target_date = self._parse_date(target_date)
        frames = []
        for symbol in symbols:
            try:
                frame = self.build_features(target_date, symbol)
                if not frame.empty:
                    frames.append(frame)
            except Exception:
                self.logger.exception("Failed to build features for %s on %s", symbol, target_date)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def build_features(self, target_date, symbol):
        start_at, end_at = self._date_window(target_date)
        self.logger.info("Building features for %s from %s to %s", symbol, start_at, end_at)

        index_df = self._query_index_ohlc(symbol, start_at, end_at)
        chain_df = self._query_option_chain(symbol, start_at, end_at)
        option_df = self._query_option_ohlc(symbol, start_at, end_at)
        depth_df = self._query_market_depth(start_at, end_at)

        if index_df.empty or chain_df.empty:
            self.logger.warning(
                "Skipping %s: index rows=%s chain rows=%s",
                symbol,
                len(index_df),
                len(chain_df),
            )
            return pd.DataFrame()

        decision_times = self._decision_times(index_df)
        rows = []

        for timestamp in decision_times:
            idx_features = index_features(index_df, timestamp)
            index_close = idx_features.get("index_close")
            chain_features, atm_strike, expiry = option_chain_features(
                chain_df, timestamp, index_close=index_close
            )
            if atm_strike is None:
                continue

            for option_type in ("CE", "PE"):
                option_features = option_price_features(
                    option_df, timestamp, atm_strike, option_type
                )
                security_id = self._security_id_for(chain_df, timestamp, atm_strike, option_type)
                depth_features = microstructure_features(depth_df, timestamp, security_id)
                exp_features = expiry_features(timestamp, expiry)

                feature_values = {}
                feature_values.update(idx_features)
                feature_values.update(chain_features)
                feature_values.update(option_features)
                feature_values.update(depth_features)
                feature_values.update(exp_features)
                feature_values["selected_security_id"] = security_id

                rows.append(
                    {
                        "time": timestamp,
                        "symbol": symbol,
                        "expiry": expiry,
                        "strike": int(atm_strike),
                        "option_type": option_type,
                        "features": self._clean_features(feature_values),
                    }
                )

        result = pd.DataFrame(rows)
        self.logger.info("Built %s feature rows for %s", len(result), symbol)
        return result

    def _query_index_ohlc(self, symbol, start_at, end_at):
        query = """
            SELECT time, symbol, open, high, low, close, volume
            FROM index_ohlc
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time
        """
        return self._read_sql(query, (symbol, start_at, end_at))

    def _query_option_chain(self, symbol, start_at, end_at):
        query = """
            SELECT *
            FROM optionchainsnapshot
            WHERE underlying_symbol = %s AND time >= %s AND time < %s
            ORDER BY time, strike
        """
        return self._read_sql(query, (symbol, start_at, end_at))

    def _query_option_ohlc(self, symbol, start_at, end_at):
        query = """
            SELECT time, symbol, expiry, strike, option_type, open, high, low, close, volume
            FROM option_ohlc
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time, strike, option_type
        """
        return self._read_sql(query, (symbol, start_at, end_at))

    def _query_market_depth(self, start_at, end_at):
        query = """
            SELECT time, security_id, bidprice1, bidqty1, askprice1, askqty1
            FROM market_depth
            WHERE time >= %s AND time < %s
            ORDER BY time
        """
        return self._read_sql(query, (start_at, end_at))

    def _read_sql(self, query, params):
        with get_connection(cursor_factory=None) as conn:
            frame = pd.read_sql_query(query, conn, params=params)
        if "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"])
        return frame

    def _decision_times(self, index_df):
        frame = index_df.sort_values("time").drop_duplicates("time")
        if frame.empty:
            return []
        return list(frame.set_index("time").resample(self.decision_frequency).last().dropna(how="all").index)

    def _security_id_for(self, chain_df, timestamp, strike, option_type):
        snapshot = chain_df[chain_df["time"] <= timestamp]
        if snapshot.empty:
            return None
        latest_time = snapshot["time"].max()
        row = snapshot[(snapshot["time"] == latest_time) & (snapshot["strike"] == strike)]
        if row.empty:
            return None
        column = "cesecurityid" if option_type == "CE" else "pesecurityid"
        value = row.iloc[0].get(column)
        if value is None or pd.isna(value):
            return None
        return int(value)

    def _clean_features(self, values):
        clean = {}
        for key, value in values.items():
            if value is None or pd.isna(value):
                clean[key] = None
            elif hasattr(value, "item"):
                clean[key] = value.item()
            else:
                clean[key] = value
        return clean

    def _parse_date(self, value):
        if value is None:
            return datetime.now(IST).date()
        if isinstance(value, date):
            return value
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _date_window(self, target_date):
        start_at = datetime.combine(target_date, time(9, 15), tzinfo=IST)
        end_at = datetime.combine(target_date, time(15, 31), tzinfo=IST)
        return start_at, end_at
