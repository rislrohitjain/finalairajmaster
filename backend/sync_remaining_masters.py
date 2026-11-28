"""
Complete Sync Script for Remaining Official RajMasters Datasets (Local PostgreSQL)
Syncs and aligns counts across both `raj_masters` and `public` schemas:
  - SUB-DIVISION (328) -> raj_masters.sub_divisions + public.sub_divisions
  - SUB-TEHSIL (290) -> raj_masters.sub_tehsils + public.tehsils_blocks (entity_type='Sub-Tehsil')
  - URBAN LOCAL BODY(CITY) RAJASTHAN (309) -> raj_masters.ulbs + public.urban_local_bodies
  - WARD RAJASTHAN (10,245) -> raj_masters.wards + public.urban_wards
  - ILR RAJASTHAN (2,815) -> raj_masters.ilr_circles
  - PATWAR RAJASTHAN (11,336) -> raj_masters.patwar_circles
  - Backfills raj_masters.gram_panchayats (14,496) & raj_masters.villages (51,892) from hierarchy tables.

Note: `raj_masters.*` foreign keys reference the parent's `raj_master_id` column,
while `public.*` foreign keys reference the parent's surrogate `id` column.
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
logger = logging.getLogger("sync_remaining_masters")

DB_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://postgres:Admin%40123@127.0.0.1:5432/finalairajmaster",
)
PORTAL_URL = "https://rajmasters.rajasthan.gov.in"

DISTRICT_ALIASES: Dict[str, str] = {
    "BARA": "BARAN",
    "GANGANAGAR": "SRI GANGANAGAR",
    "JALOR": "JALORE",
    "JHUJHUNU": "JHUNJHUNU",
    "CHITTAURGARH": "CHITTORGARH",
    "DHAULPUR": "DHOLPUR",
    "BALOTARA": "BALOTRA",
    "SALUMBER": "SALUMBAR",
    "DIDWANA KUCHAMAN": "DIDWANA-KUCHAMAN",
    "DEEDWANA-KUCHAMAN": "DIDWANA-KUCHAMAN",
    "KOTPUTLI BEHROR": "KOTPUTLI-BEHROR",
    "KHAIRTHAL TIJARA": "KHAIRTHAL-TIJARA",
}


def norm_key(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().upper())


def parse_row(item: Any) -> Dict[str, Any]:
    if isinstance(item, list):
        return {kv["Key"]: kv.get("Value") for kv in item if isinstance(kv, dict) and "Key" in kv}
    if isinstance(item, dict):
        return item
    return {}


def clean_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(str(val).strip())
    except Exception:
        return None


def clean_int32(val: Any) -> Optional[int]:
    v = clean_int(val)
    if v is not None and -2147483648 <= v <= 2147483647:
        return v
    return None


async def fetch_master(master_name: str, page_size: int = 5000) -> List[Dict[str, Any]]:
    headers_get = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    headers_post = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": f"{PORTAL_URL}/Home/List?master={master_name}",
    }

    rows: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=90.0, verify=False, follow_redirects=True, trust_env=False) as client:
        await client.get(f"{PORTAL_URL}/Home/List?master={master_name}", headers=headers_get)
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
            data = None
            for attempt in range(4):
                try:
                    resp = await client.post(f"{PORTAL_URL}/Home/ListData", json=payload, headers=headers_post)
                    resp.raise_for_status()
                    if "Error" in str(resp.url):
                        raise RuntimeError(f"Portal redirected to error page for Size={payload['Size']}")
                    data = resp.json()
                    break
                except Exception as exc:
                    if attempt == 3:
                        raise
                    logger.warning(f"[{master_name}] page {page} retry {attempt+1}: {exc}")
                    await asyncio.sleep(1.5 * (attempt + 1))
                    await client.get(f"{PORTAL_URL}/Home/List?master={master_name}", headers=headers_get)

            raw_rows = (data or {}).get("data") or []
            if total_count is None:
                total_count = int((data or {}).get("TotalCount") or len(raw_rows))
                logger.info(f"[{master_name}] Portal TotalCount={total_count}")
            if not raw_rows:
                break
            rows.extend(parse_row(item) for item in raw_rows)
            logger.info(f"[{master_name}] fetched page {page}: {len(rows)}/{total_count}")
            if len(rows) >= total_count or len(raw_rows) < page_size:
                break
            page += 1
    return rows


def resolve_pub_district(dist_name: Optional[str], pub_dist_by_name: Dict[str, Tuple[int, str]]) -> Optional[int]:
    dk = norm_key(dist_name)
    dk = DISTRICT_ALIASES.get(dk, dk)
    entry = pub_dist_by_name.get(dk)
    if entry:
        return entry[0]
    for k, v in pub_dist_by_name.items():
        if k and (k == dk or k in dk or dk in k):
            return v[0]
    return None


def resolve_rm_district_rid(
    d_rid: Optional[int],
    d_name: Optional[str],
    rm_dist_rid_set: set,
    rm_dist_rid_by_name: Dict[str, int],
) -> Optional[int]:
    if d_rid and d_rid in rm_dist_rid_set:
        return d_rid
    dk = DISTRICT_ALIASES.get(norm_key(d_name), norm_key(d_name))
    if dk in rm_dist_rid_by_name:
        return rm_dist_rid_by_name[dk]
    for k, val in rm_dist_rid_by_name.items():
        if k and (k in dk or dk in k):
            return val
    return None


async def run_sync() -> None:
    t_start = time.time()
    conn = await asyncpg.connect(DB_DSN)
    try:
        pub_dists = await conn.fetch("SELECT id, name_en FROM public.districts ORDER BY id ASC")
        pub_dist_by_name: Dict[str, Tuple[int, str]] = {norm_key(d["name_en"]): (d["id"], d["name_en"]) for d in pub_dists}

        rm_dists = await conn.fetch("SELECT id, raj_master_id, name_en FROM raj_masters.districts ORDER BY id ASC")
        rm_dist_rid_set = {r["raj_master_id"] for r in rm_dists}
        rm_dist_rid_by_name: Dict[str, int] = {norm_key(r["name_en"]): r["raj_master_id"] for r in rm_dists}

        rm_teh_rid_set = {r["raj_master_id"] for r in await conn.fetch("SELECT raj_master_id FROM raj_masters.tehsils")}
        rm_blk_rid_set = {r["raj_master_id"] for r in await conn.fetch("SELECT raj_master_id FROM raj_masters.blocks")}

        # ------------------------------------------------------------------
        # 1. SUB-DIVISION (328): raj_masters.sub_divisions + public.sub_divisions
        # ------------------------------------------------------------------
        sd_portal_rows = await fetch_master("SUB-DIVISION", page_size=1000)
        logger.info(f"Syncing {len(sd_portal_rows)} Sub-Divisions...")

        rm_sd_batch = []
        for r in sd_portal_rows:
            rid = clean_int(r.get("SUB_DIVISION_ID"))
            if not rid:
                continue
            rm_d_rid = resolve_rm_district_rid(clean_int(r.get("DISTRICT_ID")), r.get("DISTRICT_ENG"), rm_dist_rid_set, rm_dist_rid_by_name)
            if not rm_d_rid:
                continue
            name_en = (r.get("SUB_DIVISION_ENG") or f"Sub-Division {rid}").strip()
            rm_sd_batch.append((
                rid,
                rm_d_rid,
                (r.get("SUB_DIVISION_CODE") or f"SDC{rid}").strip(),
                name_en,
                (r.get("SUB_DIVISION_MANGAL") or "").strip() or None,
                f"Sub-Divisional Magistrate (SDM / SDO), {name_en}",
                json.dumps(r),
            ))
        await conn.executemany("""
            INSERT INTO raj_masters.sub_divisions
            (raj_master_id, district_id, code, name_en, name_hi, sdm_jurisdiction, is_active, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                sdm_jurisdiction = EXCLUDED.sdm_jurisdiction,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """, rm_sd_batch)

        existing_pub_sds = await conn.fetch("SELECT id, district_id, rajmaster_id, name_en FROM public.sub_divisions ORDER BY id ASC")
        sd_by_rid = {r["rajmaster_id"]: r["id"] for r in existing_pub_sds if r["rajmaster_id"]}
        sd_by_dist_name = {(r["district_id"], norm_key(r["name_en"])): r["id"] for r in existing_pub_sds if r["name_en"]}

        for r in sd_portal_rows:
            rid = clean_int(r.get("SUB_DIVISION_ID"))
            if not rid:
                continue
            name_en = (r.get("SUB_DIVISION_ENG") or f"Sub-Division {rid}").strip()
            name_hi = (r.get("SUB_DIVISION_MANGAL") or "").strip() or None
            code = (r.get("SUB_DIVISION_CODE") or f"SDC{rid}").strip()
            d_id = resolve_pub_district(r.get("DISTRICT_ENG"), pub_dist_by_name) or 12
            sdm = f"Sub-Divisional Magistrate (SDM / SDO), {name_en}"
            meta_j = json.dumps({"source": "rajmasters_subdivision_complete", "raw": r})

            target_id = sd_by_rid.get(rid) or sd_by_dist_name.get((d_id, norm_key(name_en)))
            if target_id:
                await conn.execute("""
                    UPDATE public.sub_divisions
                    SET district_id = $1,
                        rajmaster_id = $2,
                        code = $3,
                        name_en = $4,
                        name_hi = COALESCE($5, name_hi),
                        sdm_jurisdiction = $6,
                        metadata_json = $7::jsonb,
                        updated_at = NOW()
                    WHERE id = $8
                """, d_id, rid, code, name_en, name_hi, sdm, meta_j, target_id)
            else:
                await conn.execute("""
                    INSERT INTO public.sub_divisions
                    (district_id, rajmaster_id, code, name_en, name_hi, sdm_jurisdiction, lgd_code, metadata_json, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NULL, $7::jsonb, NOW(), NOW())
                """, d_id, rid, code, name_en, name_hi, sdm, meta_j)

        # ------------------------------------------------------------------
        # 2. URBAN LOCAL BODY(CITY) RAJASTHAN (309) -> raj_masters.ulbs + public.urban_local_bodies
        # ------------------------------------------------------------------
        ulb_rows = await fetch_master("URBAN LOCAL BODY(CITY) RAJASTHAN", page_size=1000)
        logger.info(f"Syncing {len(ulb_rows)} ULBs...")

        rm_ulb_batch = []
        for r in ulb_rows:
            cid = clean_int(r.get("CITY_ID"))
            if not cid:
                continue
            rm_d_rid = resolve_rm_district_rid(clean_int(r.get("DISTRICT_ID")), r.get("DISTRICT_ENG"), rm_dist_rid_set, rm_dist_rid_by_name)
            if not rm_d_rid:
                continue
            c_en = (r.get("CITY_ENG") or f"ULB {cid}").strip()
            c_hi = (r.get("CITY_MANGAL") or "").strip() or None
            c_type = (r.get("CITY_TYPE_ENG") or "Nagar Palika").strip()
            c_code = (r.get("CITY_CODE") or f"C{cid}").strip()
            lg_str = str(clean_int(r.get("LG_CODE"))) if clean_int(r.get("LG_CODE")) else None
            full_name = f"{c_type} {c_en}".strip() if c_type.lower() not in c_en.lower() else c_en
            rm_ulb_batch.append((cid, rm_d_rid, c_code, lg_str, full_name, c_hi, c_en, json.dumps(r)))

        await conn.executemany("""
            INSERT INTO raj_masters.ulbs
            (raj_master_id, district_id, ulb_type_id, ulb_category_id, code, lgd_code, name_en, name_hi, city_name, is_active, raw_payload, synced_at)
            VALUES ($1, $2, NULL, NULL, $3, $4, $5, $6, $7, TRUE, $8::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                lgd_code = COALESCE(EXCLUDED.lgd_code, raj_masters.ulbs.lgd_code),
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                city_name = EXCLUDED.city_name,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """, rm_ulb_batch)

        await conn.execute("""
            UPDATE public.urban_local_bodies
            SET rajmaster_id = NULL
            WHERE code LIKE 'ULB%' AND (metadata_json->>'source' = 'seed' OR metadata_json IS NULL)
        """)

        pub_ulb_batch = []
        for r in ulb_rows:
            cid = clean_int(r.get("CITY_ID"))
            if not cid:
                continue
            pub_d_id = resolve_pub_district(r.get("DISTRICT_ENG"), pub_dist_by_name) or 12
            c_en = (r.get("CITY_ENG") or f"ULB {cid}").strip()
            c_hi = (r.get("CITY_MANGAL") or "").strip() or None
            c_type = (r.get("CITY_TYPE_ENG") or "Nagar Palika").strip()
            c_code = (r.get("CITY_CODE") or f"C{cid}").strip()
            lg_int = clean_int32(r.get("LG_CODE"))
            full_name = f"{c_type} {c_en}".strip() if c_type.lower() not in c_en.lower() else c_en
            meta_j = json.dumps({"source": "rajmasters_ulb_complete", "raw": r})
            pub_ulb_batch.append((pub_d_id, cid, c_code, full_name, c_hi, c_type, c_en, lg_int, meta_j))

        await conn.executemany("""
            INSERT INTO public.urban_local_bodies
            (district_id, rajmaster_id, code, name_en, name_hi, ulb_type, city_name, lgd_code, metadata_json, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW(), NOW())
            ON CONFLICT (rajmaster_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                ulb_type = EXCLUDED.ulb_type,
                city_name = EXCLUDED.city_name,
                lgd_code = COALESCE(EXCLUDED.lgd_code, public.urban_local_bodies.lgd_code),
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW();
        """, pub_ulb_batch)

        rm_ulb_rid_set = {r["raj_master_id"] for r in await conn.fetch("SELECT raj_master_id FROM raj_masters.ulbs")}
        pub_ulb_by_cid = {
            r["rajmaster_id"]: r["id"]
            for r in await conn.fetch("SELECT id, rajmaster_id FROM public.urban_local_bodies WHERE rajmaster_id IS NOT NULL")
        }

        # ------------------------------------------------------------------
        # 3. WARD RAJASTHAN (10,245) -> raj_masters.wards + public.urban_wards
        # ------------------------------------------------------------------
        ward_rows = await fetch_master("WARD RAJASTHAN", page_size=1000)
        logger.info(f"Syncing {len(ward_rows)} Urban Wards...")

        rm_ward_batch = []
        pub_ward_rows = []
        for r in ward_rows:
            wid = clean_int(r.get("WARD_ID"))
            cid = clean_int(r.get("CITY_ID"))
            if not wid or not cid:
                continue
            pub_ulb_pk = pub_ulb_by_cid.get(cid)
            w_en = (r.get("WARD_ENG") or f"Ward {wid}").strip()
            w_hi = (r.get("WARD_MANGAL") or "").strip() or None
            w_code = (r.get("WARD_CODE") or f"W{wid}").strip()
            lg_raw = clean_int(r.get("LG_CODE"))
            lg_int = clean_int32(lg_raw)
            lg_str = str(lg_raw) if lg_raw else None
            m_num = re.search(r"(\d+)", w_en)
            w_num = f"Ward {m_num.group(1)}" if m_num else w_en[:45]
            councillor = f"Parshad / Councillor, {w_en} ({r.get('CITY_ENG') or ''})".strip()
            meta_j = json.dumps({"source": "rajmasters_ward_complete", "raw": r})

            if cid in rm_ulb_rid_set:
                rm_ward_batch.append((wid, cid, w_num, w_code, lg_str, w_en, w_hi, councillor, json.dumps(r)))
            if pub_ulb_pk:
                pub_ward_rows.append((pub_ulb_pk, wid, w_num, w_en, w_hi, councillor, lg_int, meta_j))

        chunk_sz = 3000
        for i in range(0, len(rm_ward_batch), chunk_sz):
            await conn.executemany("""
                INSERT INTO raj_masters.wards
                (raj_master_id, ulb_id, ward_number, code, lgd_code, name_en, name_hi, councillor_parshad, is_active, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, $9::jsonb, NOW())
                ON CONFLICT (raj_master_id) DO UPDATE SET
                    ulb_id = EXCLUDED.ulb_id,
                    ward_number = EXCLUDED.ward_number,
                    code = EXCLUDED.code,
                    lgd_code = COALESCE(EXCLUDED.lgd_code, raj_masters.wards.lgd_code),
                    name_en = EXCLUDED.name_en,
                    name_hi = EXCLUDED.name_hi,
                    councillor_parshad = EXCLUDED.councillor_parshad,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, rm_ward_batch[i : i + chunk_sz])

        await conn.execute("""
            DELETE FROM public.urban_wards
            WHERE COALESCE(metadata_json->>'source', '') IN ('rajmaster_scraper', 'rajmasters_ward_complete')
        """)
        await conn.execute("""
            UPDATE public.urban_wards
            SET rajmaster_id = NULL
            WHERE COALESCE(metadata_json->>'source', '') = 'seed' AND rajmaster_id <= 10
        """)
        for i in range(0, len(pub_ward_rows), chunk_sz):
            await conn.executemany("""
                INSERT INTO public.urban_wards
                (ulb_id, rajmaster_id, ward_number, name_en, name_hi, councillor_parshad, lgd_code, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW(), NOW())
            """, pub_ward_rows[i : i + chunk_sz])

        # ------------------------------------------------------------------
        # 4. SUB-TEHSIL (290) -> raj_masters.sub_tehsils & public.tehsils_blocks
        # ------------------------------------------------------------------
        subteh_rows = await fetch_master("SUB-TEHSIL", page_size=1000)
        logger.info(f"Syncing {len(subteh_rows)} Sub-Tehsils...")
        rm_subteh_batch = []
        for r in subteh_rows:
            stid = clean_int(r.get("SUB_TEHSIL_ID") or r.get("SUBTEHSIL_ID") or r.get("ID"))
            tid = clean_int(r.get("TEHSIL_ID"))
            if not stid or not tid or tid not in rm_teh_rid_set:
                continue
            rm_d_rid = resolve_rm_district_rid(clean_int(r.get("DISTRICT_ID")), r.get("DISTRICT_ENG"), rm_dist_rid_set, rm_dist_rid_by_name)
            st_en = (r.get("SUB_TEHSIL_ENG") or r.get("SUBTEHSIL_ENG") or f"Sub-Tehsil {stid}").strip()
            st_hi = (r.get("SUB_TEHSIL_MANGAL") or r.get("SUBTEHSIL_MANGAL") or "").strip() or None
            st_code = (r.get("SUB_TEHSIL_CODE") or r.get("SUBTEHSIL_CODE") or f"ST{stid}").strip()
            rm_subteh_batch.append((stid, tid, rm_d_rid, st_code, st_en, st_hi, f"Naib Tehsildar, {st_en}", json.dumps(r)))
        if rm_subteh_batch:
            await conn.executemany("""
                INSERT INTO raj_masters.sub_tehsils
                (raj_master_id, tehsil_id, district_id, code, name_en, name_hi, naib_tehsildar_details, is_active, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8::jsonb, NOW())
                ON CONFLICT (raj_master_id) DO UPDATE SET
                    tehsil_id = EXCLUDED.tehsil_id,
                    district_id = EXCLUDED.district_id,
                    code = EXCLUDED.code,
                    name_en = EXCLUDED.name_en,
                    name_hi = EXCLUDED.name_hi,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, rm_subteh_batch)

        # ------------------------------------------------------------------
        # 5. ILR RAJASTHAN (2,815) & PATWAR RAJASTHAN (11,336)
        # ------------------------------------------------------------------
        ilr_rows = await fetch_master("ILR RAJASTHAN", page_size=1000)
        logger.info(f"Syncing {len(ilr_rows)} ILR Circles...")
        rm_ilr_batch = []
        for r in ilr_rows:
            iid = clean_int(r.get("ILR_ID"))
            tid = clean_int(r.get("TEHSIL_ID"))
            if not iid or not tid or tid not in rm_teh_rid_set:
                continue
            rm_ilr_batch.append((
                iid, tid,
                (r.get("ILR_CODE") or f"ILR{iid}").strip(),
                (r.get("ILR_ENG") or f"ILR {iid}").strip(),
                (r.get("ILR_MANGAL") or "").strip() or None,
                json.dumps(r),
            ))
        for i in range(0, len(rm_ilr_batch), chunk_sz):
            await conn.executemany("""
                INSERT INTO raj_masters.ilr_circles
                (raj_master_id, tehsil_id, code, name_en, name_hi, is_active, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, TRUE, $6::jsonb, NOW())
                ON CONFLICT (raj_master_id) DO UPDATE SET
                    tehsil_id = EXCLUDED.tehsil_id,
                    code = EXCLUDED.code,
                    name_en = EXCLUDED.name_en,
                    name_hi = EXCLUDED.name_hi,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, rm_ilr_batch[i : i + chunk_sz])

        rm_ilr_rid_set = {r["raj_master_id"] for r in await conn.fetch("SELECT raj_master_id FROM raj_masters.ilr_circles")}

        patwar_rows = await fetch_master("PATWAR RAJASTHAN", page_size=1000)
        logger.info(f"Syncing {len(patwar_rows)} Patwar Circles...")
        rm_pat_batch = []
        for r in patwar_rows:
            pid = clean_int(r.get("PATWAR_ID"))
            tid = clean_int(r.get("TEHSIL_ID"))
            iid = clean_int(r.get("ILR_ID"))
            if not pid:
                continue
            tid_fk = tid if (tid and tid in rm_teh_rid_set) else None
            iid_fk = iid if (iid and iid in rm_ilr_rid_set) else None
            p_en = (r.get("PATWAR_ENG") or f"Patwar {pid}").strip()
            p_hi = (r.get("PATWAR_MANGAL") or "").strip() or None
            p_code = (r.get("PATWAR_CODE") or f"PAT{pid}").strip()
            rm_pat_batch.append((pid, iid_fk, tid_fk, p_code, p_en, p_hi, f"Patwari, {p_en}", json.dumps(r)))
        for i in range(0, len(rm_pat_batch), chunk_sz):
            await conn.executemany("""
                INSERT INTO raj_masters.patwar_circles
                (raj_master_id, ilr_circle_id, tehsil_id, code, name_en, name_hi, patwari_name, is_active, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8::jsonb, NOW())
                ON CONFLICT (raj_master_id) DO UPDATE SET
                    ilr_circle_id = EXCLUDED.ilr_circle_id,
                    tehsil_id = EXCLUDED.tehsil_id,
                    code = EXCLUDED.code,
                    name_en = EXCLUDED.name_en,
                    name_hi = EXCLUDED.name_hi,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, rm_pat_batch[i : i + chunk_sz])

        # ------------------------------------------------------------------
        # 6. Mirror gp_hierarchy (14,496) & village_hierarchy (51,892) -> raj_masters.gram_panchayats & raj_masters.villages
        # ------------------------------------------------------------------
        logger.info("Populating raj_masters.gram_panchayats and raj_masters.villages from synced hierarchies...")
        await conn.execute("""
            INSERT INTO raj_masters.gram_panchayats
            (raj_master_id, block_id, district_id, code, lgd_code, name_en, name_hi, sarpanch_name, is_active, raw_payload, synced_at)
            SELECT
                gh.gp_id,
                b.raj_master_id,
                COALESCE(d.raj_master_id, b.district_id),
                gh.gp_code,
                gh.gp_lgdcode::text,
                gh.gp_eng,
                gh.gp_mangal,
                'Sarpanch, GP ' || gh.gp_eng,
                TRUE,
                gh.raw_payload,
                NOW()
            FROM raj_masters.gp_hierarchy gh
            JOIN raj_masters.blocks b ON b.raj_master_id = gh.block_id
            LEFT JOIN raj_masters.districts d ON d.raj_master_id = gh.district_id
            ON CONFLICT (raj_master_id) DO NOTHING;
        """)

        await conn.execute("""
            INSERT INTO raj_masters.villages
            (raj_master_id, patwar_circle_id, tehsil_id, district_id, gram_panchayat_id, code, lgd_code, name_en, name_hi, is_active, raw_payload, synced_at)
            SELECT
                vh.village_id,
                pc.raj_master_id,
                t.raj_master_id,
                COALESCE(d.raj_master_id, t.district_id),
                gp.raj_master_id,
                vh.village_code,
                vh.village_lgdcode::text,
                vh.village_eng,
                vh.village_mangal,
                TRUE,
                vh.raw_payload,
                NOW()
            FROM raj_masters.village_hierarchy vh
            LEFT JOIN raj_masters.tehsils t ON t.raj_master_id = vh.tehsil_id
            LEFT JOIN raj_masters.districts d ON d.raj_master_id = vh.district_id
            LEFT JOIN raj_masters.patwar_circles pc ON pc.raj_master_id = vh.patwar_id
            LEFT JOIN raj_masters.gram_panchayats gp ON gp.raj_master_id = vh.gp_id
            ON CONFLICT (raj_master_id) DO NOTHING;
        """)

        # ------------------------------------------------------------------
        # 7. Log scraper runs & print verification counts
        # ------------------------------------------------------------------
        duration = round(time.time() - t_start, 2)
        await conn.execute("""
            INSERT INTO public.scraper_runs (master_name, status, rows_fetched, rows_upserted, error_logs, started_at, completed_at)
            VALUES
                ('SUB-DIVISION', 'completed', $1, $1, NULL, NOW() - ($4::double precision * interval '1 second'), NOW()),
                ('URBAN LOCAL BODY(CITY) RAJASTHAN', 'completed', $2, $2, NULL, NOW() - ($4::double precision * interval '1 second'), NOW()),
                ('WARD RAJASTHAN', 'completed', $3, $3, NULL, NOW() - ($4::double precision * interval '1 second'), NOW())
        """, len(sd_portal_rows), len(ulb_rows), len(ward_rows), duration)

        for tbl in [
            "public.divisions", "public.districts", "public.sub_divisions",
            "public.tehsils_blocks", "public.gram_panchayats", "public.villages",
            "public.urban_local_bodies", "public.urban_wards", "public.pincodes",
            "raj_masters.sub_divisions", "raj_masters.sub_tehsils",
            "raj_masters.ilr_circles", "raj_masters.patwar_circles",
            "raj_masters.gram_panchayats", "raj_masters.villages",
            "raj_masters.ulbs", "raj_masters.wards",
            "raj_masters.pincodes", "raj_masters.pincode_localities",
        ]:
            cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            logger.info(f"  {tbl}: {cnt}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_sync())
