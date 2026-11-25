import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    exists = await conn.fetchval("SELECT to_regclass('public.rag_support')")
    print("rag_support exists:", exists)
    if exists:
        cols = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'rag_support'
            ORDER BY ordinal_position;
        """)
        for c in cols:
            print(f"  {c['column_name']}: {c['data_type']}")
    else:
        # Create it with JSONB for embedding if vector type is not on local host
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_support (
                id SERIAL PRIMARY KEY,
                record_type VARCHAR(10) NOT NULL,
                session_id VARCHAR(100),
                role VARCHAR(20),
                content TEXT NOT NULL,
                embedding JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("Created rag_support with JSONB embedding fallback on local host!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
