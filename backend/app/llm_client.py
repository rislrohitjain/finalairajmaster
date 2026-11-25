import os
import re
import hashlib
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

logger = logging.getLogger("llm_client")

# Detect environment mode: Cloud (Hugging Face Spaces) vs Local
IS_HUGGINGFACE = bool(os.getenv("SPACE_ID")) or os.getenv("ENV_MODE") == "huggingface"

# Hugging Face Settings
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
HF_LLM_MODEL = "meta-llama/Llama-3.2-3B-Instruct"

# Local Ollama Settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2:latest")

def _deterministic_fallback_embedding(text: str, dim: int = 384) -> List[float]:
    """Generates a stable, unit-normalized fallback embedding if the provider is unavailable."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vals = [((h[i % len(h)] / 255.0) - 0.5) for i in range(dim)]
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [round(v / norm, 6) for v in vals]

def get_embedding(text: str) -> List[float]:
    """
    Computes a 384-dimensional vector embedding for the given text.
    - Cloud (Hugging Face Spaces): Uses huggingface_hub.InferenceClient with BAAI/bge-small-en-v1.5.
    - Local: Uses ollama.Client with OLLAMA_EMBED_MODEL (sliced/padded to 384 dimensions).
    """
    if not text or not text.strip():
        return [0.0] * 384

    clean_text = text.strip()

    # Cloud Mode: Hugging Face InferenceClient
    if IS_HUGGINGFACE:
        try:
            from huggingface_hub import InferenceClient
            client = InferenceClient(token=HF_TOKEN or os.getenv("HF_TOKEN"))
            res = client.feature_extraction(clean_text, model=HF_EMBED_MODEL)
            if hasattr(res, "tolist"):
                res = res.tolist()
            if isinstance(res, list):
                if len(res) > 0 and isinstance(res[0], list):
                    res = res[0]
                vector = [float(x) for x in res]
                if len(vector) > 384:
                    vector = vector[:384]
                elif len(vector) < 384:
                    vector = vector + [0.0] * (384 - len(vector))
                return [round(x, 6) for x in vector]
        except Exception as e:
            logger.warning(f"HF feature_extraction error ({e}), utilizing fallback vector.")

    # Local Mode: Ollama Client
    else:
        try:
            import ollama
            client = ollama.Client(host=OLLAMA_BASE_URL)
            res = client.embeddings(model=OLLAMA_EMBED_MODEL, prompt=clean_text)
            raw_emb = res.get("embedding", [])
            if raw_emb:
                vector = [float(x) for x in raw_emb]
                if len(vector) > 384:
                    vector = vector[:384]
                elif len(vector) < 384:
                    vector = vector + [0.0] * (384 - len(vector))
                return [round(x, 6) for x in vector]
        except Exception as e:
            logger.info(f"Ollama local embeddings error ({e}), utilizing fallback vector.")

    # Return deterministic fallback vector
    return _deterministic_fallback_embedding(clean_text, 384)

def generate_chat_reply(messages: List[Dict[str, str]], max_tokens: int = 300) -> str:
    """
    Generates a conversational chat completion.
    - Cloud (Hugging Face Spaces): Uses huggingface_hub.InferenceClient with meta-llama/Llama-3.2-3B-Instruct.
    - Local: Uses ollama.Client with OLLAMA_LLM_MODEL.
    """
    if not messages:
        return ""

    # Cloud Mode: Hugging Face InferenceClient
    if IS_HUGGINGFACE:
        try:
            from huggingface_hub import InferenceClient
            client = InferenceClient(token=HF_TOKEN or os.getenv("HF_TOKEN"))
            res = client.chat_completion(
                messages=messages,
                model=HF_LLM_MODEL,
                max_tokens=max_tokens
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"HF chat_completion error: {e}")
            return "Official Rajasthan Geographic Master service response (Cloud Inference notice)."

    # Local Mode: Ollama Client
    else:
        try:
            import ollama
            client = ollama.Client(host=OLLAMA_BASE_URL)
            res = client.chat(
                model=OLLAMA_LLM_MODEL,
                messages=messages
            )
            return res.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.info(f"Ollama local chat error/unreachable: {e}")
            return ""

__all__ = ["IS_HUGGINGFACE", "get_embedding", "generate_chat_reply"]
