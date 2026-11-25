import asyncio
import httpx

async def test_pagination():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
    client = httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True, headers=headers)
    try:
        # Check what parameters the portal accepts
        # Case A: JSON with Size and Page
        rA = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", json={
            "master": "PINCODE RAJASTHAN", "Page": 1, "Size": 5,
            "DistrictId": "0", "TehsilId": "0", "BlockId": "0"
        })
        print("Case A (json Page/Size): status", rA.status_code, "data len:", len(rA.json().get("data", [])) if rA.status_code == 200 else rA.text[:100])
        
        # Case B: form data with start / length
        rB = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", data={
            "master": "PINCODE RAJASTHAN", "start": "0", "length": "5",
            "DistrictId": "0", "TehsilId": "0", "BlockId": "0"
        })
        print("Case B (data start/length): status", rB.status_code, "data len:", len(rB.json().get("data", [])) if rB.status_code == 200 else rB.text[:100])
        
        # Test pagination with data: start=5, length=5
        rC = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", data={
            "master": "PINCODE RAJASTHAN", "start": "5", "length": "5",
            "DistrictId": "0", "TehsilId": "0", "BlockId": "0"
        })
        if rC.status_code == 200:
            dC = rC.json().get("data", [])
            print("Case C (data start=5, length=5): len:", len(dC))
            if dC:
                print("First item in C:", dC[0])

    finally:
        await client.aclose()

if __name__ == "__main__":
    asyncio.run(test_pagination())
