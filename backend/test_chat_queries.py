import asyncio
import httpx

async def test_chat():
    client = httpx.AsyncClient(timeout=30.0)
    for q in ["Details of pincode 342015 in Rajasthan", "Tell me about Nechhwa tehsil in Rajasthan"]:
        r = await client.post("http://localhost:8000/api/chat", json={
            "session_id": "test-sync-verify",
            "query": q
        })
        if r.status_code == 200:
            res = r.json()
            print(f"\n==========================================")
            print(f"Query: '{q}'")
            print(f"Intent: {res.get('intent')}")
            print(f"Breadcrumbs: {res.get('breadcrumbs')}")
            print(f"Response:\n{res.get('response', '')}")
        else:
            print(f"Error {r.status_code}: {r.text}")
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(test_chat())
