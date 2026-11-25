import os
import sys

backend_path = os.path.join(os.path.dirname(__file__), "backend")
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.llm_client import IS_HUGGINGFACE, get_embedding, generate_chat_reply

__all__ = ["IS_HUGGINGFACE", "get_embedding", "generate_chat_reply"]
