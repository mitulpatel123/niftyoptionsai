import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.model_trainer import ModelTrainer
from utils.logger import get_logger


LOGGER = get_logger("evaluatemodeldaily")


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate latest model")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--start-date", help="Optional start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional end date YYYY-MM-DD")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        version, metrics = ModelTrainer().evaluate_latest(
            days=args.days,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except Exception as exc:
        LOGGER.error("Evaluation skipped/failed: %s", exc)
        raise SystemExit(1) from exc
    else:
        LOGGER.info("Evaluation complete: version=%s metrics=%s", version, metrics)


if __name__ == "__main__":
    main()
