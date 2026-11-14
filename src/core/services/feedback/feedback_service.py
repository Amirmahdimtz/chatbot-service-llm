"""Feedback semantics and ownership checks are enforced at the repository boundary."""
from __future__ import annotations

from src.core.services.chat.chat_identity_service import ChatIdentity, scoped_conversation_owner
from src.infrastructure.di.inject import inject
from src.infrastructure.models.feedback import Feedback
from src.infrastructure.repositories.feedback.feedback_repository import FeedbackRepository


@inject
class FeedbackService:
    def __init__(self, feedback_repository: FeedbackRepository):
        self._feedback = feedback_repository

    async def create_async(
        self, message_id: str, identity: ChatIdentity, kind: str, comment: str | None
    ) -> Feedback:
        return await self._feedback.create_scoped_async(
            message_id, scoped_conversation_owner(identity), identity.audience, kind, comment
        )
