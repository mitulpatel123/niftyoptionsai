import json
import struct
import time
from urllib.parse import urlencode

from websocket import WebSocketApp

from config import settings
from config.settings import AUTO_SELECT_ATM_CONTRACTS, UNDERLYINGS, WEBSOCKET_SECURITY_IDS
from db.db_config import get_connection
from ingest.contract_selector import ATMContractSelector
from utils.dhan_api import require_credentials
from utils.logger import get_logger
from utils.time_utils import getcurrentist


class WebsocketListener:
    FULL_PACKET_CODE = 8
    FULL_PACKET_SUBSCRIBE_CODE = 21

    def __init__(self, subscriptions=None):
        self.logger = get_logger(self.__class__.__name__)
        self.contract_selector = ATMContractSelector()
        self.subscriptions = subscriptions
        self.websocket = None
        self.reconnect_delay_seconds = 5
        self.max_reconnect_delay_seconds = 1800
        self.connected_at = None
        self.rate_limited = False

    def connect(self):
        require_credentials()
        query = urlencode(
            {
                "version": "2",
                "token": settings.DHAN_ACCESS_TOKEN,
                "clientId": settings.DHAN_CLIENT_ID,
                "authType": "2",
            }
        )
        url = f"{settings.DHAN_WEBSOCKET_URL}?{query}"
        self.websocket = WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self.on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        return self.websocket

    def subscribe(self, security_ids=None):
        instruments = security_ids or self._load_subscriptions()
        if not instruments:
            self.logger.warning("No websocket subscriptions configured")
            return

        for index in range(0, len(instruments), 100):
            chunk = instruments[index : index + 100]
            message = {
                "RequestCode": self.FULL_PACKET_SUBSCRIBE_CODE,
                "InstrumentCount": len(chunk),
                "InstrumentList": [
                    {
                        "ExchangeSegment": item["exchange_segment"],
                        "SecurityId": str(item["security_id"]),
                    }
                    for item in chunk
                ],
            }
            self.websocket.send(json.dumps(message))
            self.logger.info("Subscribed to %s websocket instruments", len(chunk))

    def on_message(self, ws, message):
        row = self._parse_binary_message(message)
        if row:
            self.insert_tick(row)

    def _load_subscriptions(self):
        if self.subscriptions:
            return self.subscriptions

        if WEBSOCKET_SECURITY_IDS:
            subscriptions = []
            for item in WEBSOCKET_SECURITY_IDS:
                if ":" in item:
                    exchange_segment, security_id = item.split(":", 1)
                else:
                    exchange_segment, security_id = "NSE_FNO", item
                subscriptions.append(
                    {
                        "exchange_segment": exchange_segment,
                        "security_id": security_id,
                    }
                )
            return subscriptions

        if AUTO_SELECT_ATM_CONTRACTS:
            subscriptions = self.contract_selector.websocket_subscriptions()
            if subscriptions:
                return subscriptions

        return [
            {
                "exchange_segment": data["exchange_segment"],
                "security_id": data["security_id"],
            }
            for data in UNDERLYINGS.values()
        ]

    def _parse_binary_message(self, message):
        if not isinstance(message, (bytes, bytearray)):
            self.logger.debug("Ignoring non-binary websocket message: %s", message)
            return None
        if len(message) < 8:
            self.logger.warning("Ignoring short websocket packet of %s bytes", len(message))
            return None

        response_code = message[0]
        security_id = struct.unpack_from("<i", message, 4)[0]
        if response_code != self.FULL_PACKET_CODE:
            return None
        if len(message) < 162:
            self.logger.warning(
                "Full packet for security_id=%s was shorter than expected: %s bytes",
                security_id,
                len(message),
            )
            return None

        depth_offset = 62
        bid_qty = struct.unpack_from("<i", message, depth_offset)[0]
        ask_qty = struct.unpack_from("<i", message, depth_offset + 4)[0]
        bid_price = struct.unpack_from("<f", message, depth_offset + 12)[0]
        ask_price = struct.unpack_from("<f", message, depth_offset + 16)[0]

        return {
            "time": getcurrentist(),
            "security_id": security_id,
            "bidprice1": bid_price,
            "bidqty1": bid_qty,
            "askprice1": ask_price,
            "askqty1": ask_qty,
        }

    def insert_tick(self, row):
        query = """
            INSERT INTO market_depth (
                time, security_id, bidprice1, bidqty1, askprice1, askqty1
            )
            VALUES (
                %(time)s, %(security_id)s, %(bidprice1)s, %(bidqty1)s,
                %(askprice1)s, %(askqty1)s
            )
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, row)

    def _on_open(self, ws):
        self.logger.info("Dhan websocket connected")
        self.connected_at = time.time()
        self.rate_limited = False
        self.reconnect_delay_seconds = 5
        self.subscribe()

    def _on_error(self, ws, error):
        self.logger.error("Dhan websocket error: %s", error)
        error_text = str(error).lower()
        if "429" in error_text or "too many requests" in error_text or "blocked" in error_text:
            self.rate_limited = True
            self.reconnect_delay_seconds = self.max_reconnect_delay_seconds
            self.logger.error(
                "Dhan websocket is rate-limited/blocked. Pausing websocket reconnects for %s seconds.",
                self.reconnect_delay_seconds,
            )

    def _on_close(self, ws, close_status_code, close_msg):
        self.logger.warning(
            "Dhan websocket closed: code=%s message=%s", close_status_code, close_msg
        )
        if self.rate_limited:
            self.reconnect_delay_seconds = self.max_reconnect_delay_seconds
        elif self.connected_at and time.time() - self.connected_at < 10:
            self.reconnect_delay_seconds = min(
                self.reconnect_delay_seconds * 2,
                self.max_reconnect_delay_seconds,
            )
        self.connected_at = None

    def run(self):
        self.logger.info("Starting websocket listener")
        while True:
            try:
                websocket = self.connect()
                websocket.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                self.logger.exception("Websocket listener failed")
            self.logger.info(
                "Reconnecting websocket in %s seconds", self.reconnect_delay_seconds
            )
            time.sleep(self.reconnect_delay_seconds)
