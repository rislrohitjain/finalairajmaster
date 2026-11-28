"""
Complete Rajasthan Block & Gram Panchayat Synchronization Pipeline (Local PostgreSQL)
Fetches:
  1. BLOCK RAJASTHAN (457 records)
  2. GRAM PANCHAYAT RAJASTHAN (14,496 records)
from https://rajmasters.rajasthan.gov.in/Home/ListData, stores raw archives in
raj_masters.block_hierarchy and raj_masters.gp_hierarchy, updates raj_masters.blocks,
and normalizes/enriches public.tehsils_blocks and public.gram_panchayats (including
name_hi, code, lgd_code, district_id, tehsil_block_id, and metadata_json).
"""
import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sync_blocks_and_gps")

DB_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://postgres:Admin%40123@127.0.0.1:5432/finalairajmaster",
)
PORTAL_URL = "https://rajmasters.rajasthan.gov.in"


def parse_row(item: Any) -> Dict[str, Any]:
    if isinstance(item, list):
        return {kv["Key"]: kv.get("Value") for kv in item if isinstance(kv, dict) and "Key" in kv}
    if isinstance(item, dict):
        return item
    return {}


def safe_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def clean_str(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = re.sub(r"\s+", " ", str(val).strip())
    return s if s else None


async def fetch_master(master_name: str, page_size: int = 1000, concurrency: int = 3) -> List[Dict[str, Any]]:
    headers_get = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    headers_post = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": f"{PORTAL_URL}/Home/List?master={master_name}",
    }

    async with httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True) as client:
        r0 = await client.get(f"{PORTAL_URL}/Home/List?master={master_name}", headers=headers_get)
        logger.info(f"[{master_name}] Session init GET status: {r0.status_code}")

        async def fetch_page(page: int) -> Tuple[List[Dict[str, Any]], int]:
            payload = {
                "master": master_name,
                "Page": page,
                "Size": page_size,
                "DivisionId": "",
                "DistrictId": "0",
                "TehsilId": "0",
                "BlockId": "0",
            }
            for attempt in range(5):
                try:
                    resp = await client.post(f"{PORTAL_URL}/Home/ListData", json=payload, headers=headers_post)
                    resp.raise_for_status()
                    data = resp.json()
                    raw_rows = data.get("data") or []
                    total_count = int(data.get("TotalCount") or 0)
                    parsed = [parse_row(r) for r in raw_rows if parse_row(r)]
                    return parsed, total_count
                except Exception as exc:
                    if attempt == 4:
                        raise
                    wait_s = 2 * (attempt + 1)
                    logger.warning(f"[{master_name}] Page {page} attempt {attempt+1} failed ({exc}), retrying in {wait_s}s...")
                    await asyncio.sleep(wait_s)
            return [], 0

        page1_rows, total_count = await fetch_page(1)
        logger.info(f"[{master_name}] Portal TotalCount={total_count}; Page 1 fetched {len(page1_rows)} rows.")
        total_pages = (total_count + page_size - 1) // page_size if total_count else 1
        by_page: Dict[int, List[Dict[str, Any]]] = {1: page1_rows}

        if total_pages > 1:
            sem = asyncio.Semaphore(concurrency)

            async def worker(p: int):
                async with sem:
                    rows, _ = await fetch_page(p)
                    by_page[p] = rows
                    if p % 5 == 0 or p == total_pages:
                        cum = sum(len(v) for v in by_page.values())
                        logger.info(f"[{master_name}] Fetched page {p}/{total_pages} (cumulative ~{cum}/{total_count})")

            await asyncio.gather(*(worker(p) for p in range(2, total_pages + 1)))

        out: List[Dict[str, Any]] = []
        for p in range(1, total_pages + 1):
            out.extend(by_page.get(p, []))
        return out


