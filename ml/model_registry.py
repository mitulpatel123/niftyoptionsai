import pickle
from datetime import datetime
from pathlib import Path

from psycopg2.extras import Json

from db.db_config import get_connection
from utils.logger import get_logger
from utils.time_utils import IST


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "models"


class ModelRegistry:
    def __init__(self, models_dir=MODELS_DIR):
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger(self.__class__.__name__)
        self.ensure_table()

    def ensure_table(self):
        query = """
            CREATE TABLE IF NOT EXISTS model_registry (
                version       TEXT PRIMARY KEY,
                model_type    TEXT NOT NULL,
                model_path    TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'candidate',
                metrics       JSONB NOT NULL DEFAULT '{}'::jsonb,
                feature_count INTEGER,
                train_start   TIMESTAMPTZ,
                train_end     TIMESTAMPTZ,
                trained_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                promoted_at   TIMESTAMPTZ,
                notes         TEXT
            )
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)

    def save_model(
        self,
        model,
        version,
        metrics,
        artifact=None,
        model_type="xgboost",
        status="candidate",
        train_start=None,
        train_end=None,
        notes=None,
    ):
        path = self.models_dir / f"{version}.pkl"
        bundle = {
            "version": version,
            "model_type": model_type,
            "model": model,
            "artifact": artifact or {},
            "metrics": metrics or {},
            "saved_at": datetime.now(IST).isoformat(),
        }
        with path.open("wb") as handle:
            pickle.dump(bundle, handle)

        self.register_model(
            version=version,
            model_type=model_type,
            model_path=str(path),
            metrics=metrics,
            feature_count=len((artifact or {}).get("feature_columns", [])),
            status=status,
            train_start=train_start,
            train_end=train_end,
            notes=notes,
        )
        self.logger.info("Saved model %s to %s", version, path)
        return path

    def register_model(
        self,
        version,
        model_type,
        model_path,
        metrics,
        feature_count,
        status="candidate",
        train_start=None,
        train_end=None,
        notes=None,
    ):
        query = """
            INSERT INTO model_registry (
                version, model_type, model_path, status, metrics,
                feature_count, train_start, train_end, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (version) DO UPDATE SET
                model_type = EXCLUDED.model_type,
                model_path = EXCLUDED.model_path,
                status = EXCLUDED.status,
                metrics = EXCLUDED.metrics,
                feature_count = EXCLUDED.feature_count,
                train_start = EXCLUDED.train_start,
                train_end = EXCLUDED.train_end,
                notes = EXCLUDED.notes
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        version,
                        model_type,
                        model_path,
                        status,
                        Json(metrics or {}),
                        feature_count,
                        train_start,
                        train_end,
                        notes,
                    ),
                )

    def loadlatestmodel(self):
        active = self.get_active_model_record()
        if active:
            return self._load_bundle(active["model_path"])
        best = self.getbestmodel()
        if not best:
            raise FileNotFoundError("No model is registered yet")
        return self._load_bundle(best["model_path"])

    def loadmodelby_version(self, version):
        query = "SELECT * FROM model_registry WHERE version = %s"
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (version,))
                row = cur.fetchone()
        if not row:
            raise FileNotFoundError(f"Model version {version} is not registered")
        return self._load_bundle(row["model_path"])

    def record_metrics(self, version, accuracy=None, precision=None, recall=None, timestamp=None, **extra):
        metrics = {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "timestamp": (timestamp or datetime.now(IST)).isoformat(),
        }
        metrics.update(extra)
        query = """
            UPDATE model_registry
            SET metrics = metrics || %s::jsonb
            WHERE version = %s
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (Json(metrics), version))

    def getbestmodel(self):
        query = """
            SELECT *
            FROM model_registry
            ORDER BY COALESCE((metrics->>'roc_auc')::float, (metrics->>'f1')::float, 0) DESC,
                     trained_at DESC
            LIMIT 1
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()

    def get_active_model_record(self):
        query = """
            SELECT *
            FROM model_registry
            WHERE status = 'active'
            ORDER BY promoted_at DESC NULLS LAST, trained_at DESC
            LIMIT 1
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchone()

    def promote_model(self, version):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE model_registry SET status = 'archived' WHERE status = 'active'")
                cur.execute(
                    """
                    UPDATE model_registry
                    SET status = 'active', promoted_at = now()
                    WHERE version = %s
                    """,
                    (version,),
                )
        self.logger.info("Promoted model %s to active", version)

    def _load_bundle(self, model_path):
        with Path(model_path).open("rb") as handle:
            return pickle.load(handle)


def loadlatestmodel():
    return ModelRegistry().loadlatestmodel()


def loadmodelby_version(version):
    return ModelRegistry().loadmodelby_version(version)
