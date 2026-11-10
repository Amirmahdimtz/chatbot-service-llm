"""Stage 3 request validation and forward-compatible history contracts."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.application.chat.dtos.chat_dto import ChatRequestDto, SourcesDto
from src.application.conversation.dtos.conversation_dto import (
    ConversationCreateDto, ConversationListDto, ConversationMessageDto
)


def test_chat_message_normalization_and_uuid_contract():
    payload = ChatRequestDto(message="  سلام  ")
    assert payload.message == "سلام"
    assert payload.conversation_id is None
    assert ChatRequestDto(message="a", conversation_id=UUID(int=1)).conversation_id == UUID(int=1)


@pytest.mark.parametrize("payload", [
    {"message": ""}, {"message": " \n "}, {"message": "x" * 1001},
    {"message": 123}, {"message": "a", "audience": "internal"},
    {"message": "a", "conversation_id": "malformed"},
    {"message": "a", "client_message_id": "forged"},
])
def test_invalid_chat_messages_rejected(payload):
    with pytest.raises(ValidationError):
        ChatRequestDto.model_validate(payload)


def test_history_and_source_contracts_do_not_imply_persistence():
    assert ConversationCreateDto(title="Synthetic").title == "Synthetic"
    assert ConversationListDto(items=[]).items == []
    assert SourcesDto(documents=[]).documents == []
    with pytest.raises(ValidationError):
        ConversationMessageDto.model_validate({
            "id": str(UUID(int=1)), "role": "alien", "content": "x",
            "status": "completed", "created_at": "2026-11-10T00:00:00Z"
        })
