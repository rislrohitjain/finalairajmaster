import asyncio
import asyncpg

async def test_dynamic():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    # Single query that computes EXACT count dynamically for all tables + database details
    sql = """
    WITH table_counts AS (
        SELECT 
            table_schema,
            table_name,
            (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint AS exact_row_count,
            pg_size_pretty(pg_total_relation_size(format('%I.%I', table_schema, table_name)::regclass)) AS total_size
        FROM information_schema.tables
        WHERE table_schema IN ('public', 'raj_masters') 
          AND table_type = 'BASE TABLE'
    )
    SELECT 
        current_database() AS db_name,
        pg_size_pretty(pg_database_size(current_database())) AS db_size,
        version() AS pg_version,
        table_schema,
        table_name,
        exact_row_count,
        total_size,
        sum(exact_row_count) OVER () AS total_db_records,
        count(*) OVER () AS total_tables_count
    FROM table_counts
    ORDER BY table_schema, table_name;
    """
    rows = await conn.fetch(sql)
    print(f"Total rows returned: {len(rows)}")
    for r in rows[:10]:
        print(f"  {r['table_schema']}.{r['table_name']}: {r['exact_row_count']} rows, size: {r['total_size']}")
    print(f"First row db_size: {rows[0]['db_size']}, total_db_records: {rows[0]['total_db_records']}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(test_dynamic())
