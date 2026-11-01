# FastAPI router for Chat endpoints (v1)
import asyncio
from typing import AsyncIterator, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from common.logger import logger
from app.auth.dependencies import require_user
from app.auth.principal import Principal
from .model import  (
    ChatCreate,
    ChatSession,
    ChatDeleteResponse,
    ChatSessionStatus,
    StreamMessageCreate
)
from . import service

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("/", response_model=ChatSession, status_code=201)
async def create_chat(
    chat: ChatCreate,
    principal: Principal = Depends(require_user),
) -> ChatSession:
    """
    Create a new chat session with an optional system prompt.
    Returns a unique session_id to be used for subsequent messages.
    """
    return service.create_chat_session(chat, owner_subject=principal.subject)


@router.get("/{session_id}", response_model=ChatSessionStatus)
async def get_chat_session(
    session_id: str,
    principal: Principal = Depends(require_user),
) -> ChatSessionStatus:
    """
    Check if a chat session exists.
    Returns session status without processing any messages.
    """
    try:
        return service.get_chat_session_status(session_id, subject=principal.subject)
    except service.ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc


@router.post("/{session_id}/stream")
async def stream_message(
    session_id: str,
    message: StreamMessageCreate,
    principal: Principal = Depends(require_user),
) -> StreamingResponse:
    """
    Stream a chat response as Server-Sent Events (SSE).

    Yields SSE events in order: thinking_start, thinking_chunk(s), thinking_end,
    message_start, message_chunk(s), message_end.  On error yields an error event.
    """
    try:
        # Validate ownership before returning a StreamingResponse.
        # Raising here produces a normal JSON 404 rather than a broken SSE stream.
        service.get_chat_session_status(session_id, subject=principal.subject)

        logger.info(f"[stream_message] Starting stream: session_id={session_id} message={message.message[:80]}")

        async def event_generator() -> AsyncIterator[str]:
            try:
                async for chunk in service.stream_chat_response(
                    session_id, message.message, subject=principal.subject
                ):
                    yield chunk
            except asyncio.CancelledError:
                logger.warning(f"[stream_message] Client disconnected: session_id={session_id}")
                raise
            except Exception as exc:
                logger.error(f"[stream_message] Stream error: session_id={session_id} error={exc}")
                raise

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except service.ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/metrics/stream", tags=["metrics"])
async def stream_metrics() -> dict[str, Any]:
    """
    Return current streaming metrics (starts, completions, errors, disconnects,
    total_duration_seconds).
    """
    return service.get_stream_metrics()


@router.delete("/{session_id}", response_model=ChatDeleteResponse)
async def delete_chat(
    session_id: str,
    principal: Principal = Depends(require_user),
) -> ChatDeleteResponse:
    """
    End and delete a chat session.
    """
    try:
        return service.delete_chat_session(session_id, subject=principal.subject)
    except service.ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
