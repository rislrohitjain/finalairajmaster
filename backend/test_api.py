import json
from fastapi.testclient import TestClient
from app.main import app

def run_end_to_end_tests():
    print("=================================================================")
    print("FINALAIRAJMASTER: END-TO-END COMPREHENSIVE VERIFICATION SUITE")
    print("=================================================================")

    with TestClient(app) as client:
        # 1. Root & Health
        print("\n[1/10] Verifying Root & Health Endpoints...")
        r_root = client.get("/")
        assert r_root.status_code == 200, f"Root failed: {r_root.status_code}"
        print(f"  ✓ Root OK: {r_root.json()['portal']}")

        r_health = client.get("/health")
        assert r_health.status_code == 200, f"Health failed: {r_health.status_code}"
        print(f"  ✓ Health OK: Database = {r_health.json()['database']}, Helpline = {r_health.json()['support_phone']}")

        # 2. Capabilities Endpoint
        print("\n[2/10] Verifying Capabilities (/api/capabilities)...")
        r_cap = client.get("/api/capabilities")
        assert r_cap.status_code == 200
        cap_data = r_cap.json()
        print(f"  ✓ Official Administrative Levels: {len(cap_data['administrative_levels'])}")
        print(f"  ✓ Support Helpline: {cap_data['support_phone']}")
        print(f"  ✓ Sample Prompts: {len(cap_data['sample_prompts'])}")

        # 3. Direct Geo Search
        print("\n[3/10] Verifying Geo Search (/api/geo/search?q=Muhana)...")
        r_geo = client.get("/api/geo/search?q=Muhana")
        assert r_geo.status_code == 200
        geo_data = r_geo.json()
        assert geo_data["matched"] is True, "Expected Muhana to match"
        print(f"  ✓ Matched: {geo_data['entity_name']} ({geo_data['entity_type']})")
        print(f"  ✓ Lineage Path: {' ➔ '.join(geo_data['breadcrumbs'])}")

        # 4. LangGraph Geographic Query
        print("\n[4/10] Verifying LangGraph Geographic Hierarchy Chat...")
        r_chat_geo = client.post("/api/chat", json={
            "session_id": "test-geo",
            "query": "What is the administrative lineage of Muhana village?"
        })
        assert r_chat_geo.status_code == 200
        res_geo = r_chat_geo.json()
        assert res_geo["intent"] == "geographic_query"
        assert res_geo["helpline_card"] is False
        print(f"  ✓ Intent: {res_geo['intent']}")
        print(f"  ✓ Breadcrumbs: {res_geo['breadcrumbs']}")
        print(f"  ✓ Response Preview: {res_geo['response'][:110]}...")

        # 5. Pincode Query Lineage
        print("\n[5/10] Verifying Pincode 302029 Hierarchy Lineage...")
        r_pin = client.post("/api/chat", json={
            "session_id": "test-pin",
            "query": "Details of pincode 302029"
        })
        assert r_pin.status_code == 200
        res_pin = r_pin.json()
        assert res_pin["intent"] == "geographic_query"
        print(f"  ✓ Intent: {res_pin['intent']}")
        print(f"  ✓ Breadcrumbs: {res_pin['breadcrumbs']}")

        # 6. Out-of-Scope Guardrail & Helpline Routing
        print("\n[6/10] Verifying Out-of-Scope Guardrail & Helpline Redirect...")
        r_out = client.post("/api/chat", json={
            "session_id": "test-out",
            "query": "Write a python script for sorting an array"
        })
        assert r_out.status_code == 200
        res_out = r_out.json()
        assert res_out["intent"] == "out_of_scope"
        assert res_out["helpline_card"] is True
        assert "89988555525" in res_out["response"]
        print(f"  ✓ Caught as: {res_out['intent']}")
        print(f"  ✓ Helpline Card Triggered: {res_out['helpline_card']}")
        print(f"  ✓ Helpline Number in Response: 89988555525 verified")

        # 7. Admin Authentication (8946919241 / 123456)
        print("\n[7/10] Verifying Admin Authentication (/api/admin/login)...")
        r_login = client.post("/api/admin/login", json={
            "username": "8946919241",
            "password": "123456"
        })
        assert r_login.status_code == 200, f"Admin login failed: {r_login.status_code}"
        token = r_login.json()["access_token"]
        print(f"  ✓ JWT Token Received for Admin 8946919241 (length: {len(token)})")
        headers = {"Authorization": f"Bearer {token}"}

        # 8. Admin Geo Stats
        print("\n[8/10] Verifying Admin Geographic Database Counts (/api/admin/geo-stats)...")
        r_stats = client.get("/api/admin/geo-stats", headers=headers)
        assert r_stats.status_code == 200
        stats = r_stats.json()
        print(f"  ✓ Divisions: {stats['divisions']}")
        print(f"  ✓ Districts: {stats['districts']}")
        print(f"  ✓ Sub-Divisions: {stats['sub_divisions']}")
        print(f"  ✓ Tehsils & Blocks: {stats['tehsils_blocks']}")
        print(f"  ✓ Gram Panchayats: {stats['gram_panchayats']}")
        print(f"  ✓ Villages: {stats['villages']}")
        print(f"  ✓ Urban Local Bodies: {stats['urban_local_bodies']}")
        print(f"  ✓ Pincodes: {stats['pincodes']}")
        print(f"  ✓ Total Hierarchy Entities: {stats['total_entities']}")

        # 9. Admin LLM Configuration Management
        print("\n[9/10] Verifying LLM Configuration & Model Listing (/api/admin/llm-config)...")
        r_llm = client.get("/api/admin/llm-config", headers=headers)
        assert r_llm.status_code == 200
        llm_data = r_llm.json()
        print(f"  ✓ Active Model: {llm_data['active_model']}")
        print(f"  ✓ Temperature: {llm_data['temperature']}")
        print(f"  ✓ Available Local Models: {llm_data['available_models'][:4]}...")

        # 10. Admin Chat Logs & Scraper Runs
        print("\n[10/10] Verifying Admin Chat Logs & Scraper Run Tracking...")
        r_logs = client.get("/api/admin/chat-logs?limit=5", headers=headers)
        assert r_logs.status_code == 200
        logs = r_logs.json()
        print(f"  ✓ Recorded Chat Logs Count: {len(logs)}")
        if logs:
            print(f"  ✓ Latest Log: '{logs[0]['user_query']}' -> Intent: {logs[0]['detected_intent']} ({logs[0]['latency_ms']}ms)")

        r_runs = client.get("/api/admin/scraper-runs?limit=5", headers=headers)
        assert r_runs.status_code == 200
        print(f"  ✓ Scraper Runs Count: {len(r_runs.json())}")

    print("\n=================================================================")
    print("SUCCESS: ALL 10 END-TO-END SUITE VERIFICATIONS PASSED 100%!")
    print("=================================================================")

if __name__ == "__main__":
    run_end_to_end_tests()
