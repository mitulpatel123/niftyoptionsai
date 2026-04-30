import os


DB_HOST = os.getenv("NIFTYAI_DB_HOST", "localhost")
DB_PORT = int(os.getenv("NIFTYAI_DB_PORT", "5433"))
DB_NAME = os.getenv("NIFTYAI_DB_NAME", "niftyoptionsai")
DB_USER = os.getenv("NIFTYAI_DB_USER", "postgres")
DB_PASSWORD = os.getenv("NIFTYAI_DB_PASSWORD", "")

DHAN_API_KEY = os.getenv("DHAN_API_KEY") or os.getenv("DHANAPIKEY", "")
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID") or os.getenv("DHANCLIENTID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN") or os.getenv("DHANACCESSTOKEN", "")

DHAN_BASE_URL = os.getenv("DHAN_BASE_URL") or os.getenv("DHANBASEURL", "https://api.dhan.co")
DHAN_WEBSOCKET_URL = (
    os.getenv("DHAN_WEBSOCKET_URL")
    or os.getenv("DHANWEBSOCKETURL", "wss://api-feed.dhan.co")
)

SYMBOLS = ("NIFTY", "BANKNIFTY")
OPTION_CHAIN_INTERVAL_SECONDS = 3
OHLC_INTERVAL_SECONDS = 60
OPTION_OHLC_INTERVAL_SECONDS = int(os.getenv("OPTION_OHLC_INTERVAL_SECONDS", "300"))
HTTP_TIMEOUT_SECONDS = 20

DHAN_OPTION_CHAIN_PATH = "/v2/optionchain"
DHAN_EXPIRY_LIST_PATH = "/v2/optionchain/expirylist"
DHAN_INTRADAY_PATH = "/v2/charts/intraday"
DHAN_INSTRUMENT_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"

UNDERLYINGS = {
    "NIFTY": {
        "security_id": "13",
        "exchange_segment": "IDX_I",
        "instrument": "INDEX",
    },
    "BANKNIFTY": {
        "security_id": "25",
        "exchange_segment": "IDX_I",
        "instrument": "INDEX",
    },
}

# Optional comma-separated list, for example:
# OPTION_OHLC_SECURITY_IDS=52175,52176
OPTION_OHLC_SECURITY_IDS = tuple(
    item.strip() for item in os.getenv("OPTION_OHLC_SECURITY_IDS", "").split(",") if item.strip()
)
AUTO_SELECT_ATM_CONTRACTS = os.getenv("AUTO_SELECT_ATM_CONTRACTS", "1").lower() in (
    "1",
    "true",
    "yes",
)
AUTO_ATM_STRIKES_EACH_SIDE = int(os.getenv("AUTO_ATM_STRIKES_EACH_SIDE", "2"))
OPTION_OHLC_ATM_STRIKES_EACH_SIDE = int(
    os.getenv("OPTION_OHLC_ATM_STRIKES_EACH_SIDE", "0")
)
AUTO_CONTRACT_REFRESH_SECONDS = int(os.getenv("AUTO_CONTRACT_REFRESH_SECONDS", "60"))

# Optional comma-separated websocket subscription list:
# WEBSOCKET_SECURITY_IDS=NSE_FNO:52175,NSE_FNO:52176,IDX_I:13
WEBSOCKET_SECURITY_IDS = tuple(
    item.strip() for item in os.getenv("WEBSOCKET_SECURITY_IDS", "").split(",") if item.strip()
)
