import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.model_trainer import ModelTrainer
from utils.logger import get_logger


LOGGER = get_logger("trainmodeldaily")


def parse_args():
    parser = argparse.ArgumentParser(description="Train daily classical ML model")
    parser.add_argument("--days", type=int, default=30, help="Lookback days from feature_store")
    parser.add_argument("--start-date", help="Optional start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional end date YYYY-MM-DD")
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--subsample", type=float, default=0.9)
    parser.add_argument("--colsample-bytree", type=float, default=0.9)
    parser.add_argument("--optuna-trials", type=int, default=0, help="Number of Optuna trials to run for hyperparameter search")
    parser.add_argument("--no-promote", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    trainer = ModelTrainer(
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        n_estimators=args.n_estimators,
        subsample=args.subsample,
        colsample_bytree=args.colsample_bytree,
    )
    try:
        version, metrics = trainer.train(
            days=args.days,
            start_date=args.start_date,
            end_date=args.end_date,
            promote_if_better=not args.no_promote,
            optuna_trials=args.optuna_trials,
        )
    except Exception as exc:
        LOGGER.error("Training skipped/failed: %s", exc)
        raise SystemExit(1) from exc
    else:
        LOGGER.info("Training complete: version=%s metrics=%s", version, metrics)


if __name__ == "__main__":
    main()
