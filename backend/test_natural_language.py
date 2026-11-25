import asyncio
import json
from app.agent.graph import rajmaster_agent

async def run_tests():
    test_cases = [
        # 1. Pincode in English
        {
            "query": "Details of pincode 302029",
            "language": "en",
            "desc": "Pincode 302029 (English)"
        },
        # 2. Pincode in Hindi
        {
            "query": "पिनकोड 302029 का विवरण",
            "language": "hi",
            "desc": "Pincode 302029 (Hindi)"
        },
        # 3. Pincode in Hinglish
        {
            "query": "Pincode 302029 ke administrative details kya hai?",
            "language": "hinglish",
            "desc": "Pincode 302029 (Hinglish)"
        },
        # 4. District Balotra in English
        {
            "query": "Which division does Balotra district belong to?",
            "language": "en",
            "desc": "District Balotra (English)"
        },
        # 5. District Balotra in Hindi
        {
            "query": "बालोतरा जिला किस संभाग के अंतर्गत आता है?",
            "language": "hi",
            "desc": "District Balotra (Hindi)"
        },
        # 6. Village Muhana in English
        {
            "query": "Tell me about Muhana village administrative hierarchy",
            "language": "en",
            "desc": "Village Muhana (English)"
        },
        # 7. Village Muhana in Hindi
        {
            "query": "मुहाना गांव की प्रशासनिक वंशावली बताएं",
            "language": "hi",
            "desc": "Village Muhana (Hindi)"
        },
        # 8. Out of scope in Hindi
        {
            "query": "आज का मौसम कैसा रहेगा?",
            "language": "hi",
            "desc": "Out of Scope (Hindi)"
        }
    ]

    print("=" * 80)
    print("TESTING NATURAL LANGUAGE HIERARCHY, TRANSLATIONS & NEXT 3 QUESTIONS")
    print("=" * 80)

    all_passed = True

    for tc in test_cases:
        initial_state = {
            "session_id": "test-session",
            "user_query": tc["query"],
            "language": tc["language"],
            "intent": None,
            "sql_trace": None,
            "breadcrumbs": None,
            "helpline_card": False,
            "support_phone": "89988555525",
            "response_text": "",
            "streaming_tokens": [],
            "next_questions": []
        }

        res = await rajmaster_agent.ainvoke(initial_state)
        resp_text = res.get("response_text", "")
        next_qs = res.get("next_questions", [])

        print(f"\n--- TEST: {tc['desc']} ---")
        print(f"Query: {tc['query']} (Requested Lang: {tc['language']})")
        print(f"Detected Intent: {res.get('intent')}")
        print(f"Detected Language: {res.get('language')}")
        print(f"Next Questions Count: {len(next_qs)}")
        print(f"Next Questions: {next_qs}")
        print("Response Snippet:")
        print(resp_text[:300] + ("..." if len(resp_text) > 300 else ""))

        # Verification checks:
        # 1. No forbidden robotic headers
        if "### Administrative Hierarchy: Pincode 302029" in resp_text:
            print("FAILED: Found forbidden header '### Administrative Hierarchy: Pincode 302029'")
            all_passed = False

        if "• **State**:" in resp_text or "• State:" in resp_text:
            print("FAILED: Found forbidden bullet list '• State:'")
            all_passed = False

        # 2. Must have 3 next questions
        if len(next_qs) != 3:
            print(f"FAILED: Expected 3 next questions, got {len(next_qs)}")
            all_passed = False

        # 3. For geographic queries, must have Hierarchy Path
        if res.get("intent") == "geographic_query":
            if "Hierarchy Path" not in resp_text and "पदानुक्रम मार्ग" not in resp_text:
                print("FAILED: Missing Hierarchy Path in response")
                all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("ALL NATURAL LANGUAGE & NEXT 3 QUESTIONS TESTS PASSED! (100%)")
    else:
        print("SOME TESTS FAILED! CHECK OUTPUT ABOVE.")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_tests())
