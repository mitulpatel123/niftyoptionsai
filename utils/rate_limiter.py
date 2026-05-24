import threading
import time
from collections import deque


class DhanRateLimiter:
    """Thread-safe global rate limiter for Dhan API"""

    LIMITS = {
        "option_chain": {"calls": 1, "period": 3.5},
        "expiry_list": {"calls": 1, "period": 3.5},
        "intraday_chart": {"calls": 3, "period": 1.0},
        "data": {"calls": 5, "period": 1.0},
    }

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._history = {k: deque() for k in cls.LIMITS}
                    cls._instance._mutex = threading.Lock()
        return cls._instance

    def acquire(self, endpoint_type: str, timeout: float = 60.0) -> bool:
        if endpoint_type not in self.LIMITS:
            return True

        limit = self.LIMITS[endpoint_type]
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            with self._mutex:
                now = time.monotonic()
                history = self._history[endpoint_type]

                # Remove old calls outside window
                while history and history[0] < now - limit["period"]:
                    history.popleft()

                if len(history) < limit["calls"]:
                    history.append(now)
                    return True

            time.sleep(0.05)

        return False


# Global singleton
rate_limiter = DhanRateLimiter()
