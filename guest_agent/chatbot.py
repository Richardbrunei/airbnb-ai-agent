"""
Guest Chatbot - AI-powered guest communication.

Handles incoming guest messages, generates contextual responses using
an LLM (z.ai GLM by default, OpenAI optional), and decides whether
to auto-reply or escalate to a human.
"""

import json
import logging
import os
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
    reasoning: str = ""


# ── LLM Provider Config ───────────────────────────────────────────────────────

@dataclass
class LLMConfig:
    """Configuration for the LLM provider."""
    provider: str = "zai"         # "zai" or "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @classmethod
    def zai(cls, api_key: str = "", model: str = "glm-4"):
        return cls(
            provider="zai",
            api_key=api_key or os.getenv("ZAI_API_KEY", ""),
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            model=model,
        )

    @classmethod
    def openai(cls, api_key: str = "", model: str = "gpt-4o"):
        return cls(
            provider="openai",
            api_key=api_key or os.getenv("OPENAI_API_KEY", ""),
            base_url="https://api.openai.com/v1",
            model=model,
        )

    @classmethod
    def from_env(cls):
        """Auto-detect provider from environment variables."""
        zai_key = os.getenv("ZAI_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")
        provider = os.getenv("LLM_PROVIDER", "").lower()

        if provider == "openai" or (openai_key and not zai_key):
            return cls.openai(api_key=openai_key)
        return cls.zai(api_key=zai_key)

    def get_client(self):
        """Create an OpenAI-compatible client for this provider."""
        from openai import OpenAI
        if not self.api_key:
            raise ValueError(
                f"No API key for {self.provider}. Set "
                f"{'ZAI_API_KEY' if self.provider == 'zai' else 'OPENAI_API_KEY'} "
                f"environment variable."
            )
        return OpenAI(api_key=self.api_key, base_url=self.base_url)


# ── System Prompt Builder ─────────────────────────────────────────────────────

def build_system_prompt(knowledge_base: dict, listing_id: str = "") -> str:
    """
    Build a system prompt from the knowledge base.

    Includes property details, amenities, house rules, FAQ, and policies.
    Instructs the AI on tone, response format, and escalation rules.
    """
    properties = knowledge_base.get("properties", [])
    prop = properties[0] if properties else {}

    # Pick property by listing_id if specified
    if listing_id:
        for p in properties:
            if p.get("id") == listing_id:
                prop = p
                break

    name = prop.get("name", "our property")
    check_in = prop.get("check_in_time", "3:00 PM")
    check_out = prop.get("check_out_time", "11:00 AM")
    address = prop.get("address", "")

    # Amenities
    amenities = prop.get("amenities", {})
    amenity_lines = []
    if amenities.get("wifi"):
        wifi_net = amenities.get("wifi_network", "")
        wifi_pw = amenities.get("wifi_password", "")
        wifi_str = f"WiFi (network: {wifi_net}, password: {wifi_pw})" if wifi_net else "WiFi"
        amenity_lines.append(f"  - {wifi_str}")
    if amenities.get("parking"):
        pi = amenities.get("parking_instructions", "")
        amenity_lines.append(f"  - Free parking{f' ({pi})' if pi else ''}")
    if amenities.get("pool"):
        amenity_lines.append("  - Pool")
    if amenities.get("gym"):
        amenity_lines.append("  - Gym/Fitness center")
    if amenities.get("kitchen"):
        amenity_lines.append("  - Full kitchen")
    if amenities.get("laundry"):
        amenity_lines.append("  - Laundry (washer & dryer)")
    if amenities.get("ac"):
        amenity_lines.append("  - Air conditioning")
    if amenities.get("heating"):
        amenity_lines.append("  - Heating")
    amenities_str = "\n".join(amenity_lines) if amenity_lines else "  - Standard amenities"

    # House rules
    rules = prop.get("house_rules", [])
    rules_str = "\n".join(f"  - {r}" for r in rules) if rules else "  - Standard house rules apply"

    # Local tips
    tips = prop.get("local_tips", {})
    tips_lines = []
    if tips.get("grocery"):
        tips_lines.append(f"  - Nearest grocery: {tips['grocery']}")
    if tips.get("restaurants"):
        for r in tips["restaurants"]:
            tips_lines.append(f"  - Restaurant: {r}")
    if tips.get("transport"):
        tips_lines.append(f"  - Transport: {tips['transport']}")
    tips_str = "\n".join(tips_lines) if tips_lines else "  - (no local tips configured)"

    # FAQ
    faqs = prop.get("faq", [])
    faq_str = ""
    if faqs:
        faq_lines = []
        for faq in faqs:
            faq_lines.append(f"  Q: {faq['q']}\n  A: {faq['a']}")
        faq_str = "\n".join(faq_lines)

    # Policies
    policies = knowledge_base.get("policies", {})
    policy_lines = []
    for key, val in policies.items():
        policy_lines.append(f"  - {key.replace('_', ' ').title()}: {val}")
    policies_str = "\n".join(policy_lines) if policy_lines else "  - (no specific policies)"

    return f"""You are a friendly, helpful Airbnb host assistant responding to guest messages on behalf of the host at {name}.

PROPERTY DETAILS:
  Name: {name}
  Address: {address or '(on file)'}
  Check-in: {check_in}
  Check-out: {check_out}

AMENITIES:
{amenities_str}

HOUSE RULES:
{rules_str}

LOCAL TIPS:
{tips_str}

POLICIES:
{policies_str}

FREQUENTLY ASKED QUESTIONS:
{faq_str if faq_str else "  (none configured)"}

RESPONSE GUIDELINES:
- Be warm, concise, and professional. Like a real host texting back.
- Answer based ONLY on the property information above. Don't invent details.
- If the guest asks something you don't know (specific availability, booking changes, refunds), say you'll check with the host and get back to them.
- If the guest reports a problem (broken item, noise, safety issue), respond with empathy, tell them you're notifying the host immediately, and DO NOT try to troubleshoot — that requires the host.
- Keep responses short. Guests are on mobile. 1-3 sentences usually.
- Don't use exclamation marks more than once per message.
- Sign off as "The team at {name}" only on longer messages. For quick replies, no sign-off needed.

Respond with a JSON object:
{{"reply": "your response text here", "confidence": 0.0-1.0, "should_escalate": true/false}}

- confidence: how certain you are this answer is complete and correct (0.0-1.0)
- should_escalate: true if the host needs to handle this personally (issues, booking changes, complaints, anything sensitive)
"""


