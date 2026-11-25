import asyncio
import asyncpg

async def update_greeting():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    await conn.execute("UPDATE public.llm_settings SET greeting_message = 'Welcome here chat with Jain''s only' WHERE id = 1;")
    msg = await conn.fetchval("SELECT greeting_message FROM public.llm_settings WHERE id = 1;")
    print("Updated greeting_message in db:", msg)
    await conn.close()

if __name__ == "__main__":
    asyncio.run(update_greeting())
