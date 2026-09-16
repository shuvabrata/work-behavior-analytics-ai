import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from atlassian import Confluence  # type: ignore[import-untyped]

from common.logger import logger
from connectors.producers.confluence.fetch_spaces import fetch_spaces
from connectors.producers.confluence.fetch_content_likes import fetch_content_likes
from connectors.producers.confluence.fetch_page_comments import fetch_page_comments
from connectors.producers.confluence.fetch_user_details import fetch_user_details
from connectors.producers.github.retry_with_backoff import retry_with_backoff


def _normalize_space_key(key: str) -> str:
    return key.strip().upper()


def _parse_last_modified(content: Dict[str, Any]) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime from a content item's version.when field."""
    when = content.get("version", {}).get("when")
    if not when:
        return None
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fetch_space_pages(
    confluence: Confluence,
    space_key: str,
    since_date: datetime,
    page_size: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch all pages and blogposts in a space modified on or after *since_date*.

    Uses the storage-layer ``/rest/api/space/{key}/content`` endpoint instead of
    CQL search.  This avoids Confluence Cloud search-index gaps that cause CQL
    pagination to silently skip pages with large numeric IDs.

    **Goal:** return only content whose ``version.when`` (last modified date)
    is on or after *since_date*, so the producer re-processes only pages that
    have changed since the last sync cursor.

    **Important — full scan required:** The storage API returns content in
    creation order (oldest first) and does not support server-side date
    filtering.  Because a page created years ago could have been edited
    recently, every page in the space must be fetched and its last-modified
    date checked locally.  For a large space (e.g. 2,000 pages) with a narrow
    time window (e.g. 60 days), most batches will have ``filtered_total=0``
    until the final pages are reached — that is expected and correct.
    """
    if since_date.tzinfo is None:
        since_date = since_date.replace(tzinfo=timezone.utc)

    results: List[Dict[str, Any]] = []
    for content_type in ("page", "blogpost"):
        start = 0
        while True:
            # Retry rate-limit (HTTP 429) and transient network errors with
            # exponential backoff so a momentary connectivity loss does not
            # abort the space content fetch. Bind content_type/start as default
            # args to avoid late-binding closure issues in the lambda.
            response = retry_with_backoff(
                lambda ct=content_type, st=start: confluence.get(
                    f"/rest/api/space/{space_key}/content/{ct}",
                    params={
                        "expand": "version,history,status,ancestors,space",
                        "limit": page_size,
                        "start": st,
                    },
                )
            )
            if not isinstance(response, dict):
                logger.debug(
                    f"Exiting loop for space {space_key} content_type {content_type}: unexpected response format"
                )
                break
            batch = response.get("results", [])
            if not batch:
                logger.debug(f"Exiting loop for space {space_key} content_type {content_type}: no more results")
                break

            for item in batch:
                last_mod = _parse_last_modified(item)
                if last_mod is None or last_mod >= since_date:
                    results.append(item)

            logger.debug(
                f"Space {space_key} {content_type}: fetched batch start={start} size={len(batch)} (filtered_total="
                f"{len(results)})"
            )
            start += len(batch)
            if len(batch) < page_size:
                break

    logger.info(f"Space {space_key}: {len(results)} content items on or after {since_date.isoformat()}")
    return results

async def get_spaces(confluence) -> List[Dict[str, Any]]:
    logger.debug("Dispatching Confluence space fetch to worker thread")
    spaces = await asyncio.to_thread(fetch_spaces, confluence)
    logger.info(f"Helper fetched {len(spaces)} spaces from Confluence")
    return spaces


async def get_space_pages(
    confluence,
    space_key: str,
    since_date: datetime,
) -> List[Dict[str, Any]]:
    """Async wrapper around fetch_space_pages."""
    logger.debug(f"Dispatching storage-layer content fetch for space={space_key} since={since_date.isoformat()}")
    results = await asyncio.to_thread(fetch_space_pages, confluence, space_key, since_date)
    logger.info(f"Helper fetched {len(results)} content items for space={space_key}")
    return results


async def get_comments(confluence, content_id: str, content_type: str = "page") -> List[Dict[str, Any]]:
    logger.debug(f"Dispatching comment fetch to worker thread for content_type={content_type} content_id={content_id}")
    comments = await asyncio.to_thread(fetch_page_comments, confluence, content_id, content_type)
    logger.info(f"Helper fetched {len(comments)} comments for content_type={content_type} content_id={content_id}")
    return comments

async def get_likes(confluence, content_id: str, content_type: str = "page") -> List[Dict[str, Any]]:
    logger.debug(f"Dispatching like fetch to worker thread for content_type={content_type} content_id={content_id}")
    likes = await asyncio.to_thread(fetch_content_likes, confluence, content_id, content_type)
    logger.info(f"Helper fetched {len(likes)} likes for content_type={content_type} content_id={content_id}")
    return likes

async def get_user_details_async(confluence, account_id: str) -> Dict[str, Any]:
    logger.debug(f"Dispatching user detail fetch to worker thread for account_id={account_id}")
    user_details = await asyncio.to_thread(fetch_user_details, confluence, account_id)
    logger.info(f"Helper fetched user details for account_id={account_id} (found={bool(user_details)})")
    return user_details
