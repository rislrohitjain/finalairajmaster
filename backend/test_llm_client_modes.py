import os
import asyncio
from app.llm_client import get_embedding, generate_chat_reply, IS_HUGGINGFACE

def test_local_mode():
    print("=== Testing Local Mode ===")
    os.environ["ENV_MODE"] = "local"
    if "SPACE_ID" in os.environ:
        del os.environ["SPACE_ID"]
    
    emb = get_embedding("Rajasthan administrative tiers and districts")
    print(f"Local Embedding dim: {len(emb)}")
    assert len(emb) == 384
    print(f"Local Embedding sample: {emb[:5]}")

    reply = generate_chat_reply([
        {"role": "user", "content": "Hello"}
    ])
    print(f"Local Chat reply: {repr(reply)}")

def test_hf_mode():
    print("\n=== Testing Cloud (Hugging Face) Mode Simulation ===")
    # Temporarily set SPACE_ID to simulate Hugging Face Spaces environment
    import app.llm_client as lc
    lc.IS_HUGGINGFACE = True

    emb = lc.get_embedding("Rajasthan administrative tiers and districts")
    print(f"Cloud Embedding dim: {len(emb)}")
    assert len(emb) == 384
    print(f"Cloud Embedding sample: {emb[:5]}")

    reply = lc.generate_chat_reply([
        {"role": "user", "content": "Hello"}
    ])
    print(f"Cloud Chat reply: {repr(reply)}")

if __name__ == "__main__":
    test_local_mode()
    test_hf_mode()
    print("\nLLM Client Auto-Switching verification passed!")
