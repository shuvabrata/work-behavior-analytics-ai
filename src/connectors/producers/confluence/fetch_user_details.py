from typing import Any, Dict
from atlassian import Confluence
from common.logger import logger
from connectors.producers.github.retry_with_backoff import (
    WbaRetryTimeoutError,
    retry_with_backoff,
)

def fetch_user_details(confluence: Confluence, account_id: str) -> Dict[str, Any]:
    """Fetch user details from Confluence REST API."""
    logger.info(f"Fetching user details for account_id={account_id}")
    try:
        # Retry rate-limit (HTTP 429) and transient network errors with
        # exponential backoff so a momentary connectivity loss does not drop
        # a user's details.
        response = retry_with_backoff(
            lambda: confluence.get(f"/rest/api/user?accountId={account_id}")
        )
        logger.debug(f"Fetched user details for account_id={account_id}")
        return response
    except WbaRetryTimeoutError:
        raise
    except Exception as exc:
        logger.warning(f"Failed to fetch user details for account_id={account_id}: {exc}")
        return {}
