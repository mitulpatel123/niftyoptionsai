import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("\"'")

import pandas as pd
from db.db_config import get_connection

def analyze_gaps(target_date):
    print(f"\n🔍 ANALYZING DATA INTEGRITY FOR: {target_date}\n")
    
    with get_connection() as conn:
        # 1. Check Index OHLC Gaps
        print("--- 📈 INDEX OHLC ---")
        idx_df = pd.read_sql_query(
            "SELECT time, symbol FROM index_ohlc WHERE DATE(time) = %s ORDER BY time ASC",
            conn, params=(target_date,)
        )
        if idx_df.empty:
            print(f"❌ ERROR: No Index OHLC data found for {target_date}!")
        else:
            for symbol in idx_df["symbol"].unique():
                sym_df = idx_df[idx_df["symbol"] == symbol].copy()
                sym_df["diff"] = sym_df["time"].diff().dt.total_seconds()
                gaps = sym_df[sym_df["diff"] > 65]
                print(f"✅ {symbol}: Collected {len(sym_df)} rows. Found {len(gaps)} missing minutes/gaps > 65s.")
                if not gaps.empty:
                    print(gaps[["time", "diff"]].head(5).to_string(index=False))

        # 2. Check Option Chain Gaps
        print("\n--- ⛓️ OPTION CHAIN SNAPSHOT ---")
        oc_df = pd.read_sql_query(
            "SELECT time, underlying_symbol FROM optionchainsnapshot WHERE DATE(time) = %s ORDER BY time ASC",
            conn, params=(target_date,)
        )
        if oc_df.empty:
            print(f"❌ ERROR: No Option Chain data found for {target_date}!")
        else:
            # Group by underlying and unique timestamps (since there are multiple strikes per timestamp)
            unique_times = oc_df.drop_duplicates(subset=["time", "underlying_symbol"])
            for symbol in unique_times["underlying_symbol"].unique():
                sym_df = unique_times[unique_times["underlying_symbol"] == symbol].copy()
                sym_df["diff"] = sym_df["time"].diff().dt.total_seconds()
                gaps = sym_df[sym_df["diff"] > 65]
                print(f"✅ {symbol}: Collected {len(sym_df)} unique timestamps. Found {len(gaps)} missing minutes/gaps > 65s.")
                if not gaps.empty:
                    print(gaps[["time", "diff"]].head(5).to_string(index=False))

        # 3. Check Option OHLC Intraday
        print("\n--- 📊 OPTION OHLC (INTRADAY CHARTS) ---")
        opt_df = pd.read_sql_query(
            "SELECT time, symbol FROM option_ohlc WHERE DATE(time) = %s ORDER BY time ASC",
            conn, params=(target_date,)
        )
        if opt_df.empty:
            print(f"❌ ERROR: No Option OHLC data found for {target_date}!")
        else:
            unique_times = opt_df.drop_duplicates(subset=["time", "symbol"])
            for symbol in unique_times["symbol"].unique():
                sym_df = unique_times[unique_times["symbol"] == symbol].copy()
                sym_df["diff"] = sym_df["time"].diff().dt.total_seconds()
                gaps = sym_df[sym_df["diff"] > 65]
                print(f"✅ {symbol} (Options): Collected {len(sym_df)} unique minutes. Found {len(gaps)} missing minutes/gaps > 65s.")
                if not gaps.empty:
                    print(gaps[["time", "diff"]].head(5).to_string(index=False))
                    
    print("\n✅ DIAGNOSTIC COMPLETE\n")

if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else "2026-05-25"
    analyze_gaps(date_str)
