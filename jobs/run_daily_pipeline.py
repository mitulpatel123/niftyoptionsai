import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.dhan_api import validate_credentials_or_raise
from utils.logger import get_logger
from utils.time_utils import IST, is_market_day, is_trading_holiday


LOGGER = get_logger("run_daily_pipeline")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the full market-day pipeline: ingestion first, features/labels after close."
    )
    parser.add_argument("--date", dest="target_date", help="Trading date in YYYY-MM-DD format")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["NIFTY", "BANKNIFTY"],
        help="Symbols for after-market feature/label build",
    )
    parser.add_argument("--skip-ingestion", action="store_true")
    parser.add_argument("--skip-feature-build", action="store_true")
    parser.add_argument("--train-model", action="store_true")
    parser.add_argument("--train-days", type=int, default=30)
    parser.add_argument("--optuna-trials", type=int, default=50, help="Number of Optuna trials to run during training")
    parser.add_argument(
        "--run-seconds",
        type=int,
        help="Test mode: run ingestion for N seconds instead of until market close",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for market open; useful if you start manually after 09:15 IST",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target_date = args.target_date or datetime.now(IST).strftime("%Y-%m-%d")

    if not args.skip_ingestion:
        # Generate the daily access token automatically
        try:
            # We import here to avoid circular imports if any, and ensure it's only loaded when needed
            sys.path.append(str(PROJECT_ROOT))
            from scripts.auto_token import generate_and_save_dhan_token
            LOGGER.info("Attempting to auto-generate Dhan Access Token...")
            success = generate_and_save_dhan_token()
            if success:
                from dotenv import load_dotenv
                load_dotenv(override=True)
                # IMPORTANT: Update the loaded `settings` module memory with the new token
                from config import settings
                settings.DHAN_ACCESS_TOKEN = os.environ.get('DHAN_ACCESS_TOKEN', settings.DHAN_ACCESS_TOKEN)
            else:
                LOGGER.error("Failed to generate Dhan Access Token. Ingestion might fail if the old token is expired.")
        except Exception as e:
            LOGGER.error("Error running auto-token generation: %s", e)
            
        run_ingestion_until_close(args)

    if not args.skip_feature_build:
        build_features_and_labels(target_date, args.symbols)

    if args.train_model:
        train_model(args.train_days, optuna_trials=args.optuna_trials)


def run_ingestion_until_close(args):
    validate_credentials_or_raise()

    now = datetime.now(IST)
    market_open = now.replace(
        hour=MARKET_OPEN_HOUR,
        minute=MARKET_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR,
        minute=MARKET_CLOSE_MINUTE,
        second=0,
        microsecond=0,
    )

    if not is_market_day(now):
        if is_trading_holiday(now):
            LOGGER.warning("Today is an NSE trading holiday in IST; ingestion will not be started")
        else:
            LOGGER.warning("Today is not a weekday in IST; ingestion will not be started")
        return

    if now < market_open and not args.no_wait:
        sleep_seconds = int((market_open - now).total_seconds())
        LOGGER.info("Waiting %s seconds for market open at %s", sleep_seconds, market_open)
        time.sleep(max(0, sleep_seconds))

    if args.run_seconds:
        stop_at = datetime.now(IST) + timedelta(seconds=args.run_seconds)
    else:
        stop_at = market_close

    if datetime.now(IST) >= stop_at:
        LOGGER.info("Market close/test stop time already passed; skipping ingestion")
        return

    LOGGER.info("Starting ingestion until %s", stop_at)
    process = subprocess.Popen(
        [sys.executable, "runallingestors.py"],
        cwd=str(PROJECT_ROOT),
        env=os.environ.copy(),
    )

    try:
        while datetime.now(IST) < stop_at and process.poll() is None:
            time.sleep(5)
    finally:
        stop_process(process)


def stop_process(process):
    if process.poll() is not None:
        LOGGER.info("Ingestion process exited with code %s", process.returncode)
        return

    LOGGER.info("Stopping ingestion process")
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        LOGGER.warning("Ingestion did not stop after SIGTERM; killing process")
        process.kill()
        process.wait(timeout=10)
    LOGGER.info("Ingestion stopped with code %s", process.returncode)


def build_features_and_labels(target_date, symbols):
    command = [
        sys.executable,
        "jobs/build_labels_daily.py",
        "--date",
        target_date,
        "--symbols",
        *symbols,
    ]
    LOGGER.info("Building feature_store rows: %s", " ".join(command))
    subprocess.run(command, cwd=str(PROJECT_ROOT), check=True, env=os.environ.copy())


def train_model(days, optuna_trials=0):
    command = [sys.executable, "jobs/trainmodeldaily.py", "--days", str(days)]
    if optuna_trials and optuna_trials > 0:
        command.extend(["--optuna-trials", str(optuna_trials)])
    LOGGER.info("Training model: %s", " ".join(command))
    subprocess.run(command, cwd=str(PROJECT_ROOT), check=True, env=os.environ.copy())


if __name__ == "__main__":
    main()