async def sync_all(from_db: bool = False):
    t_start = time.time()
    conn = await asyncpg.connect(DB_DSN)
    try:
        # Ensure archive tables and GIN trigram indexes exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS raj_masters.block_hierarchy (
                id BIGSERIAL PRIMARY KEY,
                block_id BIGINT UNIQUE NOT NULL,
                block_code VARCHAR(50),
                block_lgdcode BIGINT,
                block_eng TEXT NOT NULL,
                block_mangal TEXT,
                division_id BIGINT,
                division_eng TEXT,
                district_id BIGINT,
                district_eng TEXT,
                raw_payload JSONB DEFAULT '{}'::jsonb,
                synced_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_rm_bh_eng_trgm ON raj_masters.block_hierarchy USING gin (block_eng gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_bh_hi_trgm ON raj_masters.block_hierarchy USING gin (block_mangal gin_trgm_ops);

            CREATE TABLE IF NOT EXISTS raj_masters.gp_hierarchy (
                id BIGSERIAL PRIMARY KEY,
                gp_id BIGINT UNIQUE NOT NULL,
                gp_code VARCHAR(50),
                gp_lgdcode BIGINT,
                gp_eng TEXT NOT NULL,
                gp_mangal TEXT,
                division_id BIGINT,
                division_eng TEXT,
                district_id BIGINT,
                district_eng TEXT,
                block_id BIGINT,
                block_eng TEXT,
                raw_payload JSONB DEFAULT '{}'::jsonb,
                synced_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_rm_gph_eng_trgm ON raj_masters.gp_hierarchy USING gin (gp_eng gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_gph_hi_trgm ON raj_masters.gp_hierarchy USING gin (gp_mangal gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_gph_block_id ON raj_masters.gp_hierarchy(block_id);
            CREATE INDEX IF NOT EXISTS idx_rm_gph_district_id ON raj_masters.gp_hierarchy(district_id);

            CREATE INDEX IF NOT EXISTS idx_pub_gp_name_hi_trgm ON public.gram_panchayats USING gin (name_hi gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_pub_tb_name_en_trgm ON public.tehsils_blocks USING gin (name_en gin_trgm_ops);
        """)

        if from_db:
            b_rows = [dict(r) for r in await conn.fetch("""
                SELECT division_id AS "DIVISION_ID", division_eng AS "DIVISION_ENG",
                       district_id AS "DISTRICT_ID", district_eng AS "DISTRICT_ENG",
                       block_id AS "BLOCK_ID", block_code AS "BLOCK_CODE",
                       block_lgdcode AS "BLOCK_LGCODE", block_eng AS "BLOCK_ENG",
                       block_mangal AS "BLOCK_MANGAL"
                FROM raj_masters.block_hierarchy
            """)]
            gp_rows = [dict(r) for r in await conn.fetch("""
                SELECT division_id AS "DIVISION_ID", division_eng AS "DIVISION_ENG",
                       district_id AS "DISTRICT_ID", district_eng AS "DISTRICT_ENG",
                       block_id AS "BLOCK_ID", block_eng AS "BLOCK_ENG",
                       gp_id AS "GP_ID", gp_code AS "GP_CODE",
                       gp_lgdcode AS "GP_LGCODE", gp_eng AS "GP_ENG",
                       gp_mangal AS "GP_MANGAL"
                FROM raj_masters.gp_hierarchy
            """)]
        else:
            logger.info("Fetching BLOCK RAJASTHAN and GRAM PANCHAYAT RAJASTHAN from portal...")
            b_rows = await fetch_master("BLOCK RAJASTHAN", page_size=1000, concurrency=2)
            gp_rows = await fetch_master("GRAM PANCHAYAT RAJASTHAN", page_size=1000, concurrency=3)

        # Deduplicate
        blocks_by_id: Dict[int, Dict[str, Any]] = {}
        for r in b_rows:
            bid = safe_int(r.get("BLOCK_ID"))
            if bid is not None:
                blocks_by_id[bid] = r
        unique_blocks = list(blocks_by_id.values())

        gps_by_id: Dict[int, Dict[str, Any]] = {}
        for r in gp_rows:
            gid = safe_int(r.get("GP_ID"))
            if gid is not None:
                gps_by_id[gid] = r
        unique_gps = list(gps_by_id.values())

        logger.info(f"Unique Blocks: {len(unique_blocks)}, Unique Gram Panchayats: {len(unique_gps)}")

        # 1. Upsert raj_masters.block_hierarchy
        bh_batch = []
        for r in unique_blocks:
            bid = safe_int(r.get("BLOCK_ID"))
            bh_batch.append((
                bid,
                clean_str(r.get("BLOCK_CODE")),
                safe_int(r.get("BLOCK_LGCODE")),
                clean_str(r.get("BLOCK_ENG")) or f"Block {bid}",
                clean_str(r.get("BLOCK_MANGAL")),
                safe_int(r.get("DIVISION_ID")),
                clean_str(r.get("DIVISION_ENG")),
                safe_int(r.get("DISTRICT_ID")),
                clean_str(r.get("DISTRICT_ENG")),
                json.dumps(r),
            ))

        await conn.executemany("""
            INSERT INTO raj_masters.block_hierarchy
            (block_id, block_code, block_lgdcode, block_eng, block_mangal,
             division_id, division_eng, district_id, district_eng, raw_payload, synced_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,NOW())
            ON CONFLICT (block_id) DO UPDATE SET
                block_code = EXCLUDED.block_code,
                block_lgdcode = EXCLUDED.block_lgdcode,
                block_eng = EXCLUDED.block_eng,
                block_mangal = EXCLUDED.block_mangal,
                division_id = EXCLUDED.division_id,
                division_eng = EXCLUDED.division_eng,
                district_id = EXCLUDED.district_id,
                district_eng = EXCLUDED.district_eng,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """, bh_batch)

        # Also update raj_masters.blocks where district_id exists in raj_masters.districts
        rm_dist_ids = {r["raj_master_id"] for r in await conn.fetch("SELECT raj_master_id FROM raj_masters.districts")}
        rm_b_batch = []
        for r in unique_blocks:
            bid = safe_int(r.get("BLOCK_ID"))
            did = safe_int(r.get("DISTRICT_ID"))
            if did not in rm_dist_ids:
                did = None
            b_eng = clean_str(r.get("BLOCK_ENG")) or f"Block {bid}"
            rm_b_batch.append((
                bid,
                did,
                clean_str(r.get("BLOCK_CODE")),
                str(r.get("BLOCK_LGCODE") or "") or None,
                b_eng,
                clean_str(r.get("BLOCK_MANGAL")),
                f"Block Development Officer (BDO), {b_eng}",
                json.dumps(r),
            ))
        await conn.executemany("""
            INSERT INTO raj_masters.blocks
            (raj_master_id, district_id, code, lgd_code, name_en, name_hi, bdo_details, raw_payload, synced_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = COALESCE(EXCLUDED.district_id, raj_masters.blocks.district_id),
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                bdo_details = EXCLUDED.bdo_details,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """, rm_b_batch)

        # 2. Upsert raj_masters.gp_hierarchy
        gph_batch = []
        for r in unique_gps:
            gid = safe_int(r.get("GP_ID"))
            gph_batch.append((
                gid,
                clean_str(r.get("GP_CODE")),
                safe_int(r.get("GP_LGCODE")),
                clean_str(r.get("GP_ENG")) or f"GP {gid}",
                clean_str(r.get("GP_MANGAL")),
                safe_int(r.get("DIVISION_ID")),
                clean_str(r.get("DIVISION_ENG")),
                safe_int(r.get("DISTRICT_ID")),
                clean_str(r.get("DISTRICT_ENG")),
                safe_int(r.get("BLOCK_ID")),
                clean_str(r.get("BLOCK_ENG")),
                json.dumps(r),
            ))

        chunk_size = 3000
        for i in range(0, len(gph_batch), chunk_size):
            chunk = gph_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO raj_masters.gp_hierarchy
                (gp_id, gp_code, gp_lgdcode, gp_eng, gp_mangal,
                 division_id, division_eng, district_id, district_eng,
                 block_id, block_eng, raw_payload, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,NOW())
                ON CONFLICT (gp_id) DO UPDATE SET
                    gp_code = EXCLUDED.gp_code,
                    gp_lgdcode = EXCLUDED.gp_lgdcode,
                    gp_eng = EXCLUDED.gp_eng,
                    gp_mangal = EXCLUDED.gp_mangal,
                    division_id = EXCLUDED.division_id,
                    division_eng = EXCLUDED.division_eng,
                    district_id = EXCLUDED.district_id,
                    district_eng = EXCLUDED.district_eng,
                    block_id = EXCLUDED.block_id,
                    block_eng = EXCLUDED.block_eng,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, chunk)

        # 3. Sync public.tehsils_blocks for all 457 Blocks
        pub_dists = await conn.fetch("SELECT id, rajmaster_id, name_en FROM public.districts ORDER BY id ASC")
        dist_by_rm_id = {d["rajmaster_id"]: d["id"] for d in pub_dists if d["rajmaster_id"]}
        dist_by_name = {d["name_en"].upper().strip(): d["id"] for d in pub_dists}

        pub_blocks_existing = await conn.fetch("""
            SELECT id, rajmaster_id, district_id, name_en
            FROM public.tehsils_blocks
            WHERE entity_type LIKE '%Block%'
        """)
        block_id_by_rm = {b["rajmaster_id"]: b["id"] for b in pub_blocks_existing if b["rajmaster_id"]}
        block_id_by_dist_name = {
            (b["district_id"], (b["name_en"] or "").upper().strip()): b["id"]
            for b in pub_blocks_existing if b["district_id"] and b["name_en"]
        }

        for r in unique_blocks:
            bid = safe_int(r.get("BLOCK_ID"))
            b_eng = clean_str(r.get("BLOCK_ENG")) or f"Block {bid}"
            b_hi = clean_str(r.get("BLOCK_MANGAL"))
            b_code = clean_str(r.get("BLOCK_CODE"))
            b_lgd = safe_int(r.get("BLOCK_LGCODE"))
            rm_dist_id = safe_int(r.get("DISTRICT_ID"))
            dist_eng = clean_str(r.get("DISTRICT_ENG")) or ""
            pub_dist_id = dist_by_rm_id.get(rm_dist_id) or dist_by_name.get(dist_eng.upper())
            bdo = f"Block Development Officer (BDO), {b_eng}"
            meta = json.dumps({
                "source": "rajmasters_block_sync",
                "raj_master_id": bid,
                "division_id": safe_int(r.get("DIVISION_ID")),
                "division": clean_str(r.get("DIVISION_ENG")),
                "district": dist_eng,
            })

            existing_id = block_id_by_rm.get(bid) or (block_id_by_dist_name.get((pub_dist_id, b_eng.upper())) if pub_dist_id else None)
            if existing_id:
                await conn.execute("""
                    UPDATE public.tehsils_blocks SET
                        district_id = COALESCE($1, district_id),
                        rajmaster_id = $2,
                        code = COALESCE($3, code),
                        name_en = $4,
                        name_hi = COALESCE($5, name_hi),
                        bdo_details = COALESCE($6, bdo_details),
                        lgd_code = COALESCE($7, lgd_code),
                        metadata_json = $8::jsonb,
                        updated_at = NOW()
                    WHERE id = $9
                """, pub_dist_id, bid, b_code, b_eng[:150], b_hi[:150] if b_hi else None, bdo[:255], b_lgd, meta, existing_id)
            else:
                new_id = await conn.fetchval("""
                    INSERT INTO public.tehsils_blocks
                    (district_id, rajmaster_id, code, name_en, name_hi, entity_type, bdo_details, lgd_code, metadata_json, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, 'Panchayat Samiti / Block', $6, $7, $8::jsonb, NOW(), NOW())
                    RETURNING id
                """, pub_dist_id, bid, b_code, b_eng[:150], b_hi[:150] if b_hi else None, bdo[:255], b_lgd, meta)
                block_id_by_rm[bid] = new_id

        # Refresh block map after sync
        pub_blocks_all = await conn.fetch("SELECT id, rajmaster_id, district_id, name_en FROM public.tehsils_blocks WHERE entity_type LIKE '%Block%'")
        tb_by_rm = {b["rajmaster_id"]: b["id"] for b in pub_blocks_all if b["rajmaster_id"]}
        tb_by_dist_name = {(b["district_id"], (b["name_en"] or "").upper().strip()): b["id"] for b in pub_blocks_all if b["district_id"] and b["name_en"]}

        # 4. Sync all 14,496 Gram Panchayats into public.gram_panchayats
        logger.info(f"Upserting {len(unique_gps)} Gram Panchayats into public.gram_panchayats...")
        gp_batch = []
        for r in unique_gps:
            gid = safe_int(r.get("GP_ID"))
            gp_eng = clean_str(r.get("GP_ENG")) or f"GP {gid}"
            gp_hi = clean_str(r.get("GP_MANGAL"))
            gp_code = clean_str(r.get("GP_CODE"))
            gp_lgd = safe_int(r.get("GP_LGCODE"))
            rm_dist_id = safe_int(r.get("DISTRICT_ID"))
            dist_eng = clean_str(r.get("DISTRICT_ENG")) or ""
            pub_dist_id = dist_by_rm_id.get(rm_dist_id) or dist_by_name.get(dist_eng.upper())

            rm_block_id = safe_int(r.get("BLOCK_ID"))
            block_eng = clean_str(r.get("BLOCK_ENG")) or ""
            pub_tb_id = (
                (tb_by_rm.get(rm_block_id) if rm_block_id else None)
                or (tb_by_dist_name.get((pub_dist_id, block_eng.upper())) if pub_dist_id and block_eng else None)
            )
            sarpanch = f"Sarpanch, GP {gp_eng}"
            meta = json.dumps({
                "source": "rajmasters_gp_sync",
                "division_id": safe_int(r.get("DIVISION_ID")),
                "division": clean_str(r.get("DIVISION_ENG")),
                "district": dist_eng,
                "block_id": rm_block_id,
                "block_eng": block_eng,
            })
            gp_batch.append((
                gid,
                pub_dist_id,
                pub_tb_id,
                gp_code[:50] if gp_code else None,
                gp_eng[:150],
                gp_hi[:150] if gp_hi else None,
                sarpanch[:150],
                gp_lgd,
                meta,
            ))

        for i in range(0, len(gp_batch), chunk_size):
            chunk = gp_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO public.gram_panchayats
                (rajmaster_id, district_id, tehsil_block_id, code, name_en, name_hi, sarpanch, lgd_code, metadata_json, created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,NOW(),NOW())
                ON CONFLICT (rajmaster_id) DO UPDATE SET
                    district_id = COALESCE(EXCLUDED.district_id, public.gram_panchayats.district_id),
                    tehsil_block_id = COALESCE(EXCLUDED.tehsil_block_id, public.gram_panchayats.tehsil_block_id),
                    code = COALESCE(EXCLUDED.code, public.gram_panchayats.code),
                    name_en = EXCLUDED.name_en,
                    name_hi = COALESCE(EXCLUDED.name_hi, public.gram_panchayats.name_hi),
                    sarpanch = COALESCE(public.gram_panchayats.sarpanch, EXCLUDED.sarpanch),
                    lgd_code = COALESCE(EXCLUDED.lgd_code, public.gram_panchayats.lgd_code),
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW();
            """, chunk)

        # Link any villages whose metadata_json->>'gp_id' matches newly added GPs
        await conn.execute("""
            UPDATE public.villages v
            SET gram_panchayat_id = gp.id,
                updated_at = NOW()
            FROM public.gram_panchayats gp
            WHERE v.gram_panchayat_id IS NULL
              AND v.metadata_json->>'gp_id' IS NOT NULL
              AND (v.metadata_json->>'gp_id')::bigint = gp.rajmaster_id
        """)

        # Audit logs
        duration = round(time.time() - t_start, 2)
        await conn.execute("""
            INSERT INTO public.scraper_runs (master_name, status, rows_fetched, rows_upserted, error_logs, started_at, completed_at)
            VALUES
              ('BLOCK RAJASTHAN', 'completed', $1, $1, NULL, NOW() - ($3::double precision * interval '1 second'), NOW()),
              ('GRAM PANCHAYAT RAJASTHAN', 'completed', $2, $2, NULL, NOW() - ($3::double precision * interval '1 second'), NOW())
        """, len(unique_blocks), len(unique_gps), duration)

        await conn.execute("""
            INSERT INTO raj_masters.sync_audit_log (master_name, tier_level, expected_count, fetched_count, upserted_count, status, duration_seconds, mode, created_at, completed_at)
            VALUES
              ('BLOCK RAJASTHAN', 3, $1, $1, $1, 'COMPLETED', $3::numeric, 'full', NOW() - ($4::double precision * interval '1 second'), NOW()),
              ('GRAM PANCHAYAT RAJASTHAN', 4, $2, $2, $2, 'COMPLETED', $3::numeric, 'full', NOW() - ($4::double precision * interval '1 second'), NOW())
        """, len(unique_blocks), len(unique_gps), duration, duration)

        bh_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.block_hierarchy")
        gph_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.gp_hierarchy")
        pub_b_cnt = await conn.fetchval("SELECT count(*) FROM public.tehsils_blocks WHERE entity_type LIKE '%Block%'")
        pub_gp_stats = dict(await conn.fetchrow("""
            SELECT count(*) as total, count(district_id) as has_dist, count(tehsil_block_id) as has_tb,
                   count(name_hi) as has_hi, count(lgd_code) as has_lgd, count(code) as has_code
            FROM public.gram_panchayats
        """))
        logger.info("=== BLOCK & GRAM PANCHAYAT SYNC COMPLETE ===")
        logger.info(f"raj_masters.block_hierarchy: {bh_cnt} | public.tehsils_blocks (Blocks): {pub_b_cnt}")
        logger.info(f"raj_masters.gp_hierarchy: {gph_cnt} | public.gram_panchayats: {pub_gp_stats}")
        logger.info(f"Completed in {duration}s")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    asyncio.run(sync_all(from_db="--from-db" in sys.argv))
