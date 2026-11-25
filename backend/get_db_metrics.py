import asyncio
import asyncpg

async def db_summary():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    db_name = await conn.fetchval("SELECT current_database()")
    db_size = await conn.fetchval("SELECT pg_size_pretty(pg_database_size(current_database()))")
    pg_version = await conn.fetchval("SELECT version()")
    
    tables = await conn.fetch("""
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_schema IN ('public', 'raj_masters') AND table_type = 'BASE TABLE'
    """)
    
    pub_rows = 0
    rm_rows = 0
    pub_tables = 0
    rm_tables = 0
    
    for t in tables:
        s = t["table_schema"]
        tbl = t["table_name"]
        cnt = await conn.fetchval(f'SELECT count(*) FROM "{s}"."{tbl}"')
        if s == 'public':
            pub_tables += 1
            pub_rows += cnt
        else:
            rm_tables += 1
            rm_rows += cnt
            
    print(f"DATABASE: {db_name}")
    print(f"SIZE: {db_size}")
    print(f"VERSION: {pg_version.split(',')[0]}")
    print(f"PUBLIC_TABLES: {pub_tables}")
    print(f"PUBLIC_ROWS: {pub_rows:,}")
    print(f"RAJ_MASTERS_TABLES: {rm_tables}")
    print(f"RAJ_MASTERS_ROWS: {rm_rows:,}")
    print(f"TOTAL_TABLES: {len(tables)}")
    print(f"TOTAL_ROWS: {pub_rows + rm_rows:,}")
    
    print("\n--- ADMINISTRATIVE TOTALS (PUBLIC APPLICATION LAYER) ---")
    for entity, tbl in [
        ("Divisions", "divisions"),
        ("Districts", "districts"),
        ("Sub-Divisions", "sub_divisions"),
        ("Tehsils & Blocks", "tehsils_blocks"),
        ("Gram Panchayats", "gram_panchayats"),
        ("Villages", "villages"),
        ("Urban Local Bodies", "urban_local_bodies"),
        ("Urban Wards", "urban_wards"),
        ("Pincodes", "pincodes")
    ]:
        val = await conn.fetchval(f'SELECT count(*) FROM public."{tbl}"')
        print(f"{entity}: {val:,}")

    print("\n--- RAJ MASTERS ETL PORTAL LAYER ---")
    for entity, tbl in [
        ("Divisions", "divisions"),
        ("Districts", "districts"),
        ("Sub-Divisions", "sub_divisions"),
        ("Tehsils", "tehsils"),
        ("Blocks", "blocks"),
        ("Pincodes", "pincodes"),
        ("Sync Audit Logs", "sync_audit_log")
    ]:
        val = await conn.fetchval(f'SELECT count(*) FROM raj_masters."{tbl}"')
        print(f"{entity}: {val:,}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(db_summary())
