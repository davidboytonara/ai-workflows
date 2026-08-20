"""
Retry handler with exponential backoff for Google API calls.

Handles rate limiting and transient errors gracefully.
"""

import time
import random
import logging
from typing import Callable, Any, Optional
from googleapiclient.errors import HttpError


logger = logging.getLogger(__name__)


class RetryExhausted(Exception):
    """Raised when maximum retry attempts are exhausted."""
    pass


def execute_with_retry(request_func: Callable, max_retries: int = 3,
                      initial_delay: float = 1.0, max_delay: float = 32.0,
                      exponential_base: float = 2.0, jitter: bool = True) -> Any:
    """
    Execute API request with exponential backoff retry.

    Args:
        request_func: Function that returns an API request object
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Add random jitter to prevent thundering herd

    Returns:
        API response

    Raises:
        RetryExhausted: When max retries are exceeded
        HttpError: For non-retryable errors

    Example:
        >>> request = service.presentations().get(presentationId=id)
        >>> response = execute_with_retry(lambda: request)
    """
    delay = initial_delay

    for attempt in range(max_retries + 1):
        try:
            # Execute the request
            request = request_func()
            response = request.execute()
            return response

        except HttpError as e:
            error_code = e.resp.status
            error_reason = getattr(e, 'reason', str(e))

            # Check if error is retryable
            if error_code in [429, 500, 502, 503, 504]:
                if attempt < max_retries:
                    # Calculate backoff delay
                    sleep_time = min(delay, max_delay)

                    # Add jitter to prevent thundering herd
                    if jitter:
                        sleep_time = sleep_time * (0.5 + random.random())

                    logger.warning(
                        f"Retryable error {error_code}: {error_reason}. "
                        f"Retry {attempt + 1}/{max_retries} after {sleep_time:.2f}s"
                    )

                    time.sleep(sleep_time)

                    # Exponential backoff
                    delay *= exponential_base

                    continue
                else:
                    logger.error(f"Max retries ({max_retries}) exceeded for error {error_code}")
                    raise RetryExhausted(
                        f"Maximum retry attempts ({max_retries}) exceeded. "
                        f"Last error: {error_code} - {error_reason}"
                    ) from e
            else:
                # Non-retryable error
                logger.error(f"Non-retryable error {error_code}: {error_reason}")
                raise

        except Exception as e:
            # Unexpected error
            logger.error(f"Unexpected error during API call: {str(e)}")
            raise

    # Should never reach here
    raise RetryExhausted("Retry loop completed unexpectedly")


def batch_execute_with_retry(service: Any, presentation_id: str, requests: list,
                             batch_size: int = 500, max_retries: int = 3) -> list:
    """
    Execute batch requests with retry and chunking.

    Args:
        service: Google Slides service instance
        presentation_id: Presentation ID
        requests: List of API requests
        batch_size: Maximum requests per batch (Google limit: 1000)
        max_retries: Maximum retry attempts per batch

    Returns:
        List of batch responses

    Example:
        >>> requests = [{'createSlide': {...}}, {'insertText': {...}}]
        >>> responses = batch_execute_with_retry(service, pres_id, requests)
    """
    responses = []

    # Split requests into batches
    for i in range(0, len(requests), batch_size):
        batch = requests[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(requests) + batch_size - 1) // batch_size

        logger.info(f"Executing batch {batch_num}/{total_batches} ({len(batch)} requests)")

        # Execute batch with retry
        def make_batch_request():
            return service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={'requests': batch}
            )

        try:
            response = execute_with_retry(make_batch_request, max_retries=max_retries)
            responses.append(response)
            logger.info(f"Batch {batch_num}/{total_batches} completed successfully")

        except RetryExhausted as e:
            logger.error(f"Failed to execute batch {batch_num}/{total_batches}: {str(e)}")
            raise

    return responses


def rate_limit_aware_execute(requests_list: list, service: Any, presentation_id: str,
                             requests_per_minute: int = 300,
                             requests_per_user_minute: int = 60) -> list:
    """
    Execute requests with rate limit awareness.

    Google Slides API limits:
    - 300 requests per minute per project
    - 60 requests per user per minute

    Args:
        requests_list: List of API requests
        service: Google Slides service instance
        presentation_id: Presentation ID
        requests_per_minute: Project rate limit
        requests_per_user_minute: User rate limit

    Returns:
        List of responses
    """
    # Use the more restrictive limit
    limit = min(requests_per_minute, requests_per_user_minute)

    # Calculate delay between batches to stay under limit
    delay_between_batches = 60.0 / limit if limit > 0 else 0

    responses = []
    total_requests = len(requests_list)

    logger.info(f"Executing {total_requests} requests with rate limit {limit}/min")

    for idx, request_batch in enumerate(requests_list):
        # Execute batch
        response = execute_with_retry(
            lambda: service.presentations().batchUpdate(
                presentationId=presentation_id,
                body={'requests': [request_batch] if not isinstance(request_batch, list) else request_batch}
            )
        )
        responses.append(response)

        # Sleep to respect rate limits (except for last batch)
        if idx < total_requests - 1 and delay_between_batches > 0:
            logger.debug(f"Sleeping {delay_between_batches:.2f}s for rate limiting")
            time.sleep(delay_between_batches)

    return responses


def handle_quota_exceeded(error: HttpError, notification_email: Optional[str] = None):
    """
    Handle quota exceeded errors.

    Args:
        error: HttpError with quota exceeded
        notification_email: Email to notify (optional)
    """
    error_message = (
        "Google Slides API quota exceeded. "
        "Please wait before making more requests or request a quota increase."
    )

    logger.error(error_message)
    logger.error(f"Error details: {error.resp.status} - {error.content}")

    if notification_email:
        try:
            from .email_notifier import send_error_notification
            send_error_notification(
                to_email=notification_email,
                subject="Google Slides API Quota Exceeded",
                error_details=error_message
            )
        except ImportError:
            logger.warning("Email notifier not available")


if __name__ == '__main__':
    # Test examples
    logging.basicConfig(level=logging.INFO)

    def mock_request_success():
        """Mock successful request."""
        class MockRequest:
            def execute(self):
                return {'status': 'success'}
        return MockRequest()

    def mock_request_retry():
        """Mock request that fails twice then succeeds."""
        attempt = 0
        def make_request():
            nonlocal attempt
            attempt += 1
            class MockRequest:
                def execute(self):
                    if attempt < 3:
                        from googleapiclient.errors import HttpError
                        import httplib2
                        resp = httplib2.Response({'status': 429})
                        raise HttpError(resp, b'Rate limit exceeded')
                    return {'status': 'success', 'attempt': attempt}
            return MockRequest()
        return make_request

    # Test successful request
    print("Test 1: Successful request")
    result = execute_with_retry(mock_request_success)
    print(f"Result: {result}")

    # Test retry logic
    print("\nTest 2: Request with retries")
    result = execute_with_retry(mock_request_retry())
    print(f"Result: {result}")
