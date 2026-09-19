from atlassian import Confluence
from common.logger import logger
from connectors.producers.github.retry_with_backoff import retry_with_backoff

def fetch_page_body(confluence: Confluence, page_id: str) -> str:
    """Fetch the storage format body of a page/blogpost."""
    logger.debug(f"Fetching page body for page_id={page_id}")
    # Retry rate-limit (HTTP 429) and transient network errors with
    # exponential backoff so a momentary connectivity loss does not abort
    # the body fetch.
    page = retry_with_backoff(
        lambda: confluence.get_page_by_id(page_id, expand='body.storage')  # type: ignore[no-untyped-call]
    )
    body = page.get('body', {}).get('storage', {}).get('value', '')
    logger.debug(f"Fetched page body for page_id={page_id} (length={len(body)})")
    return body  # type: ignore[no-any-return]
