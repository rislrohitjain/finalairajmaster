import asyncio, asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    rows = await conn.fetch("""
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_schema IN ('public', 'raj_masters') AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """)
    for r in rows:
        cnt = await conn.fetchval(f'SELECT count(*) FROM "{r["table_schema"]}"."{r["table_name"]}"')
        print(f"{r['table_schema']}.{r['table_name']}: {cnt}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
