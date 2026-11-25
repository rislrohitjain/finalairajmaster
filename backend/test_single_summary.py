import asyncio
import asyncpg

async def test_summary_query():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    sql = """
    SELECT 
        current_database() AS database_name,
        pg_size_pretty(pg_database_size(current_database())) AS database_size,
        version() AS postgres_version,
        (SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('public', 'raj_masters') AND table_type = 'BASE TABLE') AS total_tables,
        (
            SELECT sum((xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint)
            FROM information_schema.tables
            WHERE table_schema IN ('public', 'raj_masters') AND table_type = 'BASE TABLE'
        ) AS total_records;
    """
    row = await conn.fetchrow(sql)
    print("Database Summary:")
    for k, v in row.items():
        print(f"  {k}: {v}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(test_summary_query())
