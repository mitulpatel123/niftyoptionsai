import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from features.feature_engineering import FeatureEngineer
from features.feature_store_writer import FeatureStoreWriter
from utils.logger import get_logger


LOGGER = get_logger("build_features_daily")


def parse_args():
    parser = argparse.ArgumentParser(description="Build daily feature rows")
    parser.add_argument("--date", dest="target_date", help="Trading date in YYYY-MM-DD format")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NIFTY", "BANKNIFTY"],
        help="Symbols to build features for",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Build features but do not write to feature_store",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    engineer = FeatureEngineer()
    features = engineer.build_features_for_date(args.target_date, tuple(args.symbols))
    LOGGER.info("Built %s total feature rows", len(features))

    if not args.no_write:
        FeatureStoreWriter().write(features)


if __name__ == "__main__":
    main()

