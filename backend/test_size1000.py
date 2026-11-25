import asyncio, httpx

async def test():
    client = httpx.AsyncClient(timeout=60.0, verify=False)
    p = await client.post("https://rajmasters.rajasthan.gov.in/Home/ListData", json={"master": "PINCODE RAJASTHAN", "Page": 1, "Size": 1000})
    d = p.json()
    print("TotalCount:", d.get("TotalCount"), "returned records:", len(d.get("data", [])))
    await client.aclose()

asyncio.run(test())
