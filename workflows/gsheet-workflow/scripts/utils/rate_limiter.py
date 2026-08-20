"""
Google Sheets API Rate Limiter

Manages API request rate limits to prevent quota exhaustion and 429 errors.

Google Sheets API Limits:
- 300 read requests per minute per project
- 500 requests per 100 seconds per project
- 100 requests per 100 seconds per user
- 60 write requests per minute per user

This module implements:
1. Token bucket algorithm for rate limiting
2. Automatic delays to prevent hitting quotas
3. Exponential backoff for 429 errors
4. Request tracking and analytics

Example:
    >>> from scripts.rate_limiter import RateLimiter
    >>> limiter = RateLimiter()
    >>> with limiter.limit():
    ...     service.spreadsheets().get(spreadsheetId='abc').execute()
"""

import os
import time
import threading
from typing import Optional, Callable, Any
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timedelta

# Load ~/.agents/.env and ~/.agents/.config into os.environ (see .env.example).
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d != _os.path.dirname(_d):
    if _os.path.isfile(_os.path.join(_d, '_shared', 'agents_config.py')):
        _sys.path.insert(0, _os.path.join(_d, '_shared'))
        break
    _d = _os.path.dirname(_d)
import agents_config  # noqa: F401,E402



class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded and cannot be retried."""
    pass


class RateLimiter:
    """
    Token bucket rate limiter for Google Sheets API.

    Attributes:
        requests_per_minute: Maximum requests per minute (default: 250, buffer from 300 limit)
        requests_per_100s: Maximum requests per 100 seconds (default: 450, buffer from 500 limit)
        auto_delay_threshold: Number of consecutive requests before auto-delay (default: 50)
        auto_delay_seconds: Delay duration in seconds (default: 1)
        enable_backoff: Enable exponential backoff on 429 errors (default: True)
        max_backoff_attempts: Maximum backoff attempts (default: 4)
    """

    def __init__(
        self,
        requests_per_minute: Optional[int] = None,
        requests_per_100s: Optional[int] = None,
        auto_delay_threshold: Optional[int] = None,
        auto_delay_seconds: Optional[float] = None,
        enable_backoff: bool = True,
        max_backoff_attempts: Optional[int] = None,
        verbose: bool = False
    ):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Max requests per minute (default: 250 or GOOGLE_SHEETS_REQUESTS_PER_MINUTE env)
            requests_per_100s: Max requests per 100 seconds (default: 450 or GOOGLE_SHEETS_REQUESTS_PER_100S env)
            auto_delay_threshold: Requests before auto-delay (default: 50 or GOOGLE_SHEETS_AUTO_DELAY_THRESHOLD env)
            auto_delay_seconds: Auto-delay duration (default: 1.0 or GOOGLE_SHEETS_AUTO_DELAY_SECONDS env)
            enable_backoff: Enable exponential backoff for 429 errors
            max_backoff_attempts: Max retry attempts with backoff (default: 4 or GOOGLE_SHEETS_MAX_BACKOFF_ATTEMPTS env)
            verbose: Print rate limiting information
        """
        # Read from environment variables if not provided
        self.requests_per_minute = (
            requests_per_minute
            if requests_per_minute is not None
            else int(os.getenv('GOOGLE_SHEETS_REQUESTS_PER_MINUTE', '250'))
        )
        self.requests_per_100s = (
            requests_per_100s
            if requests_per_100s is not None
            else int(os.getenv('GOOGLE_SHEETS_REQUESTS_PER_100S', '450'))
        )
        self.auto_delay_threshold = (
            auto_delay_threshold
            if auto_delay_threshold is not None
            else int(os.getenv('GOOGLE_SHEETS_AUTO_DELAY_THRESHOLD', '50'))
        )
        self.auto_delay_seconds = (
            auto_delay_seconds
            if auto_delay_seconds is not None
            else float(os.getenv('GOOGLE_SHEETS_AUTO_DELAY_SECONDS', '1.0'))
        )
        self.enable_backoff = enable_backoff
        self.max_backoff_attempts = (
            max_backoff_attempts
            if max_backoff_attempts is not None
            else int(os.getenv('GOOGLE_SHEETS_MAX_BACKOFF_ATTEMPTS', '4'))
        )
        self.verbose = verbose

        # Request tracking
        self._lock = threading.Lock()
        self._request_times = deque()  # Timestamps of recent requests
        self._consecutive_requests = 0

        # Statistics
        self.total_requests = 0
        self.total_delays = 0
        self.total_backoffs = 0

    def _cleanup_old_requests(self):
        """Remove request timestamps older than 100 seconds."""
        cutoff_time = time.time() - 100
        while self._request_times and self._request_times[0] < cutoff_time:
            self._request_times.popleft()

    def _get_requests_in_window(self, window_seconds: int) -> int:
        """
        Get number of requests in the last N seconds.

        Args:
            window_seconds: Time window in seconds

        Returns:
            int: Number of requests in window
        """
        cutoff_time = time.time() - window_seconds
        return sum(1 for t in self._request_times if t >= cutoff_time)

    def _calculate_wait_time(self) -> float:
        """
        Calculate how long to wait before next request.

        Returns:
            float: Wait time in seconds (0 if no wait needed)
        """
        with self._lock:
            self._cleanup_old_requests()

            # Check per-minute limit (60 second window)
            requests_in_minute = self._get_requests_in_window(60)
            if requests_in_minute >= self.requests_per_minute:
                # Wait until oldest request in minute expires
                oldest_in_minute = None
                cutoff = time.time() - 60
                for t in self._request_times:
                    if t >= cutoff:
                        oldest_in_minute = t
                        break

                if oldest_in_minute:
                    wait_time = 60 - (time.time() - oldest_in_minute) + 0.1
                    if self.verbose:
                        print(f"[Rate Limit] Per-minute limit reached. Waiting {wait_time:.1f}s...")
                    return max(0, wait_time)

            # Check per-100s limit
            requests_in_100s = self._get_requests_in_window(100)
            if requests_in_100s >= self.requests_per_100s:
                # Wait until oldest request in 100s expires
                if self._request_times:
                    oldest_request = self._request_times[0]
                    wait_time = 100 - (time.time() - oldest_request) + 0.1
                    if self.verbose:
                        print(f"[Rate Limit] Per-100s limit reached. Waiting {wait_time:.1f}s...")
                    return max(0, wait_time)

            # Check auto-delay threshold
            if self._consecutive_requests >= self.auto_delay_threshold:
                if self.verbose:
                    print(f"[Rate Limit] Auto-delay after {self._consecutive_requests} requests ({self.auto_delay_seconds}s)...")
                self._consecutive_requests = 0
                return self.auto_delay_seconds

            return 0

    def _record_request(self):
        """Record that a request was made."""
        with self._lock:
            current_time = time.time()
            self._request_times.append(current_time)
            self._consecutive_requests += 1
            self.total_requests += 1

    def wait_if_needed(self):
        """
        Wait if necessary to comply with rate limits.

        This method should be called before making an API request.
        """
        wait_time = self._calculate_wait_time()
        if wait_time > 0:
            self.total_delays += 1
            time.sleep(wait_time)

        self._record_request()

    @contextmanager
    def limit(self):
        """
        Context manager for rate-limited API calls.

        Example:
            >>> limiter = RateLimiter()
            >>> with limiter.limit():
            ...     result = service.spreadsheets().get(...).execute()
        """
        self.wait_if_needed()
        try:
            yield
        finally:
            pass

    def execute_with_backoff(
        self,
        api_call: Callable[[], Any],
        operation_name: str = "API request"
    ) -> Any:
        """
        Execute an API call with automatic rate limiting and exponential backoff.

        Args:
            api_call: Callable that executes the API request
            operation_name: Description of the operation for logging

        Returns:
            Any: Result from api_call

        Raises:
            RateLimitExceeded: If max backoff attempts exceeded
            Exception: Other API errors

        Example:
            >>> limiter = RateLimiter()
            >>> result = limiter.execute_with_backoff(
            ...     lambda: service.spreadsheets().get(spreadsheetId='abc').execute(),
            ...     "Get spreadsheet"
            ... )
        """
        from googleapiclient.errors import HttpError

        attempt = 0
        backoff_time = 2  # Start with 2 seconds

        while attempt <= self.max_backoff_attempts:
            try:
                # Wait if needed for rate limiting
                self.wait_if_needed()

                # Execute the API call
                return api_call()

            except HttpError as e:
                if e.resp.status == 429:  # Too Many Requests
                    if attempt >= self.max_backoff_attempts:
                        raise RateLimitExceeded(
                            f"Rate limit exceeded for {operation_name}. "
                            f"Max retry attempts ({self.max_backoff_attempts}) reached."
                        )

                    if self.enable_backoff:
                        self.total_backoffs += 1
                        if self.verbose:
                            print(f"[429 Error] Rate limit hit for {operation_name}. "
                                  f"Retrying in {backoff_time}s (attempt {attempt + 1}/{self.max_backoff_attempts})...")

                        time.sleep(backoff_time)
                        backoff_time *= 2  # Exponential backoff
                        attempt += 1
                    else:
                        raise
                else:
                    # Other HTTP errors, re-raise
                    raise
            except Exception as e:
                # Non-HTTP errors, re-raise
                raise

        raise RateLimitExceeded(f"Unexpected error in backoff loop for {operation_name}")

    def reset_consecutive_counter(self):
        """Reset the consecutive request counter (useful for batch operations)."""
        with self._lock:
            self._consecutive_requests = 0

    def get_stats(self) -> dict:
        """
        Get rate limiting statistics.

        Returns:
            dict: Statistics including total requests, delays, and backoffs
        """
        with self._lock:
            self._cleanup_old_requests()
            return {
                'total_requests': self.total_requests,
                'total_delays': self.total_delays,
                'total_backoffs': self.total_backoffs,
                'requests_in_last_minute': self._get_requests_in_window(60),
                'requests_in_last_100s': self._get_requests_in_window(100),
                'consecutive_requests': self._consecutive_requests,
                'limits': {
                    'requests_per_minute': self.requests_per_minute,
                    'requests_per_100s': self.requests_per_100s,
                    'auto_delay_threshold': self.auto_delay_threshold
                }
            }

    def print_stats(self):
        """Print rate limiting statistics."""
        stats = self.get_stats()
        print("\n" + "="*60)
        print("RATE LIMITER STATISTICS")
        print("="*60)
        print(f"Total Requests:          {stats['total_requests']}")
        print(f"Total Delays:            {stats['total_delays']}")
        print(f"Total 429 Backoffs:      {stats['total_backoffs']}")
        print(f"Requests (last minute):  {stats['requests_in_last_minute']} / {stats['limits']['requests_per_minute']}")
        print(f"Requests (last 100s):    {stats['requests_in_last_100s']} / {stats['limits']['requests_per_100s']}")
        print(f"Consecutive Requests:    {stats['consecutive_requests']} / {stats['limits']['auto_delay_threshold']}")
        print("="*60 + "\n")


