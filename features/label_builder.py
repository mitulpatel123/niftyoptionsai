from datetime import date, datetime, time
import json

import pandas as pd

from db.db_config import get_connection
from utils.logger import get_logger
from utils.time_utils import IST


class LabelBuilder:
    def __init__(self, lookahead_minutes=15, risk_reward_ratio=2.0, transaction_cost_points=2.0, min_stop_points=5.0):
        self.lookahead_minutes = lookahead_minutes
        self.risk_reward_ratio = risk_reward_ratio
        self.transaction_cost_points = transaction_cost_points
        self.min_stop_points = min_stop_points
        self.logger = get_logger(self.__class__.__name__)

    def build_labels_for_features(self, features_df):
        if features_df.empty:
            return pd.DataFrame()

        labels = []
        for symbol in sorted(features_df["symbol"].dropna().unique()):
            symbol_features = features_df[features_df["symbol"] == symbol]
            start_at = symbol_features["time"].min()
            end_at = symbol_features["time"].max() + pd.Timedelta(minutes=self.lookahead_minutes + 1)
            option_df = self._query_option_ohlc(symbol, start_at, end_at)

            for _, feature_row in symbol_features.iterrows():
                labels.append(self._label_row(feature_row, option_df))

        result = pd.DataFrame(labels)
        self.logger.info("Built %s labels", len(result))
        return result

    def build_labels_for_date(self, target_date=None, symbols=("NIFTY", "BANKNIFTY")):
        target_date = self._parse_date(target_date)
        start_at, end_at = self._date_window(target_date)
        rows = []
        for symbol in symbols:
            rows.extend(self._feature_keys_from_store(symbol, start_at, end_at))
        if not rows:
            self.logger.warning("No feature_store keys found for %s", target_date)
            return pd.DataFrame()
        return self.build_labels_for_features(pd.DataFrame(rows))

    def _label_row(self, feature_row, option_df):
        timestamp = feature_row["time"]
        future = option_df[
            (option_df["expiry"] == feature_row["expiry"])
            & (option_df["strike"] == feature_row["strike"])
            & (option_df["option_type"] == feature_row["option_type"])
            & (option_df["time"] >= timestamp)
            & (option_df["time"] <= timestamp + pd.Timedelta(minutes=self.lookahead_minutes))
        ].sort_values("time")

        label = 0
        max_future_move_up = None
        max_future_move_down = None
        price_at_t = None
        
        features_json = feature_row.get("features", {})
        if isinstance(features_json, str):
            try:
                features_json = json.loads(features_json)
            except json.JSONDecodeError:
                features_json = {}
                
        range_15m = features_json.get("atm_option_range_15m")
        if range_15m is None or pd.isna(range_15m) or range_15m < 5.0:
            range_15m = 10.0
            
        stop_points = max(self.min_stop_points, float(range_15m) * 0.5)
        profit_points = stop_points * self.risk_reward_ratio

        if not future.empty:
            price_at_t = float(future.iloc[0]["close"])
            future_moves = future["close"].astype(float) - price_at_t
            max_future_move_up = float(future_moves.max())
            max_future_move_down = float(future_moves.min())
            
            target_gross_move = profit_points  # Target is pure profit points. Transaction cost is applied to final P&L.
            hit_target = False
            hit_stop = False
            
            for future_price in future["close"]:
                move = float(future_price) - price_at_t
                if move <= -stop_points:
                    hit_stop = True
                    break
                if move >= target_gross_move:
                    hit_target = True
                    break
                    
            label = int(hit_target and not hit_stop)

        return {
            "time": timestamp,
            "symbol": feature_row["symbol"],
            "expiry": feature_row["expiry"],
            "strike": int(feature_row["strike"]),
            "option_type": feature_row["option_type"],
            "label": label,
            "price_at_t": price_at_t,
            "max_future_move_up": max_future_move_up,
            "max_future_move_down": max_future_move_down,
        }

    def _query_option_ohlc(self, symbol, start_at, end_at):
        query = """
            SELECT time, symbol, expiry, strike, option_type, close
            FROM option_ohlc
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time
        """
        with get_connection(cursor_factory=None) as conn:
            frame = pd.read_sql_query(query, conn, params=(symbol, start_at, end_at))
        if "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"])
        return frame

    def _feature_keys_from_store(self, symbol, start_at, end_at):
        query = """
            SELECT time, symbol, expiry, strike, option_type, features
            FROM feature_store
            WHERE symbol = %s AND time >= %s AND time < %s
            ORDER BY time
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (symbol, start_at, end_at))
                return [dict(row) for row in cur.fetchall()]

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
