"""
Rate limiter module for controlling API request rates to prevent 429 errors.
Implements thread-safe rate limiting with queue management.
"""

import time
import threading
from collections import deque
from typing import Callable, Any, Optional
import requests


class RateLimiter:
    """
    Thread-safe rate limiter that ensures no more than max_requests per time_window.
    """

    def __init__(self, max_requests: int = 5, time_window: float = 1.0):
        """
        Initialize the rate limiter.

        :param max_requests: Maximum number of requests allowed per time window
        :param time_window: Time window in seconds (default: 1.0 for per-second limiting)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()  # Store timestamps of recent requests
        self.lock = threading.Lock()

    def _cleanup_old_requests(self):
        """Remove request timestamps older than the time window."""
        current_time = time.time()
        while self.requests and current_time - self.requests[0] > self.time_window:
            self.requests.popleft()

    def wait_if_needed(self):
        """
        Block the current thread if rate limit would be exceeded.
        Ensures thread-safe access to the request queue.
        """
        wait_time = 0

        with self.lock:
            current_time = time.time()
            self._cleanup_old_requests()

            if len(self.requests) >= self.max_requests:
                # Calculate how long to wait until the oldest request expires
                oldest_request = self.requests[0]
                wait_time = self.time_window - (current_time - oldest_request)
                # Ensure we wait at least a small amount to prevent tight loops
                wait_time = max(wait_time, 0.1)

        # Sleep outside the lock if needed
        if wait_time > 0:
            time.sleep(wait_time)

        # Acquire lock again to record the request
        with self.lock:
            self._cleanup_old_requests()
            self.requests.append(time.time())


class RetryableRateLimiter:
    """
    Rate limiter with built-in retry logic and exponential backoff for API calls.
    """

    def __init__(self, max_requests: int = 5, time_window: float = 1.0,
                 max_retries: int = 4, base_delay: float = 1.0):
        """
        Initialize the retryable rate limiter.

        :param max_requests: Maximum requests per time window
        :param time_window: Time window in seconds
        :param max_retries: Maximum number of retry attempts
        :param base_delay: Base delay for exponential backoff (seconds)
        """
        self.rate_limiter = RateLimiter(max_requests, time_window)
        self.max_retries = max_retries
        self.base_delay = base_delay

    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        """
        Execute a function with rate limiting and retry logic.

        :param func: Function to execute (should be a requests call)
        :param args: Arguments to pass to the function
        :param kwargs: Keyword arguments to pass to the function
        :return: Function result or None if all retries failed
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                # Apply rate limiting before making the request
                self.rate_limiter.wait_if_needed()

                # Execute the function
                result = func(*args, **kwargs)

                # If we get here, the request was successful
                return result

            except requests.exceptions.HTTPError as e:
                last_exception = e

                # Check if it's a 429 error
                if hasattr(e, 'response') and e.response.status_code == 429:
                    if attempt < self.max_retries:
                        # Calculate exponential backoff delay
                        delay = self.base_delay * (2 ** attempt)
                        print(f"Rate limited (429), retrying in {delay} seconds... (attempt {attempt + 1}/{self.max_retries + 1})")
                        time.sleep(delay)
                        continue
                    else:
                        print(f"Max retries reached for 429 error: {e}")
                        break
                else:
                    # For non-429 HTTP errors, don't retry
                    print(f"HTTP error (non-429): {e}")
                    break

            except requests.exceptions.RequestException as e:
                last_exception = e

                if attempt < self.max_retries:
                    # For other request exceptions, retry with exponential backoff
                    delay = self.base_delay * (2 ** attempt)
                    print(f"Request failed, retrying in {delay} seconds... (attempt {attempt + 1}/{self.max_retries + 1}): {e}")
                    time.sleep(delay)
                    continue
                else:
                    print(f"Max retries reached for request error: {e}")
                    break

        # If we get here, all retries failed
        print(f"All retry attempts failed. Last error: {last_exception}")
        return None


# Global rate limiter instance for calcus.ru API
calcus_rate_limiter = RetryableRateLimiter(
    max_requests=2,     # 2 requests (more conservative)
    time_window=1.0,    # per second
    max_retries=3,      # up to 3 retries (less aggressive)
    base_delay=2.0      # starting with 2 second delay (longer backoff)
)

# Global rate limiter instance for pan-auto.ru API
panauto_rate_limiter = RetryableRateLimiter(
    max_requests=5,     # 5 requests per second
    time_window=1.0,    # per second
    max_retries=3,      # up to 3 retries
    base_delay=1.0      # starting with 1 second delay
)