# Global rate limiter instance (can be shared across sub-skills)
_global_limiter = None


def get_global_limiter(
    reset: bool = False,
    **kwargs
) -> RateLimiter:
    """
    Get or create global rate limiter instance.

    Args:
        reset: If True, create new instance even if one exists
        **kwargs: Arguments to pass to RateLimiter constructor

    Returns:
        RateLimiter: Global rate limiter instance

    Example:
        >>> limiter = get_global_limiter(verbose=True)
        >>> with limiter.limit():
        ...     # Make API call
    """
    global _global_limiter

    if reset or _global_limiter is None:
        _global_limiter = RateLimiter(**kwargs)

    return _global_limiter


if __name__ == "__main__":
    """
    Test rate limiter functionality.

    Usage:
        python scripts/rate_limiter.py
    """
    print("Testing Rate Limiter...")
    print("-" * 60)

    # Create rate limiter with aggressive limits for testing
    limiter = RateLimiter(
        requests_per_minute=10,
        requests_per_100s=20,
        auto_delay_threshold=5,
        auto_delay_seconds=0.5,
        verbose=True
    )

    # Simulate requests
    print("\nSimulating 15 requests...")
    for i in range(15):
        with limiter.limit():
            print(f"Request {i+1} executed")
            time.sleep(0.1)  # Simulate API call duration

    # Print statistics
    limiter.print_stats()

    print("[✓] Rate limiter test completed successfully!")
