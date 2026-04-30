import json

import pandas as pd
from psycopg2.extras import Json

from db.db_config import get_connection
from utils.logger import get_logger


FEATURE_KEY_COLUMNS = ["time", "symbol", "expiry", "strike", "option_type"]


class FeatureStoreWriter:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def write(self, features_df, labels_df=None):
        if features_df.empty:
            self.logger.warning("No features to write")
            return 0

        frame = features_df.copy()
        if labels_df is not None and not labels_df.empty:
            label_columns = FEATURE_KEY_COLUMNS + ["label"]
            frame = frame.merge(
                labels_df[label_columns],
                on=FEATURE_KEY_COLUMNS,
                how="left",
            )
        elif "label" not in frame.columns:
            frame["label"] = None

        rows = [self._row_to_record(row) for _, row in frame.iterrows()]
        with get_connection() as conn:
            with conn.cursor() as cur:
                for record in rows:
                    cur.execute(
                        """
                        DELETE FROM feature_store
                        WHERE time = %(time)s
                          AND symbol = %(symbol)s
                          AND expiry IS NOT DISTINCT FROM %(expiry)s
                          AND strike IS NOT DISTINCT FROM %(strike)s
                          AND option_type IS NOT DISTINCT FROM %(option_type)s
                        """,
                        record,
                    )
                    cur.execute(
                        """
                        INSERT INTO feature_store (
                            time, symbol, expiry, strike, option_type, features, label
                        )
                        VALUES (
                            %(time)s, %(symbol)s, %(expiry)s, %(strike)s,
                            %(option_type)s, %(features)s, %(label)s
                        )
                        """,
                        record,
                    )

        self.logger.info("Wrote %s feature_store rows", len(rows))
        return len(rows)

    def _row_to_record(self, row):
        label = row.get("label")
        if pd.isna(label):
            label = None
        else:
            label = int(label)

        return {
            "time": row["time"],
            "symbol": row["symbol"],
            "expiry": row.get("expiry"),
            "strike": int(row["strike"]) if not pd.isna(row.get("strike")) else None,
            "option_type": row.get("option_type"),
            "features": Json(self._json_safe(row["features"])),
            "label": label,
        }

    def _json_safe(self, value):
        return json.loads(json.dumps(value, default=str, allow_nan=False))
