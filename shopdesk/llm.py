import os
import anthropic
from dotenv import load_dotenv

# Read the .env file and copy its lines into environment variables
load_dotenv()

# Create the client once. It finds ANTHROPIC_API_KEY in the environment by itself.
client = anthropic.Anthropic()

# Which model to use. Falls back to Haiku if LLM_MODEL isn't set.
MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")


def chat(messages, tools=None, system=None, max_tokens=1024):
    """Send a conversation to the model and return the raw response."""
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    return client.messages.create(**kwargs)