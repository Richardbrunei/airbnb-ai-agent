"""
Guest Chatbot - AI-powered guest communication.

Handles incoming guest messages, generates contextual responses using
an AI model, and decides whether to auto-reply or escalate to a human.
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Categorized guest message types."""
    INQUIRY = "inquiry"           # Pre-booking questions
    CHECK_IN = "check_in"         # Check-in instructions
    AMENITY = "amenity"           # Questions about amenities
    ISSUE = "issue"               # Problems/complaints
    GENERAL = "general"           # Other
    ESCALATE = "escalate"         # Requires human attention


@dataclass
class GuestMessage:
    """An incoming guest message."""
    guest_name: str
    message: str
    thread_id: str = ""
    listing_id: str = ""
    language: str = "en"


@dataclass
class AgentResponse:
    """The agent's response to a guest message."""
    reply: str
    message_type: MessageType
    auto_send: bool = False       # Whether to auto-send or escalate
    confidence: float = 0.0


class GuestChatbot:
    """AI-powered guest communication agent."""

    def __init__(self, knowledge_base_path: str = "guest_agent/knowledge_base.json"):
        self.knowledge_base_path = knowledge_base_path
        self.knowledge_base: dict = {}
        self._load_knowledge_base()

    def _load_knowledge_base(self):
        """Load property knowledge base from JSON file."""
        path = Path(self.knowledge_base_path)
        if path.exists():
            self.knowledge_base = json.loads(path.read_text())
            logger.info(f"Loaded knowledge base ({len(self.knowledge_base)} entries)")
        else:
            logger.warning(f"Knowledge base not found at {path}")

    async def initialize(self):
        """Initialize the chatbot (load models, connect APIs, etc.)."""
        logger.info("Guest chatbot initialized")

    async def handle_message(self, message: GuestMessage) -> AgentResponse:
        """
        Process an incoming guest message and generate a response.

        Args:
            message: The guest's incoming message

        Returns:
            AgentResponse with reply text and routing decision
        """
        # 1. Classify message type
        msg_type = self._classify_message(message.message)
        logger.info(f"Classified message from {message.guest_name} as {msg_type.value}")

        # 2. Generate response (TODO: integrate with AI model)
        response = await self._generate_response(message, msg_type)

        return response

    def _classify_message(self, text: str) -> MessageType:
        """Classify a guest message into a category."""
        text_lower = text.lower()

        if any(w in text_lower for w in ["check in", "check-in", "arrival", "keys"]):
            return MessageType.CHECK_IN
        if any(w in text_lower for w in ["wifi", "parking", "pool", "kitchen", "amenities"]):
            return MessageType.AMENITY
        if any(w in text_lower for w in ["problem", "broken", "issue", "complaint", "noisy"]):
            return MessageType.ISSUE
        if any(w in text_lower for w in ["book", "available", "price", "discount"]):
            return MessageType.INQUIRY

        return MessageType.GENERAL

    async def _generate_response(self, message: GuestMessage, msg_type: MessageType) -> AgentResponse:
        """Generate an AI response for a guest message."""
        # TODO: Integrate with ChatGPT/OpenAI API
        # For now, return a placeholder

        if msg_type == MessageType.ISSUE:
            return AgentResponse(
                reply="",
                message_type=MessageType.ESCALATE,
                auto_send=False,
                confidence=0.0,
            )

        return AgentResponse(
            reply="Thank you for your message. We'll get back to you shortly!",
            message_type=msg_type,
            auto_send=False,
            confidence=0.0,
        )
