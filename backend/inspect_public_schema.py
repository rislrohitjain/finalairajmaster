import asyncio, asyncpg

async def test():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    rows = await conn.fetch("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'pincodes'
        ORDER BY ordinal_position;
    """)
    print("public.pincodes columns:")
    for r in rows:
        print(f"  {r['column_name']}: {r['data_type']} (nullable={r['is_nullable']})")
    
    rows2 = await conn.fetch("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'tehsils_blocks'
        ORDER BY ordinal_position;
    """)
    print("\npublic.tehsils_blocks columns:")
    for r in rows2:
        print(f"  {r['column_name']}: {r['data_type']} (nullable={r['is_nullable']})")

    await conn.close()

asyncio.run(test())
