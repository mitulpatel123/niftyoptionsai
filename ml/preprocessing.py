from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from db.db_config import get_connection
from utils.logger import get_logger
from utils.time_utils import IST


class FeaturePreprocessor:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def load_feature_store(self, start_date=None, end_date=None, days=None, require_labels=True):
        start_at, end_at = self._resolve_window(start_date, end_date, days)
        where = ["time >= %s", "time < %s"]
        params = [start_at, end_at]
        if require_labels:
            where.append("label IS NOT NULL")

        query = f"""
            SELECT time, symbol, expiry, strike, option_type, features, label
            FROM feature_store
            WHERE {' AND '.join(where)}
            ORDER BY time
        """
        with get_connection(cursor_factory=None) as conn:
            frame = pd.read_sql_query(query, conn, params=params)
        if "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"])
        self.logger.info("Loaded %s feature_store rows", len(frame))
        return frame

    def flatten_features(self, frame):
        if frame.empty:
            return pd.DataFrame()

        feature_frame = pd.json_normalize(frame["features"]).replace([np.inf, -np.inf], np.nan)
        metadata = frame[["time", "symbol", "expiry", "strike", "option_type", "label"]].reset_index(drop=True)
        flat = pd.concat([metadata, feature_frame], axis=1)
        return flat

    def prepare_training_data(self, frame):
        flat = self.flatten_features(frame)
        if flat.empty:
            return pd.DataFrame(), pd.Series(dtype=int), pd.DataFrame(), {}

        y = flat["label"].astype(int)
        metadata = flat[["time", "symbol", "expiry", "strike", "option_type"]].copy()
        features = flat.drop(columns=["time", "expiry", "label"])
        features = pd.get_dummies(features, columns=["symbol", "option_type"], dummy_na=False)
        features = features.apply(pd.to_numeric, errors="coerce")

        fill_values = features.median(numeric_only=True).fillna(0.0)
        features = features.fillna(fill_values).astype(float)

        artifact = {
            "feature_columns": list(features.columns),
            "fill_values": fill_values.to_dict(),
        }
        return features, y, metadata, artifact

    def prepare_inference_data(self, feature_rows, artifact):
        if isinstance(feature_rows, dict):
            feature_rows = [feature_rows]
        frame = pd.DataFrame(feature_rows)
        if frame.empty:
            return pd.DataFrame()

        feature_values = pd.json_normalize(frame["features"])
        base = pd.concat(
            [
                frame[["symbol", "strike", "option_type"]].reset_index(drop=True),
                feature_values.reset_index(drop=True),
            ],
            axis=1,
        )
        base = pd.get_dummies(base, columns=["symbol", "option_type"], dummy_na=False)
        base = base.apply(pd.to_numeric, errors="coerce")

        columns = artifact["feature_columns"]
        fill_values = artifact.get("fill_values", {})
        for column in columns:
            if column not in base:
                base[column] = fill_values.get(column, 0.0)
        base = base[columns]
        return base.fillna(fill_values).fillna(0.0).astype(float)

    def _resolve_window(self, start_date=None, end_date=None, days=None):
        if days is not None:
            end_at = self._latest_feature_store_day_end() or (
                datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)
            )
            start_at = end_at - timedelta(days=int(days))
            return start_at, end_at

        if start_date is None:
            start_at = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_at = self._parse_date(start_date)

        if end_date is None:
            end_at = start_at + timedelta(days=1)
        else:
            end_at = self._parse_date(end_date) + timedelta(days=1)

        return start_at, end_at

    def _parse_date(self, value):
        if isinstance(value, datetime):
            return value
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=IST)

    def _latest_feature_store_day_end(self):
        query = """
            SELECT MAX(time) AS latest_time
            FROM feature_store
            WHERE label IS NOT NULL
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
        latest_time = row["latest_time"] if row else None
        if latest_time is None:
            return None
        latest_time = pd.Timestamp(latest_time).tz_convert(IST)
        return latest_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def loadfeaturestore(date_range=None):
    start_date = None
    end_date = None
    if date_range:
        start_date, end_date = date_range
    return FeaturePreprocessor().load_feature_store(start_date=start_date, end_date=end_date)


def flatten_features(frame):
    return FeaturePreprocessor().flatten_features(frame)
