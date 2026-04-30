import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from features.feature_engineering import FeatureEngineer
from features.feature_store_writer import FeatureStoreWriter
from features.label_builder import LabelBuilder
from utils.logger import get_logger


LOGGER = get_logger("build_labels_daily")


def parse_args():
    parser = argparse.ArgumentParser(description="Build daily labels and write feature_store")
    parser.add_argument("--date", dest="target_date", help="Trading date in YYYY-MM-DD format")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NIFTY", "BANKNIFTY"],
        help="Symbols to build labels for",
    )
    parser.add_argument("--lookahead-minutes", type=int, default=15)
    parser.add_argument("--profit-points", type=float, default=10.0)
    parser.add_argument("--stop-points", type=float, default=5.0)
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Build features and labels but do not write to feature_store",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    engineer = FeatureEngineer()
    features = engineer.build_features_for_date(args.target_date, tuple(args.symbols))
    LOGGER.info("Built %s feature rows", len(features))

    label_builder = LabelBuilder(
        lookahead_minutes=args.lookahead_minutes,
        profit_points=args.profit_points,
        stop_points=args.stop_points,
    )
    labels = label_builder.build_labels_for_features(features)
    LOGGER.info("Built %s labels", len(labels))

    if not args.no_write:
        FeatureStoreWriter().write(features, labels)


if __name__ == "__main__":
    main()
