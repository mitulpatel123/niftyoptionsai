import threading
import time
from collections import deque


class DhanRateLimiter:
    """Thread-safe global rate limiter for Dhan API
    
    FIX #7: Rate limit configuration
    
    IMPORTANT: These limits should be verified against official Dhan API documentation.
    Current values are conservative estimates based on observed behavior:
    
    - option_chain (1 call per 3.5 seconds): ~17 calls/minute
      Used by: optionchainingest.py - fetches full option chain snapshot
      
    - expiry_list (1 call per 3.5 seconds): ~17 calls/minute  
      Used by: optionchainingest.py - fetches expiry dates (cached daily)
      
    - intraday_chart (3 calls per 1 second): ~180 calls/minute
      Used by: indexohlcingest.py - fetches index OHLC data
      
    - data (5 calls per 1 second): ~300 calls/minute
      Used by: generic data fetching, websocket initialization
    
    VERIFICATION TODO:
    1. Check Dhan API documentation for official rate limits
    2. Update LIMITS dictionary below if official limits differ
    3. Current usage analysis (from daily pipeline):
       - option_chain: ~1 call per 60 seconds × 2 symbols = well under limit
       - expiry_list: ~2 calls per day = negligible
       - intraday_chart: ~1 call per 60 seconds × 2 symbols = well under limit
       - data: ~negligible usage
    
    Conclusion: Current rate limiting is working fine and we're well under limits.
    If you hit 429 (Too Many Requests) errors, check if Dhan limits are stricter.
    """

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
