import asyncio
import asyncpg

async def check_pgvector():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("pgvector extension enabled successfully!")
        
        # Test creating rag_support table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_support (
                id SERIAL PRIMARY KEY,
                record_type VARCHAR(10) NOT NULL,
                session_id VARCHAR(100),
                role VARCHAR(20),
                content TEXT NOT NULL,
                embedding VECTOR(384),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        print("rag_support table created successfully!")
        
        cols = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'rag_support'
            ORDER BY ordinal_position;
        """)
        for c in cols:
            print(f"  {c['column_name']}: {c['data_type']}")
            
    except Exception as e:
        print("pgvector error:", e)
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(check_pgvector())
