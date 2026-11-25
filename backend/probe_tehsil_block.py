import asyncio
import httpx

async def probe():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
    client = httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True, headers=headers)
    try:
        for m in ["TEHSIL RAJASTHAN", "BLOCK RAJASTHAN"]:
            r = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", data={
                "master": m, "start": "0", "length": "2",
                "DivisionId": "0", "DistrictId": "0", "SubDivisionId": "0",
                "TehsilId": "0", "BlockId": "0", "PanchayatId": "0", "VillageId": "0",
            })
            if r.status_code == 200:
                rows = r.json().get("data", [])
                print(f"{m} (count={len(rows)}):")
                if rows:
                    print("  Type:", type(rows[0]))
                    print("  Sample:", rows[0])
    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(probe())
