from typing import AsyncIterator, Any

from app.ai_agent.ai_agent import (
    new_chat,
    end_chat,
    stream_chat,
    get_streaming_metrics,
    get_chat_owner,
    _chat_sessions,
)
from .model import ChatCreate, ChatSession, ChatDeleteResponse, ChatSessionStatus


class ChatSessionNotFoundError(Exception):
    """The session does not exist, or the caller does not own it.

    Deliberately one error for both cases: distinguishing them would let a
    caller probe for session ids that exist.
    """


def _assert_owned(session_id: str, subject: str) -> None:
    """Raise ``ChatSessionNotFoundError`` unless *subject* owns *session_id*."""
    owner = get_chat_owner(session_id)
    if owner is None or owner != subject:
        raise ChatSessionNotFoundError(session_id)


def create_chat_session(chat: ChatCreate, *, owner_subject: str) -> ChatSession:
    """Create a new chat session owned by *owner_subject*"""
    session_id = new_chat(system_prompt=chat.system_prompt or "", owner_subject=owner_subject)
    return ChatSession(session_id=session_id)


def delete_chat_session(session_id: str, *, subject: str) -> ChatDeleteResponse:
    """End and delete a chat session the caller owns"""
    _assert_owned(session_id, subject)
    end_chat(session_id)
    return ChatDeleteResponse(session_id=session_id, deleted=True)


def get_chat_session_status(session_id: str, *, subject: str) -> ChatSessionStatus:
    """Check if a chat session exists and the caller owns it, and return its status"""
    _assert_owned(session_id, subject)
    message_count = len(_chat_sessions.get(session_id, []))

    return ChatSessionStatus(
        session_id=session_id,
        exists=True,
        message_count=message_count
    )


async def stream_chat_response(
    session_id: str, user_message: str, *, subject: str
) -> AsyncIterator[str]:
    """Async generator that proxies stream_chat for use in StreamingResponse."""
    _assert_owned(session_id, subject)
    async for chunk in stream_chat(session_id=session_id, user_message=user_message):
        yield chunk


def get_stream_metrics() -> dict[str, Any]:
    """Return a copy of the current streaming metrics."""
    return get_streaming_metrics()
