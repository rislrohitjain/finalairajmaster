import asyncio, httpx

async def test():
    client = httpx.AsyncClient(timeout=60.0, verify=False)
    p1 = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", json={"master": "PINCODE RAJASTHAN", "Page": 1, "Size": 2})
    p2 = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", json={"master": "PINCODE RAJASTHAN", "Page": 2, "Size": 2})
    print("Page 1 first id:", p1.json()["data"][0][0])
    print("Page 2 first id:", p2.json()["data"][0][0])
    await client.aclose()

asyncio.run(test())
