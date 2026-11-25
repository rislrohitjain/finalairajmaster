import asyncio
import asyncpg
import httpx
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

async def perform_rag_retrieval(query: str, top_k: int = 5):
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    results = []
    clean_q = query.strip()
    words = [w for w in re.findall(r"\b\w+\b", clean_q) if len(w) >= 3]
    
    # 1. Search in raj_masters.pincodes and public.pincodes
    digits = re.findall(r"\b\d{6}\b", clean_q)
    if digits:
        p_rows = await conn.fetch("""
            SELECT pincode, office_name, locality_name, subdist_name, district_name, state_name
            FROM raj_masters.pincodes
            WHERE pincode = $1
            LIMIT $2
        """, digits[0], top_k)
        for r in p_rows:
            results.append({
                "type": "pincode",
                "title": f"Pincode {r['pincode']} - {r['office_name'] or r['locality_name'] or ''}",
                "snippet": f"Pincode: {r['pincode']}, Office: {r['office_name']}, Sub-District/Tehsil: {r['subdist_name']}, District: {r['district_name']}, State: {r['state_name'] or 'Rajasthan'}"
            })

    # 2. Search in tehsils & blocks
    for w in words[:3]:
        t_rows = await conn.fetch("""
            SELECT name_en, name_hi, tehsildar_details, lgd_code
            FROM raj_masters.tehsils
            WHERE name_en ILIKE $1 OR name_hi ILIKE $1
            LIMIT $2
        """, f"%{w}%", top_k)
        for r in t_rows:
            results.append({
                "type": "tehsil",
                "title": f"Tehsil: {r['name_en']}",
                "snippet": f"Tehsil Name: {r['name_en']} ({r['name_hi'] or ''}), Tehsildar: {r['tehsildar_details'] or 'Tehsildar Office'}, LGD Code: {r['lgd_code'] or 'N/A'}"
            })

        b_rows = await conn.fetch("""
            SELECT name_en, name_hi, bdo_details, pradhan_name
            FROM raj_masters.blocks
            WHERE name_en ILIKE $1 OR name_hi ILIKE $1
            LIMIT $2
        """, f"%{w}%", top_k)
        for r in b_rows:
            results.append({
                "type": "block",
                "title": f"Panchayat Samiti (Block): {r['name_en']}",
                "snippet": f"Block Name: {r['name_en']} ({r['name_hi'] or ''}), BDO: {r['bdo_details'] or 'BDO Office'}, Pradhan: {r['pradhan_name'] or 'Zila Parishad'}"
            })

    # 3. Trigram search on public.districts
    for w in words[:2]:
        d_rows = await conn.fetch("""
            SELECT d.name_en, d.name_hi, d.collectorate_details, d.zila_pramukh, div.name_en as division_name
            FROM public.districts d
            LEFT JOIN public.divisions div ON d.division_id = div.id
            WHERE d.name_en ILIKE $1 OR d.name_hi ILIKE $1
            LIMIT $2
        """, f"%{w}%", top_k)
        for r in d_rows:
            results.append({
                "type": "district",
                "title": f"District: {r['name_en']}",
                "snippet": f"District: {r['name_en']} ({r['name_hi'] or ''}), Division: {r['division_name']}, Collectorate: {r['collectorate_details']}, Zila Pramukh: {r['zila_pramukh']}"
            })

    await conn.close()
    # Deduplicate by snippet
    seen = set()
    deduped = []
    for item in results:
        if item["snippet"] not in seen:
            seen.add(item["snippet"])
            deduped.append(item)
    return deduped[:top_k]

async def perform_web_search(query: str, provider: str = "duckduckgo", api_key: str = "", max_results: int = 4):
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    # 1. Tavily Search
    if provider == "tavily" and api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": api_key,
                    "query": f"{query} Rajasthan",
                    "max_results": max_results
                })
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("results", []):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("content", ""),
                            "url": r.get("url", "")
                        })
                    return results
        except Exception as e:
            print("Tavily search error:", e)

    # 2. SerpAPI Search
    if provider == "serpapi" and api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("https://serpapi.com/search.json", params={
                    "q": f"{query} Rajasthan",
                    "api_key": api_key,
                    "num": max_results
                })
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("organic_results", []):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("snippet", ""),
                            "url": r.get("link", "")
                        })
                    return results
        except Exception as e:
            print("SerpAPI search error:", e)

    # 3. DuckDuckGo Fallback (Default, No Key Needed)
    try:
        search_query = query if "rajasthan" in query.lower() else f"{query} Rajasthan"
        encoded_q = quote_plus(search_query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", class_="result__url")
                snippets = soup.find_all("a", class_="result__snippet")
                for i in range(min(len(snippets), max_results)):
                    s_text = snippets[i].get_text(strip=True)
                    u_href = links[i]["href"] if i < len(links) and links[i].has_attr("href") else ""
                    if s_text:
                        results.append({
                            "title": f"Result {i+1}",
                            "snippet": s_text,
                            "url": u_href
                        })
    except Exception as e:
        print("DuckDuckGo error:", e)

    # 4. Wikipedia Quick Fallback if empty
    if not results:
        try:
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(query)}&format=json"
            async with httpx.AsyncClient(timeout=5.0) as client:
                wresp = await client.get(wiki_url)
                if wresp.status_code == 200:
                    items = wresp.json().get("query", {}).get("search", [])
                    for it in items[:max_results]:
                        clean_snip = re.sub(r"<[^>]+>", "", it.get("snippet", ""))
                        results.append({
                            "title": it.get("title", ""),
                            "snippet": clean_snip,
                            "url": f"https://en.wikipedia.org/wiki/{quote_plus(it.get('title',''))}"
                        })
        except Exception as e:
            print("Wikipedia error:", e)

    return results

async def test():
    print("=== Testing RAG Retrieval for '302029' ===")
    rag_res = await perform_rag_retrieval("302029", top_k=3)
    print("RAG Results:", len(rag_res))
    for r in rag_res:
        print(" -", r)

    print("\n=== Testing RAG Retrieval for 'Sanganer tehsil' ===")
    rag_res2 = await perform_rag_retrieval("Sanganer tehsil", top_k=3)
    print("RAG Results:", len(rag_res2))
    for r in rag_res2:
        print(" -", r)

    print("\n=== Testing Web Search for 'Chief Minister of Rajasthan' ===")
    web_res = await perform_web_search("Chief Minister of Rajasthan", provider="duckduckgo", max_results=3)
    print("Web Search Results:", len(web_res))
    for w in web_res:
        print(" - Title:", w["title"])
        print("   Snippet:", w["snippet"])
        print("   URL:", w["url"])

if __name__ == "__main__":
    asyncio.run(test())
