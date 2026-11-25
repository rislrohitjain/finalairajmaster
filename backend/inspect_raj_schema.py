import asyncio, asyncpg

async def test():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    for tbl in ["pincodes", "tehsils", "blocks"]:
        rows = await conn.fetch(f"""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'raj_masters' AND table_name = '{tbl}'
            ORDER BY ordinal_position;
        """)
        print(f"\nraj_masters.{tbl} columns:")
        for r in rows:
            print(f"  {r['column_name']}: {r['data_type']}")
    await conn.close()

asyncio.run(test())
