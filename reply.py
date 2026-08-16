#!/usr/bin/env python3
"""
reply.py — Draft AI replies to Airbnb guest messages.

Uses the LLM provider configured in the environment (z.ai by default)
with the property knowledge base to generate contextual responses.

Usage:
  # Interactive mode (prompts for message)
  python reply.py

  # Pass message directly
  python reply.py --message "Hi, what time is check-in?"

  # Specify property by index
  python reply.py --message "Is parking free?" --property 0

  # Use a different provider
  python reply.py --message "WiFi password?" --provider openai

  # Set guest name for personalization
  python reply.py --message "Hey, running late!" --guest "Sarah"

  # Print draft only (no auto-send decision)
  python reply.py --message "How do I use the coffee machine?" --draft-only

Environment variables:
  ZAI_API_KEY         - z.ai API key (get from https://bigmodel.cn)
  OPENAI_API_KEY      - OpenAI API key
  LLM_PROVIDER        - "zai" or "openai" (auto-detected from keys)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from guest_agent.chatbot import (
    GuestChatbot, GuestMessage, LLMConfig, MessageType,
    build_system_prompt,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reply")

KB_PATH = PROJECT_ROOT / "guest_agent" / "knowledge_base.json"


def print_response(response, message: GuestMessage, draft_only: bool):
    """Pretty-print the agent response."""
    type_icons = {
        MessageType.INQUIRY: "❓",
        MessageType.CHECK_IN: "🔑",
        MessageType.AMENITY: "🏠",
        MessageType.ISSUE: "⚠️",
        MessageType.GENERAL: "💬",
        MessageType.ESCALATE: "🚨",
    }
    icon = type_icons.get(response.message_type, "💬")

    print(f"\n{'='*60}")
    print(f"  {icon} {response.message_type.value.upper()}")
    print(f"{'='*60}")
    print(f"\n  Guest: {message.guest_name}")
    print(f'  Message: "{message.message}"')

    print(f"\n{'─'*60}")
    print(f"  📝 Draft Reply:")
    print(f"{'─'*60}")
    print(f"\n  {response.reply}\n")

    if not draft_only:
        print(f"{'─'*60}")
        if response.message_type == MessageType.ESCALATE:
            print(f"  🚨 ESCALATE — requires host attention")
        elif response.auto_send:
            print(f"  ✅ AUTO-SEND APPROVED (confidence: {response.confidence:.0%})")
        else:
            print(f"  ⏸️  REVIEW NEEDED (confidence: {response.confidence:.0%})")
        print(f"  {response.reasoning}")
        print(f"{'─'*60}")

    print()


def list_properties():
    """List properties from knowledge base."""
    if not KB_PATH.exists():
        print("  No knowledge base found.")
        return []
    with open(KB_PATH) as f:
        kb = json.load(f)
    props = kb.get("properties", [])
    if not props:
        print("  No properties in knowledge base.")
        return props
    print(f"\n  {len(props)} propert(y/ies):\n")
    for i, p in enumerate(props):
        name = p.get("name", "Unnamed")
        pid = p.get("id", "")
        checkin = p.get("check_in_time", "—")
        print(f"  [{i}] {name} ({pid})  check-in: {checkin}")
    print()
    return props


async def run(args):
    # Build LLM config
    if args.provider == "openai":
        llm_config = LLMConfig.openai(
            api_key=args.api_key or os.getenv("OPENAI_API_KEY", ""),
            model=args.model or "gpt-4o",
        )
    elif args.provider == "zai":
        llm_config = LLMConfig.zai(
            api_key=args.api_key or os.getenv("ZAI_API_KEY", ""),
            model=args.model or "glm-4",
        )
    else:
        llm_config = LLMConfig.from_env()

    if not llm_config.api_key:
        print(f"\n  ✗ No API key found for {llm_config.provider}.")
        env_var = "ZAI_API_KEY" if llm_config.provider == "zai" else "OPENAI_API_KEY"
        print(f"    Set the {env_var} environment variable or use --api-key.")
        print(f"    Get a z.ai key at: https://bigmodel.cn/usercenter/proj-mgmt/apikeys")
        return

    print(f"  Provider: {llm_config.provider} | Model: {llm_config.model}")

    # Determine listing_id from --property
    listing_id = ""
    if args.property is not None:
        with open(KB_PATH) as f:
            kb = json.load(f)
        props = kb.get("properties", [])
        if 0 <= args.property < len(props):
            listing_id = props[args.property].get("id", "")
            print(f"  Property: {props[args.property].get('name', '')} ({listing_id})")

    # Get message
    msg_text = args.message
    if not msg_text:
        print()
        msg_text = input("  Guest message: ").strip()
        if not msg_text:
            print("  No message entered. Exiting.")
            return

    guest_name = args.guest or "Guest"

    message = GuestMessage(
        guest_name=guest_name,
        message=msg_text,
        listing_id=listing_id,
    )

    # Initialize chatbot
    threshold = args.threshold if args.threshold is not None else 0.7
    bot = GuestChatbot(
        knowledge_base_path=str(KB_PATH),
        llm_config=llm_config,
        escalation_threshold=threshold,
    )

    # Generate response
    print(f"\n  Generating reply...")
    response = await bot.handle_message(message)

    print_response(response, message, args.draft_only)


def main():
    parser = argparse.ArgumentParser(
        description="Draft AI replies to Airbnb guest messages.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("-m", "--message", type=str, default="",
                        help="Guest message text (omit for interactive prompt)")
    parser.add_argument("-g", "--guest", type=str, default="",
                        help="Guest name for personalization")
    parser.add_argument("-p", "--property", type=int, default=None,
                        help="Property index from knowledge base (see: python reply.py --list)")
    parser.add_argument("--list", action="store_true",
                        help="List properties in knowledge base and exit")

    # Provider config
    parser.add_argument("--provider", choices=["zai", "openai"], default="",
                        help="LLM provider (default: auto-detect from env vars)")
    parser.add_argument("--model", type=str, default="",
                        help="Model name override (default: glm-4 for zai, gpt-4o for openai)")
    parser.add_argument("--api-key", type=str, default="",
                        help="API key (default: from ZAI_API_KEY or OPENAI_API_KEY env var)")

    # Behavior
    parser.add_argument("--draft-only", action="store_true",
                        help="Just print the draft, skip auto-send/escalate decision")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Confidence threshold for auto-send (default: 0.7)")
    parser.add_argument("--show-prompt", action="store_true",
                        help="Print the system prompt and exit (for debugging)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.list:
        list_properties()
        return

    if args.show_prompt:
        with open(KB_PATH) as f:
            kb = json.load(f)
        print(build_system_prompt(kb))
        return

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
