import asyncio
import httpx

async def verify():
    client = httpx.AsyncClient(timeout=30.0)
    
    # 1. Test Capabilities / Welcome Greeting
    r_cap = await client.get("http://localhost:8000/api/chat/capabilities")
    print("=== CAPABILITIES RESPONSE ===")
    print("Status:", r_cap.status_code)
    data = r_cap.json()
    print("Greeting:", data.get("greeting"))
    
    # 2. Test Geographic Query Output
    r_chat = await client.post("http://localhost:8000/api/chat", json={
        "session_id": "verify-format-test",
        "query": "Details of pincode 342015"
    })
    print("\n=== CHAT QUERY RESPONSE ===")
    print("Status:", r_chat.status_code)
    chat_data = r_chat.json()
    print("Response text:\n--- START ---")
    print(chat_data.get("response"))
    print("--- END ---")
    print("Next Questions list:", chat_data.get("next_questions"))
    print("Breadcrumbs list:", chat_data.get("breadcrumbs"))
    
    # Check assertions:
    resp = chat_data.get("response", "")
    assert "Hierarchy Path" not in resp, "FAIL: Hierarchy Path still found in response text!"
    assert "Next Expected Questions:" not in resp, "FAIL: Next Expected Questions still duplicated in text!"
    print("\nAll output checks PASSED cleanly!")
    
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(verify())
