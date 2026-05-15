import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

from db.db_config import get_connection

def check_table(conn, table_name, count_query, null_queries=None, zero_queries=None):
    print(f"\n--- Checking Table: {table_name} ---")
    with conn.cursor() as cur:
        cur.execute(count_query)
        count = cur.fetchone()['count']
        print(f"Total Rows: {count}")
        
        if count == 0:
            print("  -> Table is empty.")
            return

        if null_queries:
            for col, q in null_queries.items():
                cur.execute(q)
                null_count = cur.fetchone()['count']
                if null_count > 0:
                    print(f"  -> WARNING: {null_count} rows have NULL in column '{col}'")
                else:
                    print(f"  -> OK: 0 rows have NULL in column '{col}'")
                    
        if zero_queries:
            for col, q in zero_queries.items():
                cur.execute(q)
                zero_count = cur.fetchone()['count']
                if zero_count > 0:
                    print(f"  -> WARNING: {zero_count} rows have ZERO in column '{col}'")
                else:
                    print(f"  -> OK: 0 rows have ZERO in column '{col}'")

def main():
    print("Starting Data Quality Audit...")
    try:
        with get_connection() as conn:
            check_table(
                conn, 
                "index_ohlc", 
                "SELECT COUNT(*) FROM index_ohlc",
                null_queries={"close": "SELECT COUNT(*) FROM index_ohlc WHERE close IS NULL"},
                zero_queries={"close": "SELECT COUNT(*) FROM index_ohlc WHERE close = 0"}
            )
            
            check_table(
                conn, 
                "option_ohlc", 
                "SELECT COUNT(*) FROM option_ohlc",
                null_queries={"close": "SELECT COUNT(*) FROM option_ohlc WHERE close IS NULL"},
                zero_queries={"close": "SELECT COUNT(*) FROM option_ohlc WHERE close = 0"}
            )
            
            check_table(
                conn, 
                "market_depth", 
                "SELECT COUNT(*) FROM market_depth",
                null_queries={
                    "bidprice1": "SELECT COUNT(*) FROM market_depth WHERE bidprice1 IS NULL",
                    "askprice1": "SELECT COUNT(*) FROM market_depth WHERE askprice1 IS NULL"
                },
                zero_queries={
                    "bidprice1": "SELECT COUNT(*) FROM market_depth WHERE bidprice1 = 0 AND bidqty1 > 0"
                }
            )
            
            # Check feature_store JSON values
            print(f"\n--- Checking Table: feature_store ---")
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM feature_store")
                count = cur.fetchone()['count']
                print(f"Total Rows: {count}")
                if count > 0:
                    cur.execute("""
                        SELECT COUNT(*) FROM feature_store 
                        WHERE features->>'index_close' IS NULL 
                           OR features->>'index_close' = '0' 
                           OR features->>'index_close' = 'NaN'
                    """)
                    bad_features = cur.fetchone()['count']
                    if bad_features > 0:
                        print(f"  -> WARNING: {bad_features} rows have NULL, 0, or NaN for 'index_close' in features JSON")
                    else:
                        print("  -> OK: 'index_close' looks healthy in features JSON")
                        
    except Exception as e:
        print(f"Audit failed: {e}")

if __name__ == "__main__":
    main()
