import asyncio
import httpx
import re
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

async def search_duckduckgo(query: str, max_results: int = 4):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    encoded_q = quote_plus(f"{query} Rajasthan government")
    url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
    
    results = []
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
        print("DDG HTML Status:", resp.status_code)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            snippets = soup.find_all("a", class_="result__snippet")
            titles = soup.find_all("a", class_="result__url")
            for s in snippets[:max_results]:
                text = s.get_text(strip=True)
                if text:
                    results.append(text)
    return results

async def main():
    res = await search_duckduckgo("Collector of Jaipur district")
    print("Found snippets:", len(res))
    for i, s in enumerate(res):
        print(f"{i+1}. {s}")

if __name__ == "__main__":
    asyncio.run(main())