# ── Chatbot ───────────────────────────────────────────────────────────────────

class GuestChatbot:
    """AI-powered guest communication agent."""

    def __init__(
        self,
        knowledge_base_path: str = "guest_agent/knowledge_base.json",
        llm_config: Optional[LLMConfig] = None,
        escalation_threshold: float = 0.7,
    ):
        self.knowledge_base_path = knowledge_base_path
        self.knowledge_base: dict = {}
        self.llm_config = llm_config or LLMConfig.from_env()
        self.escalation_threshold = escalation_threshold
        self._client = None
        self._load_knowledge_base()

    def _load_knowledge_base(self):
        """Load property knowledge base from JSON file."""
        path = Path(self.knowledge_base_path)
        if path.exists():
            self.knowledge_base = json.loads(path.read_text())
            n_props = len(self.knowledge_base.get("properties", []))
            logger.info(f"Loaded knowledge base ({n_props} properties)")
        else:
            logger.warning(f"Knowledge base not found at {path}")

    def _get_client(self):
        """Lazily initialize the LLM client."""
        if self._client is None:
            self._client = self.llm_config.get_client()
        return self._client

    async def initialize(self):
        """Initialize the chatbot (validate API key, etc.)."""
        # Test API key by creating client
        self._get_client()
        logger.info(f"Guest chatbot initialized (provider: {self.llm_config.provider}, model: {self.llm_config.model})")

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

        # 2. Issues always escalate
        if msg_type == MessageType.ISSUE:
            draft = await self._generate_response(message, msg_type)
            draft.auto_send = False
            draft.message_type = MessageType.ESCALATE
            draft.reasoning = "Issue/complaint detected — requires host attention"
            return draft

        # 3. Generate response
        response = await self._generate_response(message, msg_type)

        # 4. Decide auto-send based on confidence
        if response.confidence >= self.escalation_threshold and not response.message_type == MessageType.ESCALATE:
            response.auto_send = True
            response.reasoning = f"High confidence ({response.confidence:.0%}) — auto-reply approved"
        else:
            response.auto_send = False
            response.reasoning = f"Confidence {response.confidence:.0%} below threshold {self.escalation_threshold:.0%} — review before sending"

        return response

    def _classify_message(self, text: str) -> MessageType:
        """Classify a guest message into a category."""
        text_lower = text.lower()

        if any(w in text_lower for w in ["problem", "broken", "issue", "complaint", "noisy",
                                          "not working", "dirty", "smell", "leak", "bug",
                                          "unsafe", "emergency", "angry", "refund", "cancel"]):
            return MessageType.ISSUE
        if any(w in text_lower for w in ["check in", "check-in", "checkin", "arrival",
                                          "keys", "door code", "lockbox", "getting in",
                                          "early arrival", "late check"]):
            return MessageType.CHECK_IN
        if any(w in text_lower for w in ["wifi", "wi-fi", "parking", "pool", "kitchen",
                                          "amenities", "tv", "air condition", "heater",
                                          "towels", "washer", "dryer", "coffee"]):
            return MessageType.AMENITY
        if any(w in text_lower for w in ["book", "available", "price", "discount",
                                          "dates", "weekend", "extend", "stay longer",
                                          "extra night", "pet", "dog", "cat"]):
            return MessageType.INQUIRY

        return MessageType.GENERAL

    async def _generate_response(self, message: GuestMessage, msg_type: MessageType) -> AgentResponse:
        """Generate an AI response for a guest message."""
        import asyncio

        system_prompt = build_system_prompt(self.knowledge_base, message.listing_id)

        user_prompt = f"""Guest name: {message.guest_name}
Message: "{message.message}"

Respond to this guest message following the guidelines. Return only the JSON object."""

        try:
            client = self._get_client()
            # Run sync call in thread
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=self.llm_config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=400,
            )

            raw_response = completion.choices[0].message.content.strip()

            # Parse JSON from response (handle markdown code fences)
            if raw_response.startswith("```"):
                # Strip code fences
                lines = raw_response.split("\n")
                raw_response = "\n".join(l for l in lines if not l.strip().startswith("```"))

            try:
                parsed = json.loads(raw_response)
            except json.JSONDecodeError:
                # If JSON parse fails, use raw text as reply
                return AgentResponse(
                    reply=raw_response,
                    message_type=msg_type,
                    auto_send=False,
                    confidence=0.3,
                    reasoning="LLM response was not valid JSON — low confidence, review needed",
                )

            reply = parsed.get("reply", "").strip()
            confidence = float(parsed.get("confidence", 0.5))
            should_escalate = parsed.get("should_escalate", False)

            if should_escalate:
                msg_type = MessageType.ESCALATE

            return AgentResponse(
                reply=reply,
                message_type=msg_type,
                confidence=confidence,
            )

        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return AgentResponse(
                reply="",
                message_type=MessageType.ESCALATE,
                confidence=0.0,
                reasoning=f"LLM error: {e}",
            )
