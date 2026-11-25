import sys
import os
import json
import subprocess
from typing import Dict, Any, Optional

def run_mcp_test_suite():
    print("=" * 75)
    print("POSTGRESQL MCP SERVER VERIFICATION: 10 COMPREHENSIVE QUESTIONS")
    print("=" * 75)

    backend_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable

    # Launch MCP server subprocess with stdio pipes
    proc = subprocess.Popen(
        [python_exe, "-m", "app.mcp.postgres_server"],
        cwd=backend_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    req_id = 0

    def send_rpc(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        nonlocal req_id
        req_id += 1
        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

        line = proc.stdout.readline()
        if not line:
            stderr_out = proc.stderr.read()
            raise RuntimeError(f"MCP server closed stdout unexpectedly. Stderr: {stderr_out}")
        return json.loads(line)

    def send_notification(method: str, params: Optional[Dict[str, Any]] = None):
        msg = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    try:
        # Phase 1: Protocol Handshake
        print("\n[Handshake] Initializing MCP connection with postgres-mcp...")
        init_resp = send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-runner", "version": "1.0"}
        })
        assert "result" in init_resp, f"Initialize failed: {init_resp}"
        server_info = init_resp["result"]["serverInfo"]
        print(f"  ✓ Connected to MCP Server: {server_info['name']} v{server_info['version']}")
        print(f"  ✓ Protocol Version: {init_resp['result']['protocolVersion']}")

        send_notification("notifications/initialized")
        print("  ✓ Client notification 'notifications/initialized' acknowledged.")

        # Tool Discovery
        tools_resp = send_rpc("tools/list")
        available_tools = [t["name"] for t in tools_resp["result"]["tools"]]
        print(f"  ✓ Available MCP Tools: {available_tools}")

        # Phase 2: Execute 10 Database Test Questions
        print("\n" + "-" * 75)
        print("EXECUTING 10 TARGET DATABASE QUESTIONS VIA MCP PROTOCOL")
        print("-" * 75)

        # Q1: List all tables in the finalairajmaster PostgreSQL database
        print("\n[Question 1/10] 'What tables exist in the finalairajmaster PostgreSQL database?'")
        q1_res = send_rpc("tools/call", {
            "name": "list_tables",
            "arguments": {}
        })
        data1 = json.loads(q1_res["result"]["content"][0]["text"])
        tables_list = [t["table_name"] for t in data1["tables"]]
        print(f"  MCP Result: Total {data1['total_tables']} tables detected.")
        print(f"  Tables: {', '.join(tables_list[:8])}...")
        assert data1["total_tables"] >= 10, "Expected at least 10 tables."
        print("  ✓ Status: PASS")

        # Q2: Describe schema and columns of the 'districts' table
        print("\n[Question 2/10] 'What is the exact schema and primary key structure of the districts table?'")
        q2_res = send_rpc("tools/call", {
            "name": "describe_table",
            "arguments": {"table_name": "districts"}
        })
        data2 = json.loads(q2_res["result"]["content"][0]["text"])
        print(f"  MCP Result: Primary Keys = {data2['primary_keys']}, Total Columns = {len(data2['columns'])}")
        cols_summary = [f"{c['column_name']} ({c['data_type']})" for c in data2["columns"][:5]]
        print(f"  Column sample: {', '.join(cols_summary)}")
        assert "name_en" in [c["column_name"] for c in data2["columns"]]
        print("  ✓ Status: PASS")

        # Q3: List all 10 administrative divisions of Rajasthan
        print("\n[Question 3/10] 'List all official administrative divisions of Rajasthan with codes?'")
        q3_res = send_rpc("tools/call", {
            "name": "read_query",
            "arguments": {
                "query": "SELECT id, code, name_en, name_hi, lgd_code FROM divisions ORDER BY id;"
            }
        })
        data3 = json.loads(q3_res["result"]["content"][0]["text"])
        print(f"  MCP Result: {data3['row_count']} divisions returned.")
        for r in data3["rows"]:
            print(f"    • ID {r['id']}: {r['name_en']} ({r['name_hi']}) [LGD: {r['lgd_code']}]")
        assert data3["row_count"] == 10, f"Expected 10 divisions, got {data3['row_count']}"
        print("  ✓ Status: PASS")

        # Q4: Count total districts in each division
        print("\n[Question 4/10] 'How many districts are assigned to each administrative division?'")
        q4_res = send_rpc("tools/call", {
            "name": "read_query",
            "arguments": {
                "query": """
                    SELECT div.name_en AS division_name, count(d.id) AS total_districts
                    FROM divisions div
                    LEFT JOIN districts d ON d.division_id = div.id
                    GROUP BY div.name_en
                    ORDER BY total_districts DESC;
                """
            }
        })
        data4 = json.loads(q4_res["result"]["content"][0]["text"])
        print(f"  MCP Result: Aggregated district counts across divisions:")
        for r in data4["rows"]:
            print(f"    • {r['division_name']}: {r['total_districts']} districts")
        assert len(data4["rows"]) > 0
        print("  ✓ Status: PASS")

        # Q5: Administrative hierarchy of Muhana village
        print("\n[Question 5/10] 'What is the full 6-tier administrative lineage of Muhana village?'")
        q5_res = send_rpc("tools/call", {
            "name": "get_administrative_lineage",
            "arguments": {"entity_name_or_pincode": "Muhana"}
        })
        data5 = json.loads(q5_res["result"]["content"][0]["text"])
        assert data5["matched"] is True
        print(f"  MCP Result: Entity = {data5['entity_name']} ({data5['entity_type']})")
        print(f"  Lineage Path: {' ➔ '.join(data5['breadcrumbs'])}")
        print(f"  Patwar Circle: {data5['lineage'].get('patwar_circle')}, Pincode: {data5['lineage'].get('pincode')}")
        print("  ✓ Status: PASS")

        # Q6: Division and district for Balotra
        print("\n[Question 6/10] 'Which administrative division and district does Balotra belong to?'")
        q6_res = send_rpc("tools/call", {
            "name": "get_administrative_lineage",
            "arguments": {"entity_name_or_pincode": "Balotra"}
        })
        data6 = json.loads(q6_res["result"]["content"][0]["text"])
        assert data6["matched"] is True
        print(f"  MCP Result: Entity = {data6['entity_name']} ({data6['entity_type']})")
        print(f"  Division: {data6['lineage'].get('division')}, Zila Pramukh: {data6['lineage'].get('zila_pramukh')}")
        print(f"  Breadcrumbs: {' ➔ '.join(data6['breadcrumbs'])}")
        print("  ✓ Status: PASS")

        # Q7: Postal hierarchy for pincode 302029
        print("\n[Question 7/10] 'What administrative hierarchy covers pincode 302029?'")
        q7_res = send_rpc("tools/call", {
            "name": "get_administrative_lineage",
            "arguments": {"entity_name_or_pincode": "302029"}
        })
        data7 = json.loads(q7_res["result"]["content"][0]["text"])
        assert data7["matched"] is True
        print(f"  MCP Result: Pincode = {data7['entity_name']}")
        print(f"  Lineage Path: {' ➔ '.join(data7['breadcrumbs'])}")
        print(f"  District: {data7['lineage'].get('district')}, Division: {data7['lineage'].get('division')}")
        print("  ✓ Status: PASS")

        # Q8: Urban Local Bodies in Jaipur
        print("\n[Question 8/10] 'What Urban Local Bodies (Municipal Corporations/Councils) are registered in Jaipur?'")
        q8_res = send_rpc("tools/call", {
            "name": "read_query",
            "arguments": {
                "query": """
                    SELECT ulb.name_en, ulb.name_hi, ulb.ulb_type, ulb.city_name, ulb.pincode
                    FROM urban_local_bodies ulb
                    JOIN districts d ON ulb.district_id = d.id
                    WHERE d.name_en ILIKE '%Jaipur%'
                    ORDER BY ulb.name_en;
                """
            }
        })
        data8 = json.loads(q8_res["result"]["content"][0]["text"])
        print(f"  MCP Result: {data8['row_count']} Urban Local Bodies found in Jaipur:")
        for r in data8["rows"]:
            print(f"    • {r['name_en']} ({r['name_hi']}) - Type: {r['ulb_type']} [PIN: {r['pincode']}]")
        assert data8["row_count"] >= 1
        print("  ✓ Status: PASS")

        # Q9: LLM Setting & configuration
        print("\n[Question 9/10] 'What is the active LLM configuration and support phone stored in the database?'")
        q9_res = send_rpc("tools/call", {
            "name": "read_query",
            "arguments": {
                "query": "SELECT id, active_model, temperature, max_tokens, support_phone FROM llm_settings WHERE id = 1;"
            }
        })
        data9 = json.loads(q9_res["result"]["content"][0]["text"])
        assert data9["row_count"] == 1
        cfg = data9["rows"][0]
        print(f"  MCP Result: Active Model = {cfg['active_model']}, Temp = {cfg['temperature']}, Helpline = {cfg['support_phone']}")
        print("  ✓ Status: PASS")

        # Q10: Overall 6-tier administrative database statistics
        print("\n[Question 10/10] 'What are the overall entity counts across all 6 Rajasthan administrative tiers?'")
        q10_res = send_rpc("tools/call", {
            "name": "get_database_stats",
            "arguments": {}
        })
        data10 = json.loads(q10_res["result"]["content"][0]["text"])
        stats = data10["summary"]
        print(f"  MCP Result: 6-Tier Administrative Summary:")
        print(f"    • Tier 1 (State): {stats['tier_1_state']}")
        print(f"    • Tier 2 (Divisions): {stats['tier_2_divisions']}")
        print(f"    • Tier 3 (Districts): {stats['tier_3_districts']}")
        print(f"    • Tier 4 (Sub-Divisions): {stats['tier_4_sub_divisions']}")
        print(f"    • Tier 5 (Tehsils & Blocks): {stats['tier_5_tehsils_blocks']}")
        print(f"    • Tier 6 (Villages & Gram Panchayats): {stats['tier_6_rural_villages_gps']}")
        print(f"    • Tier 6 (Urban Local Bodies): {stats['tier_6_urban_bodies']}")
        print(f"    • Postal Directory (Pincodes): {stats['postal_directory_pincodes']}")
        assert stats["tier_2_divisions"] == 10
        assert stats["tier_3_districts"] == 50
        print("  ✓ Status: PASS")

        print("\n" + "=" * 75)
        print("SUCCESS: ALL 10 MCP POSTGRESQL QUESTIONS VERIFIED & PASSED (100%)")
        print("=" * 75)

    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=5)

if __name__ == "__main__":
    run_mcp_test_suite()
