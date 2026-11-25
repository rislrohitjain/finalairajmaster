import asyncio
import httpx
import os

BASE_URL = "http://127.0.0.1:8000"

async def test_dual_env_and_rag():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Test /health
        health = await client.get(f"{BASE_URL}/health")
        print("Health check status:", health.status_code)
        assert health.status_code == 200

        # 2. Test /ingest (both /ingest and /api/ingest)
        print("\n--- Testing /ingest Endpoint ---")
        ingest_resp = await client.post(f"{BASE_URL}/ingest", json={
            "content": "Jaipur Development Authority (JDA) was established in 1982 for urban infrastructure, civic planning, and master plan execution across the Jaipur metropolitan region.",
            "session_id": "test-session-rag"
        })
        print("Ingest status:", ingest_resp.status_code)
        print("Ingest response:", ingest_resp.json())
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["embedding_dim"] == 384

        # 3. Test /api/ingest
        print("\n--- Testing /api/ingest Endpoint ---")
        api_ingest = await client.post(f"{BASE_URL}/api/ingest", json={
            "doc": "Rajasthan Tourism Development Corporation (RTDC) operates heritage circuits, hotels, and luxury trains including Palace on Wheels.",
            "session_id": "test-session-rag"
        })
        print("API Ingest status:", api_ingest.status_code)
        assert api_ingest.status_code == 200
        assert api_ingest.json()["embedding_dim"] == 384

        # 4. Test /chat with RAG retrieval & session history
        print("\n--- Testing /chat with RAG Retrieval ---")
        chat_resp1 = await client.post(f"{BASE_URL}/chat", json={
            "session_id": "test-session-rag",
            "query": "Tell me about Jaipur Development Authority JDA"
        })
        print("Chat status:", chat_resp1.status_code)
        data1 = chat_resp1.json()
        print("Response 1 Text:\n", data1.get("response"))
        print("Response 1 Breadcrumbs:", data1.get("breadcrumbs"))
        assert chat_resp1.status_code == 200

        # 5. Test follow-up in the same session (verifying history saving)
        print("\n--- Testing Follow-up /api/chat ---")
        chat_resp2 = await client.post(f"{BASE_URL}/api/chat", json={
            "session_id": "test-session-rag",
            "query": "What is the administrative lineage of Muhana village?"
        })
        print("Chat status 2:", chat_resp2.status_code)
        data2 = chat_resp2.json()
        print("Response 2 Text:\n", data2.get("response"))
        print("Response 2 Next Questions:", data2.get("next_questions"))
        assert chat_resp2.status_code == 200

        # 6. Verify records in rag_support table
        import asyncpg
        conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
        docs_cnt = await conn.fetchval("SELECT count(*) FROM rag_support WHERE record_type = 'doc'")
        chats_cnt = await conn.fetchval("SELECT count(*) FROM rag_support WHERE record_type = 'chat'")
        print(f"\nrag_support table verification: {docs_cnt} docs, {chats_cnt} chats")
        
        recent_rows = await conn.fetch("SELECT id, record_type, session_id, role, substring(content, 1, 60) as preview, created_at FROM rag_support ORDER BY id DESC LIMIT 5")
        for r in recent_rows:
            print(f"  [Row {r['id']}] type={r['record_type']} role={r['role']} sid={r['session_id']} | {r['preview']}...")
        await conn.close()

        print("\nALL DUAL-ENVIRONMENT & SINGLE-TABLE RAG VERIFICATIONS PASSED!")

if __name__ == "__main__":
    asyncio.run(test_dual_env_and_rag())
