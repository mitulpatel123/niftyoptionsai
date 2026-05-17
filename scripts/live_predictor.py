import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.model_registry import ModelRegistry
from ml.preprocessing import FeaturePreprocessor
from features.feature_engineering import FeatureEngineer
from utils.time_utils import IST, is_market_day
from utils.logger import get_logger

LOGGER = get_logger("live_predictor")

def main():
    parser = argparse.ArgumentParser(description="Run the Live Prediction Engine")
    parser.add_argument("--symbol", default="NIFTY", help="Symbol to predict")
    parser.add_argument("--continuous", action="store_true", help="Run forever during market hours")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("🚀 NIFTY OPTIONS AI - LIVE PREDICTION ENGINE 🚀")
    print("="*60)
    
    registry = ModelRegistry()
    best_record = registry.getbestmodel()
    if not best_record:
        LOGGER.error("No trained models found in the database!")
        return
        
    bundle = registry._load_bundle(best_record["model_path"])
    model = bundle["model"]
    artifact = bundle["artifact"]
    print(f"✅ Loaded Highly Optimized AI Model: {bundle['version']}")
    print(f"✅ Model AUC Score: {best_record.get('metrics', {}).get('roc_auc', 'N/A')}")
    print("="*60 + "\n")

    engineer = FeatureEngineer()
    preprocessor = FeaturePreprocessor()

    while True:
        now = datetime.now(IST)
        
        # Check if market is open
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if not is_market_day(now) or now < market_open or now > market_close:
            if not args.continuous:
                print("🕒 Market is currently closed. Running a test prediction on the last available data...")
                run_prediction(engineer, preprocessor, model, artifact, args.symbol, today=True)
                break
                
            # Sleep 60 seconds quietly without printing, unless it's the exact hour
            if now.minute == 0 and now.second < 60:
                print(f"💤 [{now.strftime('%H:%M:%S')}] Market is closed. Waiting for open...")
            time.sleep(60)
            continue
            
        # If market is open, wait until 15 seconds past the minute
        current_second = now.second
        if current_second < 15:
            time.sleep(15 - current_second)
        elif current_second > 15:
            sleep_time = 60 - current_second + 15
            time.sleep(sleep_time)
            
        run_prediction(engineer, preprocessor, model, artifact, args.symbol, today=True)
        
        if not args.continuous:
            break
            
        time.sleep(40) # Wait a bit before checking the loop again

def run_prediction(engineer, preprocessor, model, artifact, symbol, today=True):
    target_date = datetime.now(IST).date() if today else None
    
    # We suppress logs from FeatureEngineer to keep the terminal clean
    logging.getLogger("FeatureEngineer").setLevel(logging.ERROR)
    
    try:
        features_df = engineer.build_features(target_date, symbol)
    except Exception as e:
        print(f"❌ Error fetching data: {e}")
        return
        
    if features_df.empty:
        print("⚠️ No data available for prediction yet.")
        return
        
    # Get the latest minute
    latest_row = features_df.iloc[[-1]].to_dict(orient="records")[0]
    timestamp = latest_row["time"]
    
    X = preprocessor.prepare_inference_data(latest_row, artifact)
    if X.empty:
        print("⚠️ Failed to preprocess features.")
        return
        
    prob = model.predict_proba(X)[0][1]
    prediction = int(prob > 0.5)
    
    dist_vwap = latest_row['features'].get('index_distance_from_vwap')
    dist_vwap_str = f"{dist_vwap:.2f}" if dist_vwap is not None else "N/A"
    
    dist_pain = latest_row['features'].get('distance_from_max_pain')
    dist_pain_str = f"{dist_pain:.2f}" if dist_pain is not None else "N/A"
    
    print("\n" + "-"*50)
    print(f"🕒 TIME: {timestamp.strftime('%Y-%m-%d %H:%M:%S')} | SYMBOL: {symbol}")
    print(f"📊 Market Distance to VWAP: {dist_vwap_str}")
    print(f"🧲 Distance to Max Pain: {dist_pain_str}")
    print("-" * 50)
    
    if prediction == 1:
        print(f"🟩 BUY SIGNAL DETECTED! (Confidence: {prob*100:.1f}%)")
        print("   -> The AI expects a massive breakout! Action recommended.")
    else:
        print(f"⬛ NO ACTION (Confidence of breakout: {prob*100:.1f}%)")
        print("   -> The AI sees sideways noise or a trap. Stay out.")
    print("-" * 50 + "\n")

if __name__ == "__main__":
    main()
