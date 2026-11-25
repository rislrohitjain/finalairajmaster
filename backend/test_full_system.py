import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8000"

async def test_full_system():
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Admin Login
        login_resp = await client.post(f"{BASE_URL}/api/admin/login", json={
            "username": "8946919241",
            "password": "123456"
        })
        print("Login status:", login_resp.status_code)
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Get LLM Config
        cfg_resp = await client.get(f"{BASE_URL}/api/admin/llm-config", headers=headers)
        print("Get LLM Config status:", cfg_resp.status_code)
        assert cfg_resp.status_code == 200
        cfg = cfg_resp.json()
        print("Current LLM Config RAG & Web Search fields:")
        print(" - enable_rag:", cfg.get("enable_rag"))
        print(" - rag_top_k:", cfg.get("rag_top_k"))
        print(" - enable_web_search:", cfg.get("enable_web_search"))
        print(" - web_search_provider:", cfg.get("web_search_provider"))
        print(" - web_search_api_key:", repr(cfg.get("web_search_api_key")))
        print(" - web_search_max_results:", cfg.get("web_search_max_results"))

        # 3. Update LLM Config
        update_payload = {
            "active_model": cfg.get("active_model", "llama3.2:3b"),
            "temperature": 0.2,
            "max_tokens": 1024,
            "system_prompt": cfg.get("system_prompt", ""),
            "greeting_message": "Welcome here chat with Jain's only",
            "support_phone": "89988555525",
            "enable_rag": True,
            "rag_top_k": 5,
            "enable_web_search": True,
            "web_search_provider": "duckduckgo",
            "web_search_api_key": "",
            "web_search_max_results": 4
        }
        put_resp = await client.put(f"{BASE_URL}/api/admin/llm-config", headers=headers, json=update_payload)
        print("Update LLM Config status:", put_resp.status_code)
        assert put_resp.status_code == 200

        # 4. Test Chat: Exact DB Hierarchy query (Muhana village)
        print("\n--- Testing Exact DB Hierarchy Query: 'What is the administrative lineage of Muhana village?' ---")
        chat1 = await client.post(f"{BASE_URL}/api/chat", json={
            "session_id": "test-session-1",
            "query": "What is the administrative lineage of Muhana village?"
        })
        print("Chat 1 status:", chat1.status_code)
        data1 = chat1.json()
        print("Response 1 Breadcrumbs:", data1.get("breadcrumbs"))
        print("Response 1 Text:\n", data1.get("response"))
        print("Response 1 Next Questions:", data1.get("next_questions"))
        assert "**" not in data1.get("response", "")

        # 5. Test Chat: RAG query (Pincode 302029)
        print("\n--- Testing RAG Query: 'Pincode 302029' ---")
        chat2 = await client.post(f"{BASE_URL}/api/chat", json={
            "session_id": "test-session-2",
            "query": "Pincode 302029"
        })
        print("Chat 2 status:", chat2.status_code)
        data2 = chat2.json()
        print("Response 2 Breadcrumbs:", data2.get("breadcrumbs"))
        print("Response 2 Text:\n", data2.get("response"))
        print("Response 2 Next Questions:", data2.get("next_questions"))
        assert "**" not in data2.get("response", "")

        # 6. Test Chat: Web Search Fallback query (Chief Minister of Rajasthan)
        print("\n--- Testing Web Search Fallback: 'Who is the current Chief Minister of Rajasthan?' ---")
        chat3 = await client.post(f"{BASE_URL}/api/chat", json={
            "session_id": "test-session-3",
            "query": "Who is the current Chief Minister of Rajasthan?"
        })
        print("Chat 3 status:", chat3.status_code)
        data3 = chat3.json()
        print("Response 3 Breadcrumbs:", data3.get("breadcrumbs"))
        print("Response 3 Text:\n", data3.get("response"))
        print("Response 3 Next Questions:", data3.get("next_questions"))
        assert "**" not in data3.get("response", "")

        print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_full_system())
