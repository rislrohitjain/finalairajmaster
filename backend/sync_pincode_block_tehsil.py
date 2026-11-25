"""
Dedicated Master Synchronization Script for:
1. TEHSIL RAJASTHAN -> raj_masters.tehsils & public.tehsils_blocks
2. BLOCK RAJASTHAN -> raj_masters.blocks & public.tehsils_blocks
3. PINCODE RAJASTHAN -> raj_masters.pincodes & public.pincodes
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
import httpx
import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_pipeline")

DB_DSN = "postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster"
PORTAL_URL = "https://rajmasters.rajasthan.gov.in"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
}

def parse_row(item: Any) -> Dict[str, Any]:
    if isinstance(item, list):
        return {kv["Key"]: kv.get("Value") for kv in item if isinstance(kv, dict) and "Key" in kv}
    elif isinstance(item, dict):
        return item
    return {}

async def fetch_all_master_rows(client: httpx.AsyncClient, master_name: str, page_size: int = 1000) -> List[Dict[str, Any]]:
    logger.info(f"Fetching master: '{master_name}'...")
    all_rows: List[Dict[str, Any]] = []
    page = 1
    total_count = None

    while True:
        payload = {
            "master": master_name,
            "Page": page,
            "Size": page_size,
            "DivisionId": "",
            "DistrictId": "0",
            "TehsilId": "0",
            "BlockId": "0",
        }
        resp = await client.post(f"{PORTAL_URL}/Home/ListData", json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        raw_rows = data.get("data", [])
        if total_count is None:
            total_count = int(data.get("TotalCount") or len(raw_rows))
            logger.info(f"'{master_name}' TotalCount declared by portal: {total_count}")

        if not raw_rows:
            break

        for r in raw_rows:
            parsed = parse_row(r)
            if parsed:
                all_rows.append(parsed)

        logger.info(f"'{master_name}' Page {page}: fetched {len(raw_rows)} rows (Cumulative: {len(all_rows)} / {total_count})")

        if len(all_rows) >= total_count or len(raw_rows) < page_size:
            break
        page += 1
        await asyncio.sleep(0.05)

    logger.info(f"Finished fetching '{master_name}': total {len(all_rows)} rows.")
    return all_rows

async def sync_all():
    logger.info("Connecting to PostgreSQL...")
    conn = await asyncpg.connect(DB_DSN)
    client = httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True)

    try:
        # =====================================================================
        # 1. SYNC TEHSIL RAJASTHAN
        # =====================================================================
        tehsil_rows = await fetch_all_master_rows(client, "TEHSIL RAJASTHAN", page_size=1000)
        logger.info(f"Processing {len(tehsil_rows)} Tehsils...")
        
        tehsil_batch = []
        for r in tehsil_rows:
            t_id = r.get("TEHSIL_ID")
            if not t_id:
                continue
            name_en = (r.get("TEHSIL_ENG") or "").strip()
            name_hi = (r.get("TEHSIL_MANGAL") or "").strip()
            code = str(r.get("TEHSIL_CODE") or "").strip()
            dist_id = r.get("DISTRICT_ID")
            tehsildar = f"Tehsildar Office, {name_en}"
            payload = json.dumps(r)

            tehsil_batch.append((
                int(t_id),
                int(dist_id) if dist_id else None,
                code or None,
                name_en,
                name_hi or None,
                tehsildar,
                payload
            ))

        await conn.executemany("""
            INSERT INTO raj_masters.tehsils
            (raj_master_id, district_id, code, name_en, name_hi, tehsildar_details, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                tehsildar_details = EXCLUDED.tehsildar_details,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """, tehsil_batch)
        logger.info(f"Upserted {len(tehsil_batch)} tehsils into raj_masters.tehsils.")

        # =====================================================================
        # 2. SYNC BLOCK RAJASTHAN
        # =====================================================================
        block_rows = await fetch_all_master_rows(client, "BLOCK RAJASTHAN", page_size=1000)
        logger.info(f"Processing {len(block_rows)} Blocks...")

        block_batch = []
        for r in block_rows:
            b_id = r.get("BLOCK_ID")
            if not b_id:
                continue
            name_en = (r.get("BLOCK_ENG") or "").strip()
            name_hi = (r.get("BLOCK_MANGAL") or "").strip()
            code = str(r.get("BLOCK_CODE") or "").strip()
            lgd_code = str(r.get("BLOCK_LGCODE") or "").strip()
            dist_id = r.get("DISTRICT_ID")
            bdo = f"Block Development Officer (BDO), {name_en}"
            payload = json.dumps(r)

            block_batch.append((
                int(b_id),
                int(dist_id) if dist_id else None,
                code or None,
                lgd_code or None,
                name_en,
                name_hi or None,
                bdo,
                payload
            ))

        await conn.executemany("""
            INSERT INTO raj_masters.blocks
            (raj_master_id, district_id, code, lgd_code, name_en, name_hi, bdo_details, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                bdo_details = EXCLUDED.bdo_details,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """, block_batch)
        logger.info(f"Upserted {len(block_batch)} blocks into raj_masters.blocks.")

        # =====================================================================
        # 3. SYNC PINCODE RAJASTHAN
        # =====================================================================
        pincode_rows = await fetch_all_master_rows(client, "PINCODE RAJASTHAN", page_size=1000)
        logger.info(f"Processing {len(pincode_rows)} Pincode records...")

        # Build district name -> raj_master_id map from raj_masters.districts
        dist_records = await conn.fetch("SELECT raj_master_id, name_en FROM raj_masters.districts")
        dist_map = {}
        for dr in dist_records:
            clean_name = dr["name_en"].upper().strip()
            dist_map[clean_name] = dr["raj_master_id"]

        pincode_batch = []
        for r in pincode_rows:
            raw_pin = str(r.get("PINCODE") or "").strip()
            if not raw_pin or len(raw_pin) < 6:
                continue
            pin = raw_pin[:6]
            if not pin.isdigit():
                continue

            office_name = str(r.get("OFFICE_NAME") or "General Post Office").strip()
            locality_name = str(r.get("LOCALITY_NAME") or office_name).strip()
            dist_name = str(r.get("DISTRICT_NAME") or "").strip()
            subdist_name = str(r.get("SUBDIST_NAME") or "").strip()
            state_name = str(r.get("STATE_NAME") or "RAJASTHAN").strip()
            r_id = r.get("PINCODE_ID")
            dist_id = dist_map.get(dist_name.upper())
            payload = json.dumps(r)

            pincode_batch.append((
                pin,
                office_name,
                locality_name,
                dist_id,
                subdist_name or None,
                dist_name or None,
                state_name or "RAJASTHAN",
                int(r_id) if r_id else None,
                payload
            ))

        chunk_size = 2000
        for i in range(0, len(pincode_batch), chunk_size):
            chunk = pincode_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO raj_masters.pincodes
                (pincode, office_name, locality_name, district_id, subdist_name, district_name, state_name, raj_master_id, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
                ON CONFLICT (pincode, office_name) DO UPDATE SET
                    locality_name = EXCLUDED.locality_name,
                    district_id = COALESCE(EXCLUDED.district_id, raj_masters.pincodes.district_id),
                    subdist_name = EXCLUDED.subdist_name,
                    district_name = EXCLUDED.district_name,
                    state_name = EXCLUDED.state_name,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, chunk)
        logger.info(f"Upserted {len(pincode_batch)} pincodes into raj_masters.pincodes.")

        # =====================================================================
        # 4. SYNC TO public.tehsils_blocks
        # =====================================================================
        logger.info("Synchronizing Tehsils & Blocks into public.tehsils_blocks...")
        
        # Load public districts for mapping
        pub_districts = await conn.fetch("SELECT id, name_en, rajmaster_id FROM public.districts")
        pub_dist_by_name = {d["name_en"].upper().strip(): d["id"] for d in pub_districts}
        pub_dist_by_rajid = {d["rajmaster_id"]: d["id"] for d in pub_districts if d["rajmaster_id"]}

        # Sync Tehsils into public.tehsils_blocks
        tehsils_in_rm = await conn.fetch("""
            SELECT t.raj_master_id, t.name_en, t.name_hi, t.code, t.district_id, t.tehsildar_details,
                   d.name_en as dist_name
            FROM raj_masters.tehsils t
            LEFT JOIN raj_masters.districts d ON t.district_id = d.raj_master_id
        """)

        pub_tehsil_batch = []
        for t in tehsils_in_rm:
            dist_id = pub_dist_by_rajid.get(t["district_id"]) or (pub_dist_by_name.get(t["dist_name"].upper()) if t["dist_name"] else None)
            pub_tehsil_batch.append((
                dist_id,
                int(t["raj_master_id"]),
                t["code"] or None,
                t["name_en"],
                t["name_hi"] or None,
                "Tehsil",
                t["tehsildar_details"] or f"Tehsildar Office, {t['name_en']}",
                json.dumps({"source": "raj_masters.tehsils", "raj_master_id": t["raj_master_id"]})
            ))

        # Check existing tehsils_blocks by rajmaster_id or (district_id AND name_en)
        for tb in pub_tehsil_batch:
            existing = await conn.fetchrow(
                "SELECT id FROM public.tehsils_blocks WHERE rajmaster_id = $1",
                tb[1]
            )
            if not existing and tb[0] is not None:
                existing = await conn.fetchrow(
                    "SELECT id FROM public.tehsils_blocks WHERE district_id = $1 AND LOWER(TRIM(name_en)) = LOWER(TRIM($2)) AND entity_type = 'Tehsil'",
                    tb[0], tb[3]
                )
            if existing:
                await conn.execute("""
                    UPDATE public.tehsils_blocks SET
                        district_id = COALESCE($1, district_id),
                        rajmaster_id = $2,
                        code = COALESCE($3, code),
                        name_hi = COALESCE($4, name_hi),
                        tehsildar_details = COALESCE($5, tehsildar_details),
                        updated_at = NOW()
                    WHERE id = $6
                """, tb[0], tb[1], tb[2], tb[4], tb[6], existing["id"])
            else:
                await conn.execute("""
                    INSERT INTO public.tehsils_blocks
                    (district_id, rajmaster_id, code, name_en, name_hi, entity_type, tehsildar_details, metadata_json, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW(), NOW())
                """, tb[0], tb[1], tb[2], tb[3], tb[4], tb[5], tb[6], tb[7])

        logger.info(f"Synchronized {len(pub_tehsil_batch)} tehsils into public.tehsils_blocks.")

        # Sync Blocks into public.tehsils_blocks
        blocks_in_rm = await conn.fetch("""
            SELECT b.raj_master_id, b.name_en, b.name_hi, b.code, b.lgd_code, b.district_id, b.bdo_details,
                   d.name_en as dist_name
            FROM raj_masters.blocks b
            LEFT JOIN raj_masters.districts d ON b.district_id = d.raj_master_id
        """)

        for b in blocks_in_rm:
            dist_id = pub_dist_by_rajid.get(b["district_id"]) or (pub_dist_by_name.get(b["dist_name"].upper()) if b["dist_name"] else None)
            b_name = b["name_en"]
            lgd_int = int(b["lgd_code"]) if b["lgd_code"] and b["lgd_code"].isdigit() else None
            existing = await conn.fetchrow(
                "SELECT id FROM public.tehsils_blocks WHERE rajmaster_id = $1",
                b["raj_master_id"]
            )
            if not existing and dist_id is not None:
                existing = await conn.fetchrow(
                    "SELECT id FROM public.tehsils_blocks WHERE district_id = $1 AND LOWER(TRIM(name_en)) = LOWER(TRIM($2)) AND entity_type LIKE '%Block%'",
                    dist_id, b_name
                )
            if existing:
                await conn.execute("""
                    UPDATE public.tehsils_blocks SET
                        district_id = COALESCE($1, district_id),
                        rajmaster_id = $2,
                        code = COALESCE($3, code),
                        name_hi = COALESCE($4, name_hi),
                        bdo_details = COALESCE($5, bdo_details),
                        lgd_code = COALESCE($6, lgd_code),
                        updated_at = NOW()
                    WHERE id = $7
                """, dist_id, b["raj_master_id"], b["code"], b["name_hi"], b["bdo_details"], lgd_int, existing["id"])
            else:
                await conn.execute("""
                    INSERT INTO public.tehsils_blocks
                    (district_id, rajmaster_id, code, name_en, name_hi, entity_type, bdo_details, lgd_code, metadata_json, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, 'Panchayat Samiti / Block', $6, $7, $8::jsonb, NOW(), NOW())
                """, dist_id, b["raj_master_id"], b["code"], b_name, b["name_hi"], b["bdo_details"], lgd_int,
                json.dumps({"source": "raj_masters.blocks", "raj_master_id": b["raj_master_id"]}))

        logger.info(f"Synchronized {len(blocks_in_rm)} blocks into public.tehsils_blocks.")

        # =====================================================================
        # 5. SYNC TO public.pincodes
        # =====================================================================
        logger.info("Aggregating unique pincodes from raj_masters.pincodes into public.pincodes...")
        
        # Aggregate unique 6-digit pincodes across Rajasthan
        unique_pins = await conn.fetch("""
            SELECT 
                pincode,
                MODE() WITHIN GROUP (ORDER BY district_name) as primary_district,
                MODE() WITHIN GROUP (ORDER BY subdist_name) as primary_subdist,
                string_agg(DISTINCT office_name, ', ' ORDER BY office_name) as all_offices,
                string_agg(DISTINCT locality_name, ', ' ORDER BY locality_name) as all_localities,
                COUNT(*) as total_offices
            FROM raj_masters.pincodes
            GROUP BY pincode
            ORDER BY pincode;
        """)

        logger.info(f"Found {len(unique_pins)} unique Rajasthan postal codes to sync into public.pincodes.")

        # Map public tehsils/blocks for fast resolution
        tb_records = await conn.fetch("SELECT id, name_en, district_id FROM public.tehsils_blocks")
        tb_by_name = {tb["name_en"].upper().strip(): tb["id"] for tb in tb_records}

        pub_pincode_upserts = []
        for up in unique_pins:
            pin = up["pincode"]
            dist_str = (up["primary_district"] or "").upper().strip()
            subdist_str = (up["primary_subdist"] or "").upper().strip()
            dist_id = pub_dist_by_name.get(dist_str)
            tb_id = tb_by_name.get(subdist_str)

            # Division mapping from district
            div_id = None
            if dist_id:
                div_id = await conn.fetchval("SELECT division_id FROM public.districts WHERE id = $1", dist_id)

            offices_summary = up["all_offices"] or f"Post Office, Pincode {pin}"
            city_or_village = subdist_str or dist_str or f"Pincode {pin} Area"
            meta = json.dumps({
                "district": up["primary_district"],
                "subdistrict": up["primary_subdist"],
                "offices": up["all_offices"][:500] if up["all_offices"] else "",
                "total_offices": up["total_offices"]
            })

            pub_pincode_upserts.append((
                pin,
                city_or_village[:150],
                tb_id,
                dist_id,
                div_id,
                meta
            ))

        chunk_size = 2000
        for i in range(0, len(pub_pincode_upserts), chunk_size):
            chunk = pub_pincode_upserts[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO public.pincodes
                (pincode, city_or_village, tehsil_block_id, district_id, division_id, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW(), NOW())
                ON CONFLICT (pincode) DO UPDATE SET
                    city_or_village = EXCLUDED.city_or_village,
                    tehsil_block_id = COALESCE(EXCLUDED.tehsil_block_id, public.pincodes.tehsil_block_id),
                    district_id = COALESCE(EXCLUDED.district_id, public.pincodes.district_id),
                    division_id = COALESCE(EXCLUDED.division_id, public.pincodes.division_id),
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW();
            """, chunk)

        logger.info(f"Upserted {len(pub_pincode_upserts)} unique pincodes into public.pincodes.")

        # Final Counts Verification
        logger.info("=== FINAL VERIFICATION ===")
        rm_tehsils = await conn.fetchval("SELECT count(*) FROM raj_masters.tehsils")
        rm_blocks = await conn.fetchval("SELECT count(*) FROM raj_masters.blocks")
        rm_pins = await conn.fetchval("SELECT count(*) FROM raj_masters.pincodes")
        pub_tb = await conn.fetchval("SELECT count(*) FROM public.tehsils_blocks")
        pub_pins = await conn.fetchval("SELECT count(*) FROM public.pincodes")

        logger.info(f"raj_masters.tehsils: {rm_tehsils}")
        logger.info(f"raj_masters.blocks: {rm_blocks}")
        logger.info(f"raj_masters.pincodes: {rm_pins}")
        logger.info(f"public.tehsils_blocks: {pub_tb}")
        logger.info(f"public.pincodes: {pub_pins}")

    finally:
        await client.aclose()
        await conn.close()
        logger.info("Sync pipeline completed successfully.")

if __name__ == "__main__":
    asyncio.run(sync_all())
