import asyncio
import asyncpg
import httpx

async def run_tests():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    print("=== DATABASE TABLE COUNTS ===")
    t_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.tehsils")
    b_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.blocks")
    p_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.pincodes")
    pub_tb = await conn.fetchval("SELECT count(*) FROM public.tehsils_blocks")
    pub_pins = await conn.fetchval("SELECT count(*) FROM public.pincodes")
    print(f"raj_masters.tehsils: {t_cnt}")
    print(f"raj_masters.blocks: {b_cnt}")
    print(f"raj_masters.pincodes: {p_cnt}")
    print(f"public.tehsils_blocks: {pub_tb}")
    print(f"public.pincodes: {pub_pins}")

    print("\n=== SAMPLE PINCODE LOOKUP (342015) ===")
    p_row = await conn.fetchrow("""
        SELECT p.pincode, p.city_or_village, p.metadata_json, d.name_en as district, tb.name_en as subdistrict
        FROM public.pincodes p
        LEFT JOIN public.districts d ON p.district_id = d.id
        LEFT JOIN public.tehsils_blocks tb ON p.tehsil_block_id = tb.id
        WHERE p.pincode = '342015'
    """)
    if p_row:
        print(f"Pincode: {p_row['pincode']} | Area: {p_row['city_or_village']} | District: {p_row['district']} | Tehsil/Subdist: {p_row['subdistrict']}")
        print(f"Metadata: {p_row['metadata_json']}")

    print("\n=== SAMPLE TEHSIL LOOKUP (NECHHWA) ===")
    t_row = await conn.fetchrow("SELECT name_en, name_hi, code, tehsildar_details FROM raj_masters.tehsils WHERE name_en ILIKE '%NECHHWA%'")
    if t_row:
        print(f"Tehsil: {t_row['name_en']} ({t_row['name_hi']}) | Code: {t_row['code']} | {t_row['tehsildar_details']}")

    print("\n=== SAMPLE BLOCK LOOKUP (BHADRUNA) ===")
    b_row = await conn.fetchrow("SELECT name_en, name_hi, code, lgd_code, bdo_details FROM raj_masters.blocks WHERE name_en ILIKE '%BHADRUNA%'")
    if b_row:
        print(f"Block: {b_row['name_en']} ({b_row['name_hi']}) | Code: {b_row['code']} | LGD: {b_row['lgd_code']} | {b_row['bdo_details']}")

    await conn.close()

    print("\n=== CHATBOT LIVE AGENT TEST ===")
    client = httpx.AsyncClient(timeout=30.0)
    for q in ["Details of pincode 342015 in Rajasthan", "Tell me about Nechhwa tehsil in Rajasthan"]:
        r = await client.post("http://localhost:8000/api/chat", json={
            "session_id": "test-sync-verify",
            "message": q
        })
        if r.status_code == 200:
            res = r.json()
            print(f"\nQuery: '{q}'")
            print(f"Intent: {res.get('intent')}")
            print(f"Breadcrumbs: {res.get('breadcrumbs')}")
            print(f"Response Preview:\n{res.get('response', '')[:250]}...")
        else:
            print(f"Error {r.status_code}: {r.text}")
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(run_tests())
