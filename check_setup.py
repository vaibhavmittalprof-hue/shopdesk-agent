import os
from dotenv import load_dotenv

load_dotenv()  # reads .env into environment variables

key = os.getenv("ANTHROPIC_API_KEY")  # use your provider's variable name
print("Key loaded:", bool(key))
print("Key length:", len(key) if key else 0)