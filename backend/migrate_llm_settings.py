import asyncio
import asyncpg

async def migrate_llm_settings():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    columns_to_add = [
        ("enable_rag", "BOOLEAN DEFAULT TRUE"),
        ("rag_top_k", "INTEGER DEFAULT 5"),
        ("enable_web_search", "BOOLEAN DEFAULT TRUE"),
        ("web_search_provider", "VARCHAR(50) DEFAULT 'duckduckgo'"),
        ("web_search_api_key", "VARCHAR(255) DEFAULT ''"),
        ("web_search_max_results", "INTEGER DEFAULT 4")
    ]
    
    for col_name, col_type in columns_to_add:
        try:
            await conn.execute(f"ALTER TABLE public.llm_settings ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
            print(f"Added column {col_name} ({col_type})")
        except Exception as e:
            print(f"Column {col_name} notice: {e}")
            
    # Check current row
    row = await conn.fetchrow("SELECT * FROM public.llm_settings WHERE id = 1")
    print("\nUpdated public.llm_settings row:")
    for k, v in row.items():
        print(f"  {k}: {v}")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(migrate_llm_settings())
