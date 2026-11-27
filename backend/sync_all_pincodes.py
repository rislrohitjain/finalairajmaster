"""
Complete Rajasthan Pincode Synchronization Pipeline (Local PostgreSQL)
Fetches all 53,967+ records from RajMasters (PINCODE RAJASTHAN), preserves every
locality/post-office record in raj_masters.pincode_localities, updates
raj_masters.pincodes with aggregated localities, and populates/normalizes
public.pincodes with accurate division_id, district_id, tehsil_block_id,
and rich metadata_json for demos.
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
logger = logging.getLogger("sync_all_pincodes")

DB_DSN = os.getenv(
    "POSTGRES_DSN",
    "postgresql://postgres:Admin%40123@127.0.0.1:5432/finalairajmaster",
)
PORTAL_URL = "https://rajmasters.rajasthan.gov.in"

# Alias normalization for district names in RajMasters pincodes -> public.districts
DISTRICT_ALIASES: Dict[str, str] = {
    "BARA": "BARAN",
    "GANGANAGAR": "SRI GANGANAGAR",
    "JALOR": "JALORE",
    "JHUJHUNU": "JHUNJHUNU",
    "CHITTAURGARH": "CHITTORGARH",
    "DHAULPUR": "DHOLPUR",
    "BALOTARA": "BALOTRA",
    "SALUMBER": "SALUMBAR",
    "NEEM KA THANA": "NEEM KA THANA",
    "NEEM-KA-THANA": "NEEM KA THANA",
    "DEEDWANA-KUCHAMAN": "DIDWANA-KUCHAMAN",
}

# Alias normalization for subdistrict/tehsil names -> public.tehsils_blocks
SUBDIST_ALIASES: Dict[str, List[str]] = {
    "BARA": ["BARAN", "BARAN (FULL)"],
    "BEEJOLIYA": ["BIJOLIYA", "BIJOLIA"],
    "BEGU": ["BEGUN"],
    "CHITTAURGARH": ["CHITTORGARH"],
    "CHOHTA": ["CHOHTAN"],
    "DUDU (HQ. MAUZAMABAD)": ["DUDU", "MAUZAMABAD", "MOZMABAD"],
    "DUNGARGARH": ["SHRIDUNGARGARH", "SRI DUNGARGARH", "DUNGARGARH"],
    "GANGANAGAR": ["SRIGANGANAGAR", "SRI GANGANAGAR", "GANGANAGAR"],
    "GANGAPUR": ["GANGAPUR", "GANGAPUR CITY"],
    "GUDHA MALANI": ["GUDAMALANI", "GUDHA MALANI"],
    "HINDAU": ["HINDAUN", "HINDAUN CITY"],
    "JAITARA": ["JAITARAN"],
    "JALOR": ["JALORE"],
    "JHALRAPATA": ["JHALRAPATAN", "JHALRA PATAN"],
    "KAMA": ["KAMAN"],
    "KAPASA": ["KAPASAN"],
    "KESHORAIPATA": ["KESHORAIPATAN"],
    "KHEENVSAR": ["KHINVSAR"],
    "MANDRAIL": ["MANDRAYAL"],
    "MARWAR JUNCTIO": ["MARWAR JUNCTION"],
    "NEEM-KA-THANA": ["NEEM KA THANA", "NEEMKATHANA"],
    "OSIA": ["OSIAN"],
    "PEESANGA": ["PEESANGAN", "PISANGAN"],
    "POKARA": ["POKARAN", "POKHRAN"],
    "SEPAU": ["SAIPAU", "SEPAU"],
    "TIBI": ["TIBBI"],
    "JAIPUR URBAN": ["JAIPUR"],
    "JAIPUR HERITAGE": ["JAIPUR"],
    "JAIPUR GREATER": ["JAIPUR", "SANGANER"],
    "JAIPUR NORTH": ["JAIPUR", "AMER"],
    "JAIPUR EAST": ["JAIPUR", "BASSI"],
    "KOTPUTLI": ["KOTPUTLI"],
    "PHULERA": ["PHULERA (HQ.SAMBHAR)", "PHULERA", "SAMBHARLAKE"],
}


def parse_row(item: Any) -> Dict[str, Any]:
    if isinstance(item, list):
        return {kv["Key"]: kv.get("Value") for kv in item if isinstance(kv, dict) and "Key" in kv}
    if isinstance(item, dict):
        return item
    return {}


async def fetch_all_pincodes(page_size: int = 5000) -> List[Dict[str, Any]]:
    headers_get = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    headers_post = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": f"{PORTAL_URL}/Home/List?master=PINCODE RAJASTHAN",
    }

    all_rows: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=90.0, verify=False, follow_redirects=True) as client:
        r0 = await client.get(f"{PORTAL_URL}/Home/List?master=PINCODE RAJASTHAN", headers=headers_get)
        logger.info(f"Session init GET status: {r0.status_code}")

        page = 1
        total_count = None
        while True:
            payload = {
                "master": "PINCODE RAJASTHAN",
                "Page": page,
                "Size": page_size,
                "DivisionId": "",
                "DistrictId": "0",
                "TehsilId": "0",
                "BlockId": "0",
            }
            for attempt in range(4):
                try:
                    resp = await client.post(f"{PORTAL_URL}/Home/ListData", json=payload, headers=headers_post)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except Exception as exc:
                    if attempt == 3:
                        raise
                    logger.warning(f"Page {page} attempt {attempt+1} failed ({exc}), retrying...")
                    await asyncio.sleep(2 * (attempt + 1))

            raw_rows = data.get("data") or []
            if total_count is None:
                total_count = int(data.get("TotalCount") or len(raw_rows))
                logger.info(f"Portal declared TotalCount={total_count}")

            if not raw_rows:
                break

            parsed_batch = [parse_row(r) for r in raw_rows if parse_row(r)]
            all_rows.extend(parsed_batch)
            logger.info(f"Page {page}: fetched {len(parsed_batch)} rows (cumulative {len(all_rows)} / {total_count})")

            if len(all_rows) >= total_count or len(raw_rows) < page_size:
                break
            page += 1
            await asyncio.sleep(0.1)

    return all_rows


def resolve_district_name(raw_dist: str) -> str:
    clean = re.sub(r"\s+", " ", (raw_dist or "").upper().strip())
    return DISTRICT_ALIASES.get(clean, clean)


def resolve_tehsil_id(
    subdist_name: str,
    dist_id: Optional[int],
    tb_by_dist_and_name: Dict[Tuple[int, str], int],
    tb_by_name: Dict[str, int],
) -> Optional[int]:
    if not subdist_name:
        return None
    norm = re.sub(r"\s+", " ", subdist_name.upper().strip())
    candidates = [norm] + SUBDIST_ALIASES.get(norm, [])
    # Also try stripping parentheticals e.g. "Dudu (Hq. Mauzamabad)" -> "Dudu"
    no_paren = re.sub(r"\s*\(.*?\)", "", norm).strip()
    if no_paren and no_paren not in candidates:
        candidates.append(no_paren)

    if dist_id is not None:
        for cand in candidates:
            if (dist_id, cand) in tb_by_dist_and_name:
                return tb_by_dist_and_name[(dist_id, cand)]

    for cand in candidates:
        if cand in tb_by_name:
            return tb_by_name[cand]

    return None


async def sync_to_local_db(from_db: bool = False):
    t_start = time.time()
    conn = await asyncpg.connect(DB_DSN)
    try:
        # Ensure raj_masters.pincode_localities exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS raj_masters.pincode_localities (
                id BIGSERIAL PRIMARY KEY,
                raj_master_id BIGINT UNIQUE NOT NULL,
                pincode VARCHAR(10) NOT NULL,
                office_name TEXT NOT NULL,
                locality_name TEXT,
                subdist_name TEXT,
                district_name TEXT,
                state_name TEXT DEFAULT 'RAJASTHAN',
                district_id BIGINT,
                division_id BIGINT,
                raw_payload JSONB DEFAULT '{}'::jsonb,
                synced_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_rm_pinloc_pincode ON raj_masters.pincode_localities(pincode);
            CREATE INDEX IF NOT EXISTS idx_rm_pinloc_dist ON raj_masters.pincode_localities(district_name);
            CREATE INDEX IF NOT EXISTS idx_rm_pinloc_subdist ON raj_masters.pincode_localities(subdist_name);
            CREATE INDEX IF NOT EXISTS idx_rm_pinloc_locality_trgm ON raj_masters.pincode_localities USING gin (locality_name gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS idx_rm_pinloc_office_trgm ON raj_masters.pincode_localities USING gin (office_name gin_trgm_ops);
        """)

        if from_db:
            logger.info("Step 1/4: Loading PINCODE RAJASTHAN rows from local raj_masters.pincode_localities...")
            db_rows = await conn.fetch("""
                SELECT raj_master_id AS "PINCODE_ID", pincode AS "PINCODE", office_name AS "OFFICE_NAME",
                       locality_name AS "LOCALITY_NAME", subdist_name AS "SUBDIST_NAME",
                       district_name AS "DISTRICT_NAME", state_name AS "STATE_NAME"
                FROM raj_masters.pincode_localities
            """)
            raw_rows = [dict(r) for r in db_rows]
            logger.info(f"Loaded {len(raw_rows)} rows from local DB.")
        else:
            logger.info("Step 1/4: Fetching complete PINCODE RAJASTHAN dataset from portal...")
            raw_rows = await fetch_all_pincodes(page_size=5000)
            logger.info(f"Fetched {len(raw_rows)} total rows from RajMasters portal.")

        # Load raj_masters.districts for ID resolution
        rm_dists = await conn.fetch("SELECT raj_master_id, division_id, name_en FROM raj_masters.districts")
        rm_dist_map: Dict[str, Tuple[int, Optional[int]]] = {}
        for d in rm_dists:
            rm_dist_map[d["name_en"].upper().strip()] = (d["raj_master_id"], d["division_id"])

        # Prepare batch for raj_masters.pincode_localities and aggregate for raj_masters.pincodes
        loc_batch = []
        office_agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
        pin_agg: Dict[str, Dict[str, Any]] = {}

        for r in raw_rows:
            raw_pin = str(r.get("PINCODE") or "").strip()
            if len(raw_pin) < 6:
                continue
            pin = raw_pin[:6]
            if not pin.isdigit():
                continue

            r_id = r.get("PINCODE_ID")
            if not r_id:
                continue
            r_id_int = int(r_id)

            office_name = re.sub(r"\s+", " ", str(r.get("OFFICE_NAME") or "General Post Office").strip())
            locality_name = re.sub(r"\s+", " ", str(r.get("LOCALITY_NAME") or office_name).strip())
            dist_name = re.sub(r"\s+", " ", str(r.get("DISTRICT_NAME") or "").strip())
            subdist_name = re.sub(r"\s+", " ", str(r.get("SUBDIST_NAME") or "").strip())
            state_name = re.sub(r"\s+", " ", str(r.get("STATE_NAME") or "RAJASTHAN").strip())

            resolved_dist = resolve_district_name(dist_name)
            rm_d_info = rm_dist_map.get(resolved_dist) or rm_dist_map.get(dist_name.upper())
            rm_dist_id = rm_d_info[0] if rm_d_info else None
            rm_div_id = rm_d_info[1] if rm_d_info else None

            loc_batch.append((
                r_id_int,
                pin,
                office_name,
                locality_name,
                subdist_name or None,
                dist_name or None,
                state_name or "RAJASTHAN",
                rm_dist_id,
                rm_div_id,
                json.dumps(r),
            ))

            # Aggregate per (pincode, office_name)
            ok = (pin, office_name)
            if ok not in office_agg:
                office_agg[ok] = {
                    "pincode": pin,
                    "office_name": office_name,
                    "localities": [],
                    "loc_set": set(),
                    "district_id": rm_dist_id,
                    "division_id": rm_div_id,
                    "subdist_name": subdist_name,
                    "district_name": dist_name,
                    "state_name": state_name or "RAJASTHAN",
                    "raj_master_id": r_id_int,
                    "sample_raw": r,
                }
            if locality_name and locality_name.lower() not in office_agg[ok]["loc_set"]:
                office_agg[ok]["loc_set"].add(locality_name.lower())
                office_agg[ok]["localities"].append(locality_name)

            # Aggregate per unique 6-digit pincode
            if pin not in pin_agg:
                pin_agg[pin] = {
                    "pincode": pin,
                    "districts": {},
                    "subdistricts": {},
                    "offices": [],
                    "office_set": set(),
                    "localities": [],
                    "loc_set": set(),
                }
            pa = pin_agg[pin]
            if dist_name:
                pa["districts"][dist_name] = pa["districts"].get(dist_name, 0) + 1
            if subdist_name:
                pa["subdistricts"][subdist_name] = pa["subdistricts"].get(subdist_name, 0) + 1
            if office_name and office_name.lower() not in pa["office_set"]:
                pa["office_set"].add(office_name.lower())
                pa["offices"].append(office_name)
            if locality_name and locality_name.lower() not in pa["loc_set"]:
                pa["loc_set"].add(locality_name.lower())
                pa["localities"].append(locality_name)

        logger.info(f"Step 2/4: Upserting {len(loc_batch)} locality rows into raj_masters.pincode_localities...")
        chunk_size = 3000
        for i in range(0, len(loc_batch), chunk_size):
            chunk = loc_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO raj_masters.pincode_localities
                (raj_master_id, pincode, office_name, locality_name, subdist_name, district_name, state_name, district_id, division_id, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
                ON CONFLICT (raj_master_id) DO UPDATE SET
                    pincode = EXCLUDED.pincode,
                    office_name = EXCLUDED.office_name,
                    locality_name = EXCLUDED.locality_name,
                    subdist_name = EXCLUDED.subdist_name,
                    district_name = EXCLUDED.district_name,
                    state_name = EXCLUDED.state_name,
                    district_id = EXCLUDED.district_id,
                    division_id = EXCLUDED.division_id,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, chunk)

        logger.info(f"Step 3/4: Upserting {len(office_agg)} unique (pincode, office) rows into raj_masters.pincodes...")
        rm_pin_batch = []
        for ok, info in office_agg.items():
            locs_joined = ", ".join(info["localities"][:25])
            payload_obj = dict(info["sample_raw"])
            payload_obj["all_localities"] = info["localities"]
            payload_obj["total_localities"] = len(info["localities"])
            rm_pin_batch.append((
                info["pincode"],
                info["office_name"],
                locs_joined[:1000] if locs_joined else info["office_name"],
                info["district_id"],
                info["division_id"],
                info["subdist_name"] or None,
                info["district_name"] or None,
                info["state_name"],
                info["raj_master_id"],
                json.dumps(payload_obj),
            ))

        for i in range(0, len(rm_pin_batch), chunk_size):
            chunk = rm_pin_batch[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO raj_masters.pincodes
                (pincode, office_name, locality_name, district_id, division_id, subdist_name, district_name, state_name, raj_master_id, raw_payload, synced_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
                ON CONFLICT (pincode, office_name) DO UPDATE SET
                    locality_name = EXCLUDED.locality_name,
                    district_id = COALESCE(EXCLUDED.district_id, raj_masters.pincodes.district_id),
                    division_id = COALESCE(EXCLUDED.division_id, raj_masters.pincodes.division_id),
                    subdist_name = EXCLUDED.subdist_name,
                    district_name = EXCLUDED.district_name,
                    state_name = EXCLUDED.state_name,
                    raw_payload = EXCLUDED.raw_payload,
                    synced_at = NOW();
            """, chunk)

        logger.info(f"Step 4/4: Normalizing & syncing {len(pin_agg)} unique pincodes + fallback urban pincodes into public.pincodes...")

        # Load public.divisions and public.districts (prefer higher IDs for 10-division canonical mapping when duplicate names exist)
        pub_divs = await conn.fetch("SELECT id, name_en FROM public.divisions ORDER BY id")
        pub_div_name_by_id = {d["id"]: d["name_en"] for d in pub_divs}

        pub_dists = await conn.fetch("SELECT id, name_en, division_id FROM public.districts ORDER BY id ASC")
        pub_dist_by_name: Dict[str, Tuple[int, Optional[int], str]] = {}
        for d in pub_dists:
            key = d["name_en"].upper().strip()
            # Later rows (id >= 40) carry updated Sikar/Pali/Banswara divisions; keep canonical mapping
            pub_dist_by_name[key] = (d["id"], d["division_id"], d["name_en"])

        # Load public.tehsils_blocks (prefer Tehsil over Block when same name)
        pub_tbs = await conn.fetch("SELECT id, district_id, name_en, entity_type FROM public.tehsils_blocks ORDER BY CASE WHEN entity_type='Tehsil' THEN 0 ELSE 1 END, id ASC")
        tb_by_dist_and_name: Dict[Tuple[int, str], int] = {}
        tb_by_name: Dict[str, int] = {}
        for tb in pub_tbs:
            nm = re.sub(r"\s+", " ", (tb["name_en"] or "").upper().strip())
            if not nm:
                continue
            if tb["district_id"] and (tb["district_id"], nm) not in tb_by_dist_and_name:
                tb_by_dist_and_name[(tb["district_id"], nm)] = tb["id"]
            if nm not in tb_by_name:
                tb_by_name[nm] = tb["id"]

        # Load existing public.pincodes to preserve curated descriptions & ulb/gp links
        existing_pub = await conn.fetch("SELECT id, pincode, city_or_village, gram_panchayat_id, ulb_id, tehsil_block_id, district_id, division_id, metadata_json FROM public.pincodes")
        existing_map = {r["pincode"]: dict(r) for r in existing_pub}

        # Fix any existing rows that aren't in pin_agg (e.g., 21 curated Jaipur/urban pincodes)
        pub_upserts = []
        for pin, pa in sorted(pin_agg.items()):
            primary_dist_raw = max(pa["districts"].items(), key=lambda kv: kv[1])[0] if pa["districts"] else ""
            primary_subdist = max(pa["subdistricts"].items(), key=lambda kv: kv[1])[0] if pa["subdistricts"] else ""

            resolved_dist_key = resolve_district_name(primary_dist_raw)
            dist_entry = pub_dist_by_name.get(resolved_dist_key)
            if not dist_entry:
                # Fallback prefix match
                for k, v in pub_dist_by_name.items():
                    if k in resolved_dist_key or resolved_dist_key in k:
                        dist_entry = v
                        break

            dist_id = dist_entry[0] if dist_entry else None
            div_id = dist_entry[1] if dist_entry else None
            dist_label = dist_entry[2] if dist_entry else (primary_dist_raw.title() if primary_dist_raw else "Rajasthan")
            div_label = pub_div_name_by_id.get(div_id, "Rajasthan") if div_id else "Rajasthan"

            tb_id = resolve_tehsil_id(primary_subdist, dist_id, tb_by_dist_and_name, tb_by_name)

            ex = existing_map.get(pin)
            # Preserve curated multi-locality label (e.g., containing '/' or lowercase descriptive names) if present
            if ex and ex["city_or_village"] and ("/" in ex["city_or_village"] or "," in ex["city_or_village"]) and not ex["city_or_village"].isupper():
                city_label = ex["city_or_village"]
                # If curated entry had Jaipur metadata tehsil_or_zone, keep or resolve tb_id
                if not tb_id:
                    tb_id = ex["tehsil_block_id"]
            else:
                sorted_offices = sorted(pa["offices"])
                top_offices = ", ".join(sorted_offices[:3])
                more_cnt = len(sorted_offices) - 3
                sub_title = primary_subdist.title() if primary_subdist else dist_label
                if top_offices:
                    city_label = f"{sub_title} ({top_offices}" + (f" +{more_cnt} more)" if more_cnt > 0 else ")")
                else:
                    city_label = sub_title

            sorted_offices = sorted(pa["offices"])
            sorted_locs = sorted(pa["localities"])
            meta_obj = {
                "state": "Rajasthan",
                "circle": "Rajasthan Postal Circle",
                "division": div_label,
                "district": dist_label,
                "subdistrict": primary_subdist or sub_title,
                "offices": ", ".join(sorted_offices),
                "localities": ", ".join(sorted_locs[:60]),
                "total_offices": len(sorted_offices),
                "total_localities": len(sorted_locs),
                "source": "rajmasters_pincode_complete",
            }
            if ex and ex.get("metadata_json"):
                try:
                    prev_meta = json.loads(ex["metadata_json"]) if isinstance(ex["metadata_json"], str) else ex["metadata_json"]
                    if isinstance(prev_meta, dict) and prev_meta.get("tehsil_or_zone"):
                        meta_obj["tehsil_or_zone"] = prev_meta["tehsil_or_zone"]
                except Exception:
                    pass

            pub_upserts.append((
                pin,
                city_label[:150],
                ex["gram_panchayat_id"] if ex else None,
                ex["ulb_id"] if ex else None,
                tb_id,
                dist_id,
                div_id,
                json.dumps(meta_obj),
            ))

        for i in range(0, len(pub_upserts), chunk_size):
            chunk = pub_upserts[i : i + chunk_size]
            await conn.executemany("""
                INSERT INTO public.pincodes
                (pincode, city_or_village, gram_panchayat_id, ulb_id, tehsil_block_id, district_id, division_id, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW(), NOW())
                ON CONFLICT (pincode) DO UPDATE SET
                    city_or_village = EXCLUDED.city_or_village,
                    gram_panchayat_id = COALESCE(EXCLUDED.gram_panchayat_id, public.pincodes.gram_panchayat_id),
                    ulb_id = COALESCE(EXCLUDED.ulb_id, public.pincodes.ulb_id),
                    tehsil_block_id = COALESCE(EXCLUDED.tehsil_block_id, public.pincodes.tehsil_block_id),
                    district_id = COALESCE(EXCLUDED.district_id, public.pincodes.district_id),
                    division_id = COALESCE(EXCLUDED.division_id, public.pincodes.division_id),
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW();
            """, chunk)

        # Also fix tehsil_block_id & metadata on any remaining public.pincodes rows (e.g. the 21 extra Jaipur/urban pincodes)
        extra_rows = await conn.fetch("""
            SELECT id, pincode, city_or_village, district_id, division_id, tehsil_block_id, metadata_json
            FROM public.pincodes
            WHERE tehsil_block_id IS NULL OR district_id IS NULL OR division_id IS NULL
        """)
        for er in extra_rows:
            meta = {}
            if er["metadata_json"]:
                meta = json.loads(er["metadata_json"]) if isinstance(er["metadata_json"], str) else dict(er["metadata_json"])
            tz = meta.get("tehsil_or_zone") or meta.get("subdistrict") or ""
            dist_id = er["district_id"]
            div_id = er["division_id"]
            if not dist_id and meta.get("district"):
                d_entry = pub_dist_by_name.get(resolve_district_name(meta["district"]))
                if d_entry:
                    dist_id, div_id = d_entry[0], d_entry[1]
            tb_id = er["tehsil_block_id"] or resolve_tehsil_id(tz, dist_id, tb_by_dist_and_name, tb_by_name)
            if not tb_id and dist_id == 12:
                # Default urban Jaipur tehsil
                tb_id = tb_by_dist_and_name.get((12, "JAIPUR"))
            await conn.execute("""
                UPDATE public.pincodes
                SET district_id = COALESCE($1, district_id),
                    division_id = COALESCE($2, division_id),
                    tehsil_block_id = COALESCE($3, tehsil_block_id),
                    updated_at = NOW()
                WHERE id = $4
            """, dist_id, div_id, tb_id, er["id"])

        # Log completion in scraper_runs & sync_audit_log
        duration = round(time.time() - t_start, 2)
        await conn.execute("""
            INSERT INTO public.scraper_runs (master_name, status, rows_fetched, rows_upserted, error_logs, started_at, completed_at)
            VALUES ('PINCODE RAJASTHAN', 'completed', $1, $2, NULL, NOW() - ($3::double precision * interval '1 second'), NOW())
        """, len(raw_rows), len(pub_upserts), duration)

        await conn.execute("""
            INSERT INTO raj_masters.sync_audit_log (master_name, tier_level, expected_count, fetched_count, upserted_count, status, duration_seconds, mode, created_at, completed_at)
            VALUES ('PINCODE RAJASTHAN', 6, $1, $1, $2, 'COMPLETED', $3::numeric, 'full', NOW() - ($4::double precision * interval '1 second'), NOW())
        """, len(raw_rows), len(loc_batch), duration, duration)

        # Print verification summary
        rm_loc_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.pincode_localities")
        rm_pin_cnt = await conn.fetchval("SELECT count(*) FROM raj_masters.pincodes")
        pub_stats = dict(await conn.fetchrow("""
            SELECT count(*) as total,
                   count(district_id) as has_dist,
                   count(division_id) as has_div,
                   count(tehsil_block_id) as has_tb
            FROM public.pincodes
        """))
        logger.info("=== COMPLETE PINCODE SYNC VERIFICATION ===")
        logger.info(f"raj_masters.pincode_localities: {rm_loc_cnt}")
        logger.info(f"raj_masters.pincodes (unique pin+office): {rm_pin_cnt}")
        logger.info(f"public.pincodes stats: {pub_stats}")
        logger.info(f"Completed in {duration}s")
    finally:
        await conn.close()


if __name__ == "__main__":
    import sys
    asyncio.run(sync_to_local_db(from_db="--from-db" in sys.argv))
