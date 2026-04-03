#!/usr/bin/env python
"""Test script to check newline format in database."""
import asyncio
import sys
from dotenv import load_dotenv

load_dotenv()

async def main():
    from db.dao.agent_message_dao import AgentMessageDAO

    messages = await AgentMessageDAO.get_all_with_session_id(limit=1, offset=0)

    if not messages:
        print("No messages found")
        return

    message, session_id = messages[0]
    content = message.content_json

    print("=== Message Content Analysis ===")
    print(f"Type: {type(content)}")
    print(f"Keys: {list(content.keys()) if isinstance(content, dict) else 'N/A'}")
    print()

    if isinstance(content, dict):
        for key in ['summary', 'content', 'message', 'text']:
            if key in content:
                val = content[key]
                print(f"Key: {key}")
                print(f"Type: {type(val)}")
                print(f"Length: {len(val) if isinstance(val, str) else 'N/A'}")
                print(f"Contains literal '\\n' (two chars): {'\\n' in val}")
                print(f"Contains actual newline (char 10): {chr(10) in val}")

                # Show first 300 chars with repr to see escape sequences
                sample = val[:300] if isinstance(val, str) and len(val) > 300 else val
                print(f"Sample (repr): {repr(sample)}")
                print()
                break

if __name__ == "__main__":
    asyncio.run(main())
