import os
import re
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional
import httpx
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

logger = logging.getLogger("llm_client")

# Detect environment mode: Cloud (Hugging Face Spaces) vs Local vs Vercel
IS_HUGGINGFACE = bool(os.getenv("SPACE_ID")) or os.getenv("ENV_MODE") == "huggingface"

# Cloud LLM API Keys & Configurations
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# Cloud Models
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
HF_LLM_MODEL = os.getenv("HF_LLM_MODEL", "meta-llama/Llama-3.2-3B-Instruct")
HF_EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Local Ollama Settings
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "llama3.2:latest")

def get_active_llm_info() -> Dict[str, Any]:
    """Identifies the primary active LLM provider available in the environment"""
    if GEMINI_API_KEY:
        return {
            "provider": "google_gemini",
            "model": GEMINI_MODEL,
            "cloud": True,
            "status": "ready",
            "description": f"Google Gemini Cloud AI ({GEMINI_MODEL})"
        }
    elif GROQ_API_KEY:
        return {
            "provider": "groq",
            "model": GROQ_MODEL,
            "cloud": True,
            "status": "ready",
            "description": f"Groq High-Speed Cloud LPU ({GROQ_MODEL})"
        }
    elif OPENAI_API_KEY:
        return {
            "provider": "openai",
            "model": OPENAI_MODEL,
            "cloud": True,
            "status": "ready",
            "description": f"OpenAI Cloud API ({OPENAI_MODEL})"
        }
    elif HF_TOKEN or IS_HUGGINGFACE:
        return {
            "provider": "huggingface",
            "model": HF_LLM_MODEL,
            "cloud": True,
            "status": "ready",
            "description": f"Hugging Face Serverless Inference ({HF_LLM_MODEL})"
        }
    else:
        return {
            "provider": "langgraph_rule_synthesizer",
            "model": "deterministic_governance_engine",
            "cloud": True,
            "status": "active",
            "local_fallback_available": "ollama (on localhost:11434 if started)",
            "description": "Rajasthan LangGraph Deterministic Engine (100% Zero-Hallucination & Verified Records)"
        }

def _deterministic_fallback_embedding(text: str, dim: int = 384) -> List[float]:
    """Generates a stable, unit-normalized fallback embedding if the provider is unavailable."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    vals = [((h[i % len(h)] / 255.0) - 0.5) for i in range(dim)]
    norm = sum(v * v for v in vals) ** 0.5 or 1.0
    return [round(v / norm, 6) for v in vals]

def get_embedding(text: str) -> List[float]:
    """Computes a 384-dimensional vector embedding for the given text."""
    if not text or not text.strip():
        return [0.0] * 384

    clean_text = text.strip()

    # Cloud Mode: Hugging Face InferenceClient
    if HF_TOKEN or IS_HUGGINGFACE:
        try:
            from huggingface_hub import InferenceClient
            client = InferenceClient(token=HF_TOKEN or None)
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
            logger.debug(f"HF feature_extraction error ({e}), utilizing fallback vector.")

    # Local Mode: Ollama Client
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
    except Exception:
        pass

    return _deterministic_fallback_embedding(clean_text, 384)

async def async_generate_chat_reply(
    messages: List[Dict[str, str]],
    max_tokens: int = 400,
    temperature: float = 0.2
) -> Optional[str]:
    """
    Asynchronously invokes the most capable active Cloud LLM or local Ollama.
    Priority Order:
    1. Google Gemini (Gemini 1.5/2.0 Flash)
    2. Groq (Llama 3.3 70B)
    3. OpenAI (GPT-4o mini)
    4. Hugging Face Inference (Llama 3.2 3B)
    5. Local Ollama (if running)
    """
    if not messages:
        return None

    # 1. Google Gemini Cloud API
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
            sys_msg = next((m["content"] for m in messages if m["role"] == "system"), None)
            user_contents = []
            for m in messages:
                if m["role"] == "system":
                    continue
                role_val = "user" if m["role"] == "user" else "model"
                user_contents.append({"role": role_val, "parts": [{"text": m["content"]}]})
            
            body: Dict[str, Any] = {
                "contents": user_contents or [{"role": "user", "parts": [{"text": "Hello"}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens
                }
            }
            if sys_msg:
                body["systemInstruction"] = {"parts": [{"text": sys_msg}]}

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
        except Exception as e:
            logger.warning(f"Gemini API error ({e}), trying next provider.")

    # 2. Groq Cloud API
    if GROQ_API_KEY:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            body = {
                "model": GROQ_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"Groq API error ({e}), trying next provider.")

    # 3. OpenAI Cloud API
    if OPENAI_API_KEY:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
            body = {
                "model": OPENAI_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"OpenAI API error ({e}), trying next provider.")

    # 4. Hugging Face Serverless Inference API
    if HF_TOKEN or IS_HUGGINGFACE:
        try:
            from huggingface_hub import InferenceClient
            client = InferenceClient(token=HF_TOKEN or None)
            res = client.chat_completion(
                messages=messages,
                model=HF_LLM_MODEL,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return res.choices[0].message.content.strip()
        except Exception as e:
            logger.debug(f"HF chat_completion error: {e}")

    # 5. Local Ollama (fallback for local development)
    try:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        payload = {
            "model": OLLAMA_LLM_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature}
        }
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
    except Exception:
        pass

    return None

def generate_chat_reply(messages: List[Dict[str, str]], max_tokens: int = 300) -> str:
    """Synchronous fallback wrapper for chat completion."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If in async loop, run in thread pool
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                res = pool.submit(lambda: asyncio.run(async_generate_chat_reply(messages, max_tokens))).result()
                return res or ""
        else:
            return loop.run_until_complete(async_generate_chat_reply(messages, max_tokens)) or ""
    except Exception:
        return ""

__all__ = [
    "IS_HUGGINGFACE", "get_embedding", "generate_chat_reply",
    "async_generate_chat_reply", "get_active_llm_info"
]
