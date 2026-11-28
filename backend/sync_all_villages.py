"""
Complete Rajasthan Village Synchronization Pipeline (Local PostgreSQL)
Fetches all 51,892+ records from RajMasters (VILLAGE RAJASTHAN), stores all 20
portal columns in raj_masters.village_hierarchy, and normalizes & upserts all
Gram Panchayats and Villages into public.gram_panchayats and public.villages
with trigram indexes for instant Chat, Voice, and Admin Dashboard lookups.
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
logger = logging.getLogger("sync_all_villages")

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


async def fetch_all_villages(page_size: int = 1000, concurrency: int = 3) -> List[Dict[str, Any]]:
    headers_get = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    headers_post = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": f"{PORTAL_URL}/Home/List?master=VILLAGE RAJASTHAN",
    }

    async with httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True) as client:
        r0 = await client.get(f"{PORTAL_URL}/Home/List?master=VILLAGE RAJASTHAN", headers=headers_get)
        logger.info(f"Session init GET status: {r0.status_code}")

        async def fetch_page(page: int) -> Tuple[List[Dict[str, Any]], int]:
            payload = {
                "master": "VILLAGE RAJASTHAN",
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
                    logger.warning(f"Page {page} attempt {attempt+1} failed ({exc}), retrying in {wait_s}s...")
                    await asyncio.sleep(wait_s)
            return [], 0

        # Fetch page 1 first to discover TotalCount
        page1_rows, total_count = await fetch_page(1)
        logger.info(f"Portal declared TotalCount={total_count}; Page 1 fetched {len(page1_rows)} rows.")

        total_pages = (total_count + page_size - 1) // page_size if total_count else 1
        all_by_page: Dict[int, List[Dict[str, Any]]] = {1: page1_rows}

        sem = asyncio.Semaphore(concurrency)

        async def fetch_worker(p: int):
            async with sem:
                rows, _ = await fetch_page(p)
                all_by_page[p] = rows
                if p % 5 == 0 or p == total_pages:
                    cum = sum(len(v) for v in all_by_page.values())
                    logger.info(f"Fetched page {p}/{total_pages} (cumulative ~{cum}/{total_count})")

        await asyncio.gather(*(fetch_worker(p) for p in range(2, total_pages + 1)))

        all_rows: List[Dict[str, Any]] = []
        for p in range(1, total_pages + 1):
            all_rows.extend(all_by_page.get(p, []))
        return all_rows


async def sync_villages_to_local_db(from_db: bool = False):
    t_start = time.time()
    conn = await asyncpg.connect(DB_DSN)

    try:
        # 1. Ensure raj_masters.village_hierarchy and GIN trigram indexes exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS raj_masters.village_hierarchy (
                id BIGSERIAL PRIMARY KEY,
                village_id BIGINT UNIQUE NOT NULL,
                village_code VARCHAR(50),
                village_lgdcode BIGINT,
                village_eng TEXT NOT NULL,
                village_mangal TEXT,
                division_id BIGINT,
                division_eng TEXT,
                district_id BIGINT,
                district_eng TEXT,
                tehsil_id BIGINT,
                tehsil_eng TEXT,
                ilr_id BIGINT,
                ilr_eng TEXT,
                patwar_id BIGINT,
                patwar_eng TEXT,
                block_id BIGINT,
                block_eng TEXT,
                block_mangal TEXT,
                gp_id BIGINT,
                gp_eng TEXT,
                raw_payload JSONB DEFAULT '{}'::jsonb,
                synced_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_rm_vh_village_eng_trgm ON raj_masters.village_hierarchy USING gin (village_eng gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_vh_village_mangal_trgm ON raj_masters.village_hierarchy USING gin (village_mangal gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_vh_gp_eng_trgm ON raj_masters.village_hierarchy USING gin (gp_eng gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_vh_patwar_eng_trgm ON raj_masters.village_hierarchy USING gin (patwar_eng gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_vh_district_id ON raj_masters.village_hierarchy(district_id);
            CREATE INDEX IF NOT EXISTS idx_rm_vh_tehsil_id ON raj_masters.village_hierarchy(tehsil_id);
            CREATE INDEX IF NOT EXISTS idx_rm_vh_gp_id ON raj_masters.village_hierarchy(gp_id);

            CREATE INDEX IF NOT EXISTS idx_pub_villages_name_en_trgm ON public.villages USING gin (name_en gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_pub_villages_name_hi_trgm ON public.villages USING gin (name_hi gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_pub_villages_patwar_trgm ON public.villages USING gin (patwar_circle gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_pub_gp_name_en_trgm ON public.gram_panchayats USING gin (name_en gin_trgm_ops);
        """)

        if from_db:
            logger.info("Step 1/4: Loading VILLAGE RAJASTHAN rows from local raj_masters.village_hierarchy...")
            db_rows = await conn.fetch("""
                SELECT division_id AS "DIVISION_ID", division_eng AS "DIVISION_ENG",
                       district_id AS "DISTRICT_ID", district_eng AS "DISTRICT_ENG",
                       tehsil_id AS "TEHSIL_ID", tehsil_eng AS "TEHSIL_ENG",
                       ilr_id AS "ILR_ID", ilr_eng AS "ILR_ENG",
                       patwar_id AS "PATWAR_ID", patwar_eng AS "PATWAR_ENG",
                       block_id AS "BLOCK_ID", block_eng AS "BLOCK_ENG", block_mangal AS "BLOCK_MANGAL",
                       gp_id AS "GP_ID", gp_eng AS "GP_ENG",
                       village_id AS "VILLAGE_ID", village_code AS "VILLAGE_CODE",
                       village_lgdcode AS "VILLAGE_LGCODE", village_eng AS "VILLAGE_ENG",
                       village_mangal AS "VILLAGE_MANGAL"
                FROM raj_masters.village_hierarchy
            """)
            raw_rows = [dict(r) for r in db_rows]
            logger.info(f"Loaded {len(raw_rows)} rows from local DB.")
        else:
            logger.info("Step 1/4: Fetching all VILLAGE RAJASTHAN rows from RajMasters portal...")
            raw_rows = await fetch_all_villages(page_size=1000, concurrency=3)
            logger.info(f"Fetched {len(raw_rows)} total village rows from portal.")

        # Deduplicate by VILLAGE_ID in case portal pagination shifted slightly
        by_vid: Dict[int, Dict[str, Any]] = {}
        for r in raw_rows:
            vid = safe_int(r.get("VILLAGE_ID"))
            if vid is not None:
                by_vid[vid] = r
        unique_rows = list(by_vid.values())
        logger.info(f"Unique VILLAGE_ID records: {len(unique_rows)}")

        # 2. Upsert into raj_masters.village_hierarchy
        logger.info("Step 2/4: Upserting into raj_masters.village_hierarchy...")
        vh_batch = []
        for r in unique_rows:
            vid = safe_int(r.get("VILLAGE_ID"))
            v_eng = clean_str(r.get("VILLAGE_ENG")) or f"Village {vid}"
            vh_batch.append((
                vid,
                clean_str(r.get("VILLAGE_CODE")),
                safe_int(r.get("VILLAGE_LGCODE")),
                v_eng,
                clean_str(r.get("VILLAGE_MANGAL")),
                safe_int(r.get("DIVISION_ID")),
                clean_str(r.get("DIVISION_ENG")),
                safe_int(r.get("DISTRICT_ID")),
                clean_str(r.get("DISTRICT_ENG")),
                safe_int(r.get("TEHSIL_ID")),
                clean_str(r.get("TEHSIL_ENG")),
                safe_int(r.get("ILR_ID")),
                clean_str(r.get("ILR_ENG")),
                safe_int(r.get("PATWAR_ID")),
                clean_str(r.get("PATWAR_ENG")),
                safe_int(r.get("BLOCK_ID")),
                clean_str(r.get("BLOCK_ENG")),
                clean_str(r.get("BLOCK_MANGAL")),
                safe_int(r.get("GP_ID")),
                clean_str(r.get("GP_ENG")),
                json.dumps(r),
            ))

        chunk_size = 5000
        for i in range(0, len(vh_batch), chunk_size):
            chunk = vh_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO raj_masters.village_hierarchy
                (village_id, village_code, village_lgdcode, village_eng, village_mangal,
                 division_id, division_eng, district_id, district_eng,
                 tehsil_id, tehsil_eng, ilr_id, ilr_eng, patwar_id, patwar_eng,
                 block_id, block_eng, block_mangal, gp_id, gp_eng, raw_payload, synced_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21::jsonb,NOW())
                ON CONFLICT (village_id) DO UPDATE SET
                    village_code = EXCLUDED.village_code,
                    village_lgdcode = EXCLUDED.village_lgdcode,
                    village_eng = EXCLUDED.village_eng,
                    village_mangal = EXCLUDED.village_mangal,
                    division_id = EXCLUDED.division_id,
                    division_eng = EXCLUDED.division_eng,
                    district_id = EXCLUDED.district_id,
                    district_eng = EXCLUDED.district_eng,
                    tehsil_id = EXCLUDED.tehsil_id,
                    tehsil_eng = EXCLUDED.tehsil_eng,
                    ilr_id = EXCLUDED.ilr_id,
                    ilr_eng = EXCLUDED.ilr_eng,
                    patwar_id = EXCLUDED.patwar_id,
                    patwar_eng = EXCLUDED.patwar_eng,
                    block_id = EXCLUDED.block_id,
                    block_eng = EXCLUDED.block_eng,
                    block_mangal = EXCLUDED.block_mangal,
                    gp_id = EXCLUDED.gp_id,
                    gp_eng = EXCLUDED.gp_eng,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, chunk)

        # 3. Detach fake rajmaster_id (1..8) on fallback seed rows if they collide, and fix Jaipur district/tehsil on id 1..5
        jaipur_id = await conn.fetchval("SELECT id FROM public.districts WHERE name_en = 'Jaipur' LIMIT 1")
        sanganer_tb_id = await conn.fetchval("SELECT id FROM public.tehsils_blocks WHERE district_id = $1 AND LOWER(name_en) = 'sanganer' AND entity_type='Tehsil' LIMIT 1", jaipur_id)
        amer_tb_id = await conn.fetchval("SELECT id FROM public.tehsils_blocks WHERE district_id = $1 AND LOWER(name_en) = 'amer' AND entity_type='Tehsil' LIMIT 1", jaipur_id)

        # Clear fake rajmaster_id 1..8 from seed rows so real RajMasters IDs 1..8 never overwrite Muhana..Badi
        await conn.execute("""
            UPDATE public.gram_panchayats
            SET rajmaster_id = NULL
            WHERE id <= 8 AND rajmaster_id = id AND metadata_json->>'source' = 'seed'
        """)
        await conn.execute("""
            UPDATE public.villages
            SET rajmaster_id = NULL
            WHERE id <= 8 AND rajmaster_id = id AND metadata_json->>'source' = 'seed'
        """)
        if jaipur_id and sanganer_tb_id and amer_tb_id:
            await conn.execute("UPDATE public.gram_panchayats SET district_id=$1, tehsil_block_id=$2 WHERE id IN (1,2,3) AND metadata_json->>'source'='seed'", jaipur_id, sanganer_tb_id)
            await conn.execute("UPDATE public.gram_panchayats SET district_id=$1, tehsil_block_id=$2 WHERE id IN (4,5) AND metadata_json->>'source'='seed'", jaipur_id, amer_tb_id)
            await conn.execute("UPDATE public.villages SET district_id=$1, tehsil_block_id=$2 WHERE id IN (1,2,3) AND metadata_json->>'source'='seed'", jaipur_id, sanganer_tb_id)
            await conn.execute("UPDATE public.villages SET district_id=$1, tehsil_block_id=$2 WHERE id IN (4,5) AND metadata_json->>'source'='seed'", jaipur_id, amer_tb_id)

        # Build lookups for public.districts, public.tehsils_blocks, and pincode matching
        pub_dists = await conn.fetch("SELECT id, rajmaster_id, name_en FROM public.districts ORDER BY id ASC")
        dist_by_rm_id = {d["rajmaster_id"]: d["id"] for d in pub_dists if d["rajmaster_id"]}
        dist_by_name = {d["name_en"].upper().strip(): d["id"] for d in pub_dists}

        pub_tbs = await conn.fetch("SELECT id, district_id, rajmaster_id, name_en, entity_type FROM public.tehsils_blocks ORDER BY CASE WHEN entity_type='Tehsil' THEN 0 ELSE 1 END, id ASC")
        tb_by_rm_and_type: Dict[Tuple[int, str], int] = {}
        tb_by_rm: Dict[int, int] = {}
        tb_by_dist_name: Dict[Tuple[int, str], int] = {}
        for tb in pub_tbs:
            if tb["rajmaster_id"]:
                etype = "block" if "block" in (tb["entity_type"] or "").lower() else "tehsil"
                tb_by_rm_and_type[(tb["rajmaster_id"], etype)] = tb["id"]
                if tb["rajmaster_id"] not in tb_by_rm:
                    tb_by_rm[tb["rajmaster_id"]] = tb["id"]
            if tb["district_id"] and tb["name_en"]:
                tb_by_dist_name.setdefault((tb["district_id"], tb["name_en"].upper().strip()), tb["id"])

        # Build fast (district_name, locality_name) -> pincode lookup from raj_masters.pincode_localities
        pin_loc_rows = await conn.fetch("""
            SELECT DISTINCT ON (LOWER(TRIM(locality_name)), LOWER(TRIM(COALESCE(district_name, ''))))
                LOWER(TRIM(locality_name)) as loc,
                LOWER(TRIM(COALESCE(district_name, ''))) as dist,
                pincode
            FROM raj_masters.pincode_localities
            WHERE locality_name IS NOT NULL AND TRIM(locality_name) <> ''
            ORDER BY LOWER(TRIM(locality_name)), LOWER(TRIM(COALESCE(district_name, ''))), pincode
        """)
        pin_by_dist_loc: Dict[Tuple[str, str], str] = {}
        pin_by_loc: Dict[str, str] = {}
        for pr in pin_loc_rows:
            pin_by_dist_loc[(pr["dist"], pr["loc"])] = pr["pincode"]
            pin_by_loc.setdefault(pr["loc"], pr["pincode"])

        # 4. Upsert Gram Panchayats into public.gram_panchayats
        logger.info("Step 3/4: Upserting Gram Panchayats into public.gram_panchayats...")
        gp_map: Dict[int, Tuple[int, Optional[int], Optional[int], str, Optional[str], str]] = {}
        for r in unique_rows:
            gp_id = safe_int(r.get("GP_ID"))
            gp_eng = clean_str(r.get("GP_ENG"))
            if not gp_id or not gp_eng:
                continue
            if gp_id in gp_map:
                continue
            rm_dist_id = safe_int(r.get("DISTRICT_ID"))
            dist_eng = clean_str(r.get("DISTRICT_ENG")) or ""
            pub_dist_id = dist_by_rm_id.get(rm_dist_id) or dist_by_name.get(dist_eng.upper())

            rm_block_id = safe_int(r.get("BLOCK_ID"))
            rm_tehsil_id = safe_int(r.get("TEHSIL_ID"))
            block_eng = clean_str(r.get("BLOCK_ENG")) or ""
            tehsil_eng = clean_str(r.get("TEHSIL_ENG")) or ""
            pub_tb_id = (
                (tb_by_rm_and_type.get((rm_block_id, "block")) if rm_block_id else None)
                or (tb_by_rm_and_type.get((rm_tehsil_id, "tehsil")) if rm_tehsil_id else None)
                or (tb_by_dist_name.get((pub_dist_id, block_eng.upper())) if pub_dist_id and block_eng else None)
                or (tb_by_dist_name.get((pub_dist_id, tehsil_eng.upper())) if pub_dist_id and tehsil_eng else None)
            )
            gp_meta = json.dumps({
                "source": "rajmasters_village_sync",
                "division": clean_str(r.get("DIVISION_ENG")),
                "block_id": rm_block_id,
                "block_eng": block_eng,
                "block_mangal": clean_str(r.get("BLOCK_MANGAL")),
            })
            gp_map[gp_id] = (gp_id, pub_dist_id, pub_tb_id, gp_eng[:150], f"Sarpanch, GP {gp_eng}"[:150], gp_meta)

        gp_batch = list(gp_map.values())
        for i in range(0, len(gp_batch), chunk_size):
            chunk = gp_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO public.gram_panchayats
                (rajmaster_id, district_id, tehsil_block_id, name_en, sarpanch, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW(), NOW())
                ON CONFLICT (rajmaster_id) DO UPDATE SET
                    district_id = COALESCE(EXCLUDED.district_id, public.gram_panchayats.district_id),
                    tehsil_block_id = COALESCE(EXCLUDED.tehsil_block_id, public.gram_panchayats.tehsil_block_id),
                    name_en = EXCLUDED.name_en,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW();
            """, chunk)

        # Fetch public.gram_panchayats id map by rajmaster_id
        pub_gps = await conn.fetch("SELECT id, rajmaster_id FROM public.gram_panchayats WHERE rajmaster_id IS NOT NULL")
        gp_id_by_rm = {g["rajmaster_id"]: g["id"] for g in pub_gps}

        # 5. Upsert all 51,892 Villages into public.villages
        logger.info(f"Step 4/4: Upserting {len(unique_rows)} villages into public.villages...")
        v_batch = []
        for r in unique_rows:
            vid = safe_int(r.get("VILLAGE_ID"))
            v_eng = clean_str(r.get("VILLAGE_ENG")) or f"Village {vid}"
            v_hi = clean_str(r.get("VILLAGE_MANGAL"))
            v_code = clean_str(r.get("VILLAGE_CODE"))
            v_lgd = safe_int(r.get("VILLAGE_LGCODE"))

            rm_dist_id = safe_int(r.get("DISTRICT_ID"))
            dist_eng = clean_str(r.get("DISTRICT_ENG")) or ""
            pub_dist_id = dist_by_rm_id.get(rm_dist_id) or dist_by_name.get(dist_eng.upper())

            rm_tehsil_id = safe_int(r.get("TEHSIL_ID"))
            rm_block_id = safe_int(r.get("BLOCK_ID"))
            tehsil_eng = clean_str(r.get("TEHSIL_ENG")) or ""
            block_eng = clean_str(r.get("BLOCK_ENG")) or ""
            pub_tb_id = (
                (tb_by_rm_and_type.get((rm_tehsil_id, "tehsil")) if rm_tehsil_id else None)
                or (tb_by_dist_name.get((pub_dist_id, tehsil_eng.upper())) if pub_dist_id and tehsil_eng else None)
                or (tb_by_rm_and_type.get((rm_block_id, "block")) if rm_block_id else None)
            )

            rm_gp_id = safe_int(r.get("GP_ID"))
            pub_gp_id = gp_id_by_rm.get(rm_gp_id) if rm_gp_id else None

            patwar_eng = clean_str(r.get("PATWAR_ENG"))
            patwari = f"Patwari, {patwar_eng}" if patwar_eng else None

            v_low = v_eng.lower()
            d_low = dist_eng.lower()
            matched_pin = pin_by_dist_loc.get((d_low, v_low)) or pin_by_loc.get(v_low)

            v_meta = json.dumps({
                "source": "rajmasters_village_sync",
                "division_id": safe_int(r.get("DIVISION_ID")),
                "division": clean_str(r.get("DIVISION_ENG")),
                "district": dist_eng,
                "tehsil_id": rm_tehsil_id,
                "tehsil": tehsil_eng,
                "ilr_id": safe_int(r.get("ILR_ID")),
                "ilr_circle": clean_str(r.get("ILR_ENG")),
                "patwar_id": safe_int(r.get("PATWAR_ID")),
                "patwar_circle": patwar_eng,
                "block_id": rm_block_id,
                "block": block_eng,
                "block_hi": clean_str(r.get("BLOCK_MANGAL")),
                "gp_id": rm_gp_id,
                "gram_panchayat": clean_str(r.get("GP_ENG")),
            })

            v_batch.append((
                vid,
                pub_gp_id,
                pub_tb_id,
                pub_dist_id,
                v_code[:50] if v_code else None,
                v_eng[:150],
                v_hi[:150] if v_hi else None,
                patwar_eng[:150] if patwar_eng else None,
                patwari[:150] if patwari else None,
                matched_pin,
                v_lgd,
                v_meta,
            ))

        for i in range(0, len(v_batch), chunk_size):
            chunk = v_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO public.villages
                (rajmaster_id, gram_panchayat_id, tehsil_block_id, district_id, code,
                 name_en, name_hi, patwar_circle, patwari, pincode, lgd_code, metadata_json,
                 created_at, updated_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,NOW(),NOW())
                ON CONFLICT (rajmaster_id) DO UPDATE SET
                    gram_panchayat_id = COALESCE(EXCLUDED.gram_panchayat_id, public.villages.gram_panchayat_id),
                    tehsil_block_id = COALESCE(EXCLUDED.tehsil_block_id, public.villages.tehsil_block_id),
                    district_id = COALESCE(EXCLUDED.district_id, public.villages.district_id),
                    code = EXCLUDED.code,
                    name_en = EXCLUDED.name_en,
                    name_hi = COALESCE(EXCLUDED.name_hi, public.villages.name_hi),
                    patwar_circle = COALESCE(EXCLUDED.patwar_circle, public.villages.patwar_circle),
                    patwari = COALESCE(EXCLUDED.patwari, public.villages.patwari),
                    pincode = COALESCE(EXCLUDED.pincode, public.villages.pincode),
                    lgd_code = COALESCE(EXCLUDED.lgd_code, public.villages.lgd_code),
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW();
            """, chunk)

        # Log audit records
        duration = round(time.time() - t_start, 2)
        await conn.execute("""
            INSERT INTO public.scraper_runs (master_name, status, rows_fetched, rows_upserted, error_logs, started_at, completed_at)
            VALUES ('VILLAGE RAJASTHAN', 'completed', $1, $2, NULL, NOW() - ($3::double precision * interval '1 second'), NOW())
        """, len(raw_rows), len(v_batch), duration)

        await conn.execute("""
            INSERT INTO raj_masters.sync_audit_log (master_name, tier_level, expected_count, fetched_count, upserted_count, status, duration_seconds, mode, created_at, completed_at)
            VALUES ('VILLAGE RAJASTHAN', 6, $1, $1, $2, 'COMPLETED', $3::numeric, 'full', NOW() - ($4::double precision * interval '1 second'), NOW())
        """, len(raw_rows), len(v_batch), duration, duration)

        vh_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.village_hierarchy")
        gp_cnt = await conn.fetchval("SELECT count(*) FROM public.gram_panchayats")
        v_stats = dict(await conn.fetchrow("""
            SELECT count(*) as total,
                   count(district_id) as has_dist,
                   count(tehsil_block_id) as has_tb,
                   count(gram_panchayat_id) as has_gp,
                   count(pincode) as has_pin
            FROM public.villages
        """))
        logger.info("=== COMPLETE VILLAGE SYNC VERIFICATION ===")
        logger.info(f"raj_masters.village_hierarchy: {vh_cnt}")
        logger.info(f"public.gram_panchayats: {gp_cnt}")
        logger.info(f"public.villages stats: {v_stats}")
        logger.info(f"Completed in {duration}s")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    asyncio.run(sync_villages_to_local_db(from_db="--from-db" in sys.argv))
