import asyncio
import asyncpg

async def test_sql():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    # Run analyze so stats are 100% fresh
    await conn.execute("ANALYZE;")
    
    # Test query
    sql1 = """
    SELECT 
        current_database() AS db_name,
        pg_size_pretty(pg_database_size(current_database())) AS db_size,
        schemaname,
        relname AS table_name,
        n_live_tup AS row_count
    FROM pg_stat_user_tables
    WHERE schemaname IN ('public', 'raj_masters')
    ORDER BY schemaname, relname;
    """
    rows = await conn.fetch(sql1)
    print("Row count via pg_stat_user_tables:")
    for r in rows[:10]:
        print(f"  {r['schemaname']}.{r['table_name']}: {r['row_count']}")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(test_sql())
