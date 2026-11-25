import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath("backend"))

from app.agent.graph import rajmaster_agent

async def test_agent_output():
    queries = [
        ("number of villages in Jodhpur", "en"),
        ("what is administrative lineage of Muhana village", "en"),
        ("details of pincode 302029", "en"),
        ("जोधपुर जिले में गांवों की संख्या क्या है?", "hi"),
        ("मुहाना गांव की प्रशासनिक जानकारी", "hi"),
        ("पिनकोड 302029 की जानकारी", "hi"),
        ("Jodhpur district mein kitne villages hain?", "hinglish"),
        ("Muhana village ki tehsil kaunsi hai?", "hinglish"),
        ("what can you do", "en"),
        ("cricket score today", "en")
    ]

    all_passed = True
    print("\n=== TESTING AGENT OUTPUT FOR DOUBLE ASTERISKS (**) ===")
    
    for q, lang in queries:
        state = {
            "session_id": "test-session",
            "user_query": q,
            "language": lang,
            "intent": None,
            "sql_trace": None,
            "breadcrumbs": None,
            "helpline_card": False,
            "support_phone": "1800-180-6127",
            "response_text": "",
            "streaming_tokens": [],
            "next_questions": []
        }
        res = await rajmaster_agent.ainvoke(state)
        text = res.get("response_text", "")
        
        has_asterisks = "**" in text
        if has_asterisks:
            all_passed = False
            print(f"[FAIL] Query: '{q}' ({lang}) -> Contained '**'")
            print("Output excerpt:")
            print(text[:200])
            print("-" * 50)
        else:
            print(f"[PASS] Query: '{q}' ({lang}) -> Zero '**' found (Length: {len(text)} chars)")

    if all_passed:
        print("\nSUCCESS: All queries returned clean responses with ZERO literal '**'!")
    else:
        print("\nFAILURE: Some queries still contained literal '**'!")

    # Let's also print an example full response for 'number of villages in Jodhpur'
    print("\n=== SAMPLE RESPONSE: 'number of villages in Jodhpur' ===")
    state = {
        "session_id": "test-session",
        "user_query": "number of villages in Jodhpur",
        "language": "en",
        "intent": None,
        "sql_trace": None,
        "breadcrumbs": None,
        "helpline_card": False,
        "support_phone": "1800-180-6127",
        "response_text": "",
        "streaming_tokens": [],
        "next_questions": []
    }
    sample_res = await rajmaster_agent.ainvoke(state)
    print(sample_res.get("response_text"))

if __name__ == "__main__":
    asyncio.run(test_agent_output())
