import asyncio
import httpx
import json

async def probe():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
    client = httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True, headers=headers)
    try:
        r1 = await client.get("https://rajmasters.rajasthan.gov.in/Home/List?master=PINCODE RAJASTHAN")
        payload = {
            "master": "PINCODE RAJASTHAN",
            "start": "0",
            "length": "5",
            "DivisionId": "0",
            "DistrictId": "0",
            "SubDivisionId": "0",
            "TehsilId": "0",
            "BlockId": "0",
            "PanchayatId": "0",
            "VillageId": "0",
        }
        r2 = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", data=payload)
        if r2.status_code == 200:
            data = r2.json()
            rows = data.get("data") or data.get("aaData") or []
            print(f"Sample rows count: {len(rows)}")
            for i, r in enumerate(rows[:3]):
                print(f"Row {i} type: {type(r)}, value: {r}")
            # Also let's inspect the HTML of Home/List to see column names in table header
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r1.text, "html.parser")
            th_tags = [th.get_text(strip=True) for th in soup.find_all("th")]
            print("Table headers:", th_tags)
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(probe())
