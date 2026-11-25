import asyncio
import httpx
from app.auth import create_access_token

async def test_admin_geo():
    token = create_access_token(data={"sub": "8946919241", "role": "admin"})
    headers = {"Authorization": f"Bearer {token}"}
    
    # We can use httpx.AsyncClient with ASGI app
    from app.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Test get districts
        r = await client.get("/api/admin/geo-records?level=district&limit=5", headers=headers)
        print("Districts status:", r.status_code)
        assert r.status_code == 200, r.text
        data = r.json()
        print(f"Districts total: {data['total']}, fetched: {len(data['records'])}")
        first_dist = data['records'][0]
        print(f"First district: #{first_dist['id']} {first_dist['name_en']} ({first_dist['authority_details']})")
        
        # 2. Test get divisions
        r = await client.get("/api/admin/geo-records?level=division&limit=5", headers=headers)
        print("Divisions status:", r.status_code)
        assert r.status_code == 200
        div_data = r.json()
        print(f"Divisions total: {div_data['total']}, first: {div_data['records'][0]['name_en']}")

        # 3. Test get tehsils
        r = await client.get("/api/admin/geo-records?level=tehsil_block&limit=5", headers=headers)
        print("Tehsils status:", r.status_code)
        assert r.status_code == 200

        # 4. Test get villages
        r = await client.get("/api/admin/geo-records?level=village&limit=5", headers=headers)
        print("Villages status:", r.status_code)
        assert r.status_code == 200

        # 5. Test get pincodes
        r = await client.get("/api/admin/geo-records?level=pincode&limit=5", headers=headers)
        print("Pincodes status:", r.status_code)
        assert r.status_code == 200

        # 6. Test update district record
        dist_id = first_dist['id']
        old_auth = first_dist['authority_details']
        new_auth = f"{old_auth} [Verified Master]"
        put_r = await client.put(
            f"/api/admin/geo-record/district/{dist_id}",
            json={"authority_details": new_auth},
            headers=headers
        )
        print("PUT status:", put_r.status_code, put_r.json())
        assert put_r.status_code == 200

        # Verify update persisted
        r_check = await client.get(f"/api/admin/geo-records?level=district&search={first_dist['name_en']}", headers=headers)
        matched = [x for x in r_check.json()['records'] if x['id'] == dist_id][0]
        print(f"Updated record in DB: #{matched['id']} authority: {matched['authority_details']}")
        assert "[Verified Master]" in matched['authority_details']

        # Revert update
        await client.put(
            f"/api/admin/geo-record/district/{dist_id}",
            json={"authority_details": old_auth},
            headers=headers
        )
        print("Reverted cleanly!")
        print("ALL ADMIN GEO API TESTS PASSED!")

if __name__ == "__main__":
    asyncio.run(test_admin_geo())
