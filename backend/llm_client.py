import os
import sys

# Ensure backend/app is importable
app_path = os.path.join(os.path.dirname(__file__), "app")
if app_path not in sys.path:
    sys.path.insert(0, app_path)

from app.llm_client import IS_HUGGINGFACE, get_embedding, generate_chat_reply

__all__ = ["IS_HUGGINGFACE", "get_embedding", "generate_chat_reply"]
