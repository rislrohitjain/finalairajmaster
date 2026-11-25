import asyncio
import asyncpg

async def count_all():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('public', 'raj_masters')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """
    tables = await conn.fetch(query)
    
    results = []
    for t in tables:
        schema = t["table_schema"]
        table = t["table_name"]
        try:
            cnt = await conn.fetchval(f'SELECT count(*) FROM "{schema}"."{table}"')
            results.append((schema, table, cnt))
        except Exception as e:
            results.append((schema, table, f"ERR: {e}"))
            
    await conn.close()
    
    print("SCHEMA|TABLE|COUNT")
    for s, t, c in results:
        print(f"{s}|{t}|{c}")

if __name__ == "__main__":
    asyncio.run(count_all())
