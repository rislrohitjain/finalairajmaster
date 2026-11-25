import asyncio
import asyncpg

async def run():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    # 1. DB Details Single Query
    db_info = await conn.fetchrow("""
        SELECT 
            current_database() AS database_name,
            version() AS postgres_version,
            pg_size_pretty(pg_database_size(current_database())) AS database_total_size,
            pg_encoding_to_char(encoding) AS encoding,
            (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS active_connections
        FROM pg_database 
        WHERE datname = current_database();
    """)
    print("=== DATABASE DETAILS ===")
    for k, v in db_info.items():
        print(f"{k}: {v}")
    
    # 2. Table Counts Single Query
    table_counts = await conn.fetch("""
        SELECT 
            table_schema,
            table_name,
            (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint AS total_records,
            pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) AS table_size
        FROM information_schema.tables
        WHERE table_schema IN ('public', 'raj_masters')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """)
    print("\n=== TABLE COUNTS ===")
    for r in table_counts:
        print(f"{r['table_schema']}|{r['table_name']}|{r['total_records']}|{r['table_size']}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
