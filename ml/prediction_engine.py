import pandas as pd

from db.db_config import get_connection
from ml.model_registry import ModelRegistry
from ml.preprocessing import FeaturePreprocessor
from utils.logger import get_logger


class PredictionEngine:
    def __init__(self, version=None):
        self.registry = ModelRegistry()
        self.preprocessor = FeaturePreprocessor()
        self.logger = get_logger(self.__class__.__name__)
        self.bundle = (
            self.registry.loadmodelby_version(version)
            if version
            else self.registry.loadlatestmodel()
        )

    def predict(self, feature_row):
        x = self.preprocessor.prepare_inference_data(feature_row, self.bundle["artifact"])
        if x.empty:
            raise ValueError("No features supplied for prediction")

        score = float(self.bundle["model"].predict_proba(x)[0, 1])
        threshold = float(self.bundle["artifact"].get("decision_threshold", 0.5))
        predicted_label = int(score >= threshold)
        return {
            "prediction_score": score,
            "predicted_label": predicted_label,
            "model_version": self.bundle["version"],
            "decision_threshold": threshold,
        }

    def predict_many(self, feature_rows):
        rows = [feature_rows] if isinstance(feature_rows, dict) else list(feature_rows)
        x = self.preprocessor.prepare_inference_data(rows, self.bundle["artifact"])
        probabilities = self.bundle["model"].predict_proba(x)[:, 1]
        threshold = float(self.bundle["artifact"].get("decision_threshold", 0.5))
        output = []
        for row, score in zip(rows, probabilities):
            prediction = {
                "prediction_score": float(score),
                "predicted_label": int(score >= threshold),
                "model_version": self.bundle["version"],
                "decision_threshold": threshold,
            }
            output.append({**row, **prediction})
        return output

    def write_prediction(self, feature_row, prediction=None):
        prediction = prediction or self.predict(feature_row)
        record = {
            "time": feature_row["time"],
            "symbol": feature_row["symbol"],
            "expiry": feature_row.get("expiry"),
            "strike": feature_row.get("strike"),
            "option_type": feature_row.get("option_type"),
            "prediction_score": prediction["prediction_score"],
            "model_version": prediction["model_version"],
        }
        query = """
            INSERT INTO model_predictions (
                time, symbol, expiry, strike, option_type, prediction_score, model_version
            )
            VALUES (
                %(time)s, %(symbol)s, %(expiry)s, %(strike)s, %(option_type)s,
                %(prediction_score)s, %(model_version)s
            )
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, record)
        return record

    def predict_latest_from_feature_store(self, symbol=None, limit=1, write=True):
        filters = ["label IS NOT NULL"]
        params = []
        if symbol:
            filters.append("symbol = %s")
            params.append(symbol)

        query = f"""
            SELECT time, symbol, expiry, strike, option_type, features
            FROM feature_store
            WHERE {' AND '.join(filters)}
            ORDER BY time DESC
            LIMIT %s
        """
        params.append(limit)
        with get_connection(cursor_factory=None) as conn:
            frame = pd.read_sql_query(query, conn, params=params)
        if frame.empty:
            return []
        rows = frame.to_dict("records")
        predictions = self.predict_many(rows)
        if write:
            for row in predictions:
                self.write_prediction(row, row)
        self.logger.info("Generated %s predictions", len(predictions))
        return predictions
