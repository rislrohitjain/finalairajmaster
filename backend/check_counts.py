import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    print("--- raj_masters schema ---")
    for tbl in ["divisions", "districts", "sub_divisions", "tehsils", "blocks", "pincodes"]:
        try:
            cnt = await conn.fetchval(f"SELECT count(*) FROM raj_masters.{tbl}")
            print(f"raj_masters.{tbl}: {cnt}")
        except Exception as e:
            print(f"raj_masters.{tbl}: ERROR {e}")

    print("\n--- public schema ---")
    for tbl in ["divisions", "districts", "sub_divisions", "tehsils_blocks", "pincodes"]:
        try:
            cnt = await conn.fetchval(f"SELECT count(*) FROM public.{tbl}")
            print(f"public.{tbl}: {cnt}")
        except Exception as e:
            print(f"public.{tbl}: ERROR {e}")
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
