import asyncio
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup
import polars as pl
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, update, func
from app.db.session import async_engine, AsyncSessionLocal
from app.db.models import (
    Division, District, SubDivision, TehsilBlock,
    GramPanchayat, PanchayatWard, Village, UrbanLocalBody, UrbanWard,
    Pincode, ScraperRun
)
from app.config import settings
from app.db.init_db import (
    FALLBACK_DIVISIONS, FALLBACK_DISTRICTS, FALLBACK_SUBDIVISIONS,
    FALLBACK_TEHSILS_BLOCKS, FALLBACK_GRAM_PANCHAYATS, FALLBACK_VILLAGES,
    FALLBACK_ULBS, FALLBACK_URBAN_WARDS, FALLBACK_PINCODES
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("rajmaster_scraper")

# Master endpoint mapping
MASTER_MAP = {
    "DIVISION RAJASTHAN": "DIVISION RAJASTHAN",
    "DIVISIONS": "DIVISION RAJASTHAN",
    "DISTRICT RAJASTHAN": "DISTRICT RAJASTHAN",
    "DISTRICTS": "DISTRICT RAJASTHAN",
    "SUB DIVISION RAJASTHAN": "SUB-DIVISION",
    "SUB-DIVISION": "SUB-DIVISION",
    "SUBDIVISIONS": "SUB-DIVISION",
    "TEHSIL RAJASTHAN": "TEHSIL RAJASTHAN",
    "TEHSILS": "TEHSIL RAJASTHAN",
    "SUB-TEHSIL": "SUB-TEHSIL",
    "PANCHAYAT SAMITI RAJASTHAN": "BLOCK RAJASTHAN",
    "BLOCK RAJASTHAN": "BLOCK RAJASTHAN",
    "BLOCKS": "BLOCK RAJASTHAN",
    "GRAM PANCHAYAT RAJASTHAN": "GRAM PANCHAYAT RAJASTHAN",
    "GRAM PANCHAYATS": "GRAM PANCHAYAT RAJASTHAN",
    "PATWAR CIRCLE RAJASTHAN": "PATWAR RAJASTHAN",
    "PATWAR RAJASTHAN": "PATWAR RAJASTHAN",
    "VILLAGE RAJASTHAN": "VILLAGE RAJASTHAN",
    "VILLAGES": "VILLAGE RAJASTHAN",
    "ULB RAJASTHAN": "URBAN LOCAL BODY(CITY) RAJASTHAN",
    "MUNICIPALITY RAJASTHAN": "URBAN LOCAL BODY(CITY) RAJASTHAN",
    "URBAN LOCAL BODY(CITY) RAJASTHAN": "URBAN LOCAL BODY(CITY) RAJASTHAN",
    "URBAN WARD RAJASTHAN": "WARD RAJASTHAN",
    "WARD RAJASTHAN": "WARD RAJASTHAN",
    "PINCODE RAJASTHAN": "PINCODE RAJASTHAN",
}

class RajMasterScraper:
    def __init__(self, base_url: str = settings.RAJMASTER_BASE_URL):
        self.base_url = base_url.rstrip("/")

    async def fetch_master_rows(self, master_name: str, max_records: int = 500) -> List[Dict[str, Any]]:
        """Fetch rows from https://rajmasters.rajasthan.gov.in/Home/ListData"""
        url_list = f"{self.base_url}/Home/List?master={master_name}"
        url_data = f"{self.base_url}/Home/ListData"

        get_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        post_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": url_list,
        }

        records: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(verify=False, timeout=30.0, follow_redirects=True) as client:
            try:
                # 1. Establish session & load master context
                r_init = await client.get(url_list, headers=get_headers)
                if r_init.status_code != 200:
                    logger.warning(f"Failed to initialize master '{master_name}': status {r_init.status_code}")
                    return []

                # 2. Query ListData
                page = 1
                page_size = min(max_records, 200)

                while len(records) < max_records:
                    payload = {
                        "DivisionId": "",
                        "DistrictId": "0",
                        "TehsilId": "0",
                        "BlockId": "0",
                        "GpId": "0",
                        "CityTypeId": "0",
                        "CityId": "0",
                        "PD_Id": "0",
                        "RangeId": "0",
                        "CircleId": "0",
                        "searchText": "",
                        "CasteCategoryId": "0",
                        "BankId": "0",
                        "searchName": "",
                        "Size": page_size,
                        "Page": page
                    }

                    r_data = await client.post(url_data, json=payload, headers=post_headers)
                    if r_data.status_code != 200:
                        logger.warning(f"Error fetching data page {page} for {master_name}: {r_data.status_code}")
                        break

                    data_json = r_data.json()
                    raw_rows = data_json.get("data", [])
                    if not raw_rows:
                        break

                    for row in raw_rows:
                        # row is a list of {"Key": "...", "Value": "..."}
                        flat_row = {}
                        if isinstance(row, list):
                            for kv in row:
                                if isinstance(kv, dict) and "Key" in kv:
                                    flat_row[kv["Key"]] = kv.get("Value")
                        elif isinstance(row, dict):
                            flat_row = row
                        if flat_row:
                            records.append(flat_row)

                    total_count = data_json.get("TotalCount", len(records))
                    if len(records) >= total_count or len(records) >= max_records:
                        break

                    page += 1

            except Exception as e:
                logger.error(f"Network error scraping {master_name}: {e}")

        return records

    async def sync_master(self, raw_master_name: str, max_records: int = 500) -> ScraperRun:
        master_key = raw_master_name.upper().strip()
        canonical_master = MASTER_MAP.get(master_key, master_key)

        async with AsyncSessionLocal() as session:
            run = ScraperRun(
                master_name=canonical_master,
                status="running",
                rows_fetched=0,
                rows_upserted=0,
                started_at=datetime.utcnow()
            )
            session.add(run)
            await session.commit()
            run_id = run.id

        try:
            logger.info(f"Starting sync for master: {canonical_master} (limit: {max_records})")
            rows = await self.fetch_master_rows(canonical_master, max_records=max_records)

            if not rows:
                logger.info(f"No online rows returned for {canonical_master}. Checking offline fallback...")
                upserted = await self._apply_offline_fallback(canonical_master)
                status = "completed"
                err_log = "Online fetch empty or timed out; loaded offline fallback dataset."
                fetched_count = upserted
            else:
                fetched_count = len(rows)
                upserted = await self._process_and_upsert(canonical_master, rows)
                status = "completed"
                err_log = None

        except Exception as ex:
            logger.exception(f"Sync failed for {canonical_master}: {ex}")
            status = "failed"
            fetched_count = 0
            upserted = 0
            err_log = str(ex)

        async with AsyncSessionLocal() as session:
            stmt = (
                update(ScraperRun)
                .where(ScraperRun.id == run_id)
                .values(
                    status=status,
                    rows_fetched=fetched_count,
                    rows_upserted=upserted,
                    error_logs=err_log,
                    completed_at=datetime.utcnow()
                )
            )
            await session.execute(stmt)
            await session.commit()
            res = await session.execute(select(ScraperRun).where(ScraperRun.id == run_id))
            updated_run = res.scalar_one()

        return updated_run

    async def _process_and_upsert(self, master: str, raw_rows: List[Dict[str, Any]]) -> int:
        if not raw_rows:
            return 0

        # Use Polars for cleaning & deduplication
        df = pl.DataFrame(raw_rows)
        logger.info(f"Polars DataFrame shape for {master}: {df.shape}")

        async with AsyncSessionLocal() as session:
            if master == "DIVISION RAJASTHAN":
                return await self._upsert_divisions(df, session)
            elif master == "DISTRICT RAJASTHAN":
                return await self._upsert_districts(df, session)
            elif master == "SUB-DIVISION":
                return await self._upsert_subdivisions(df, session)
            elif master in ("TEHSIL RAJASTHAN", "SUB-TEHSIL", "BLOCK RAJASTHAN"):
                return await self._upsert_tehsils_blocks(master, df, session)
            elif master == "GRAM PANCHAYAT RAJASTHAN":
                return await self._upsert_gram_panchayats(df, session)
            elif master == "PATWAR RAJASTHAN":
                return await self._upsert_patwar_villages(df, session)
            elif master == "VILLAGE RAJASTHAN":
                return await self._upsert_villages(df, session)
            elif master == "URBAN LOCAL BODY(CITY) RAJASTHAN":
                return await self._upsert_ulbs(df, session)
            elif master == "WARD RAJASTHAN":
                return await self._upsert_urban_wards(df, session)
            elif master == "PINCODE RAJASTHAN":
                return await self._upsert_pincodes(df, session)
            else:
                logger.warning(f"No custom upsert handler for {master}. Storing raw metadata.")
                return 0

    async def _upsert_divisions(self, df: pl.DataFrame, session) -> int:
        records = []
        for row in df.to_dicts():
            r_id = row.get("DIVISION_ID")
            if not r_id:
                continue
            name_en = row.get("DIVISION_ENG") or f"Division {r_id}"
            records.append({
                "rajmaster_id": int(r_id),
                "state_id": 1,
                "code": str(row.get("DIVISION_CODE") or ""),
                "name_en": str(name_en).strip(),
                "name_hi": str(row.get("DIVISION_MANGAL") or "").strip() or None,
                "divisional_commissioner": f"Divisional Commissioner, {name_en}",
                "lgd_code": int(r_id),
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        if not records:
            return 0

        stmt = insert(Division).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rajmaster_id"],
            set_={
                "code": stmt.excluded.code,
                "name_en": stmt.excluded.name_en,
                "name_hi": stmt.excluded.name_hi,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": datetime.utcnow()
            }
        )
        await session.execute(stmt)
        await session.commit()
        return len(records)

    async def _upsert_districts(self, df: pl.DataFrame, session) -> int:
        records = []
        # Get existing divisions for division_id foreign key mapping
        div_res = await session.execute(select(Division.id, Division.rajmaster_id))
        div_map = {r[1]: r[0] for r in div_res.fetchall() if r[1]}

        for row in df.to_dicts():
            r_id = row.get("DISTRICT_ID")
            if not r_id:
                continue
            name_en = row.get("DISTRICT_ENG") or f"District {r_id}"
            div_raj_id = row.get("DIVISION_ID")
            mapped_div_id = div_map.get(div_raj_id)

            records.append({
                "rajmaster_id": int(r_id),
                "division_id": mapped_div_id,
                "code": str(row.get("DISTRICT_CODE") or ""),
                "name_en": str(name_en).strip(),
                "name_hi": str(row.get("DISTRICT_MANGAL") or "").strip() or None,
                "collectorate_details": f"District Collectorate, {name_en}",
                "zila_parishad_details": f"Zila Parishad {name_en}",
                "zila_pramukh": f"Zila Pramukh, {name_en}",
                "lgd_code": int(row.get("LG_CODE")) if row.get("LG_CODE") else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        if not records:
            return 0

        stmt = insert(District).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rajmaster_id"],
            set_={
                "division_id": stmt.excluded.division_id,
                "code": stmt.excluded.code,
                "name_en": stmt.excluded.name_en,
                "name_hi": stmt.excluded.name_hi,
                "lgd_code": stmt.excluded.lgd_code,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": datetime.utcnow()
            }
        )
        await session.execute(stmt)
        await session.commit()
        return len(records)

    async def _upsert_subdivisions(self, df: pl.DataFrame, session) -> int:
        records = []
        dist_res = await session.execute(select(District.id, District.rajmaster_id))
        dist_map = {r[1]: r[0] for r in dist_res.fetchall() if r[1]}

        for row in df.to_dicts():
            r_id = row.get("SUB_DIVISION_ID")
            if not r_id:
                continue
            dist_raj_id = row.get("DISTRICT_ID")
            mapped_dist_id = dist_map.get(dist_raj_id, 1)
            name_en = row.get("SUB_DIVISION_ENG") or f"Sub-Division {r_id}"

            records.append({
                "rajmaster_id": int(r_id),
                "district_id": mapped_dist_id,
                "code": str(row.get("SUB_DIVISION_CODE") or ""),
                "name_en": str(name_en).strip(),
                "name_hi": str(row.get("SUB_DIVISION_MANGAL") or "").strip() or None,
                "sdm_jurisdiction": f"SDM Office {name_en}",
                "lgd_code": int(row.get("LG_CODE")) if row.get("LG_CODE") else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        if not records:
            return 0

        stmt = insert(SubDivision).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rajmaster_id"],
            set_={
                "district_id": stmt.excluded.district_id,
                "name_en": stmt.excluded.name_en,
                "name_hi": stmt.excluded.name_hi,
                "sdm_jurisdiction": stmt.excluded.sdm_jurisdiction,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": datetime.utcnow()
            }
        )
        await session.execute(stmt)
        await session.commit()
        return len(records)

    async def _upsert_tehsils_blocks(self, master: str, df: pl.DataFrame, session) -> int:
        records = []
        dist_res = await session.execute(select(District.id, District.rajmaster_id))
        dist_map = {r[1]: r[0] for r in dist_res.fetchall() if r[1]}

        entity_type = "Tehsil"
        if "BLOCK" in master:
            entity_type = "Panchayat Samiti / Block"
        elif "SUB-TEHSIL" in master:
            entity_type = "Sub-Tehsil"

        for row in df.to_dicts():
            r_id = row.get("TEHSIL_ID") or row.get("BLOCK_ID") or row.get("SUB_TEHSIL_ID")
            if not r_id:
                continue
            dist_raj_id = row.get("DISTRICT_ID")
            mapped_dist_id = dist_map.get(dist_raj_id)
            name_en = row.get("TEHSIL_ENG") or row.get("BLOCK_ENG") or row.get("SUB_TEHSIL_ENG") or f"Entity {r_id}"
            name_hi = row.get("TEHSIL_MANGAL") or row.get("BLOCK_MANGAL") or row.get("SUB_TEHSIL_MANGAL")
            code = row.get("TEHSIL_CODE") or row.get("BLOCK_CODE") or ""
            lg_code = row.get("BLOCK_LGCODE") or row.get("LG_CODE")

            records.append({
                "rajmaster_id": int(r_id),
                "district_id": mapped_dist_id,
                "code": str(code),
                "name_en": str(name_en).strip(),
                "name_hi": str(name_hi).strip() if name_hi else None,
                "entity_type": entity_type,
                "tehsildar_details": f"Tehsildar {name_en}" if "Tehsil" in entity_type else None,
                "bdo_details": f"BDO {name_en}" if "Block" in entity_type else None,
                "lgd_code": int(lg_code) if lg_code else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        count = 0
        for r in records:
            # Check existing by rajmaster_id and entity_type
            res = await session.execute(
                select(TehsilBlock).where(
                    TehsilBlock.rajmaster_id == r["rajmaster_id"],
                    TehsilBlock.entity_type == r["entity_type"]
                )
            )
            existing = res.scalar_one_or_none()
            if existing:
                existing.name_en = r["name_en"]
                existing.name_hi = r["name_hi"]
                existing.district_id = r["district_id"]
                existing.metadata_json = r["metadata_json"]
            else:
                session.add(TehsilBlock(**r))
            count += 1

        await session.commit()
        return count

    async def _upsert_gram_panchayats(self, df: pl.DataFrame, session) -> int:
        records = []
        dist_res = await session.execute(select(District.id, District.rajmaster_id))
        dist_map = {r[1]: r[0] for r in dist_res.fetchall() if r[1]}

        tb_res = await session.execute(select(TehsilBlock.id, TehsilBlock.rajmaster_id))
        tb_map = {r[1]: r[0] for r in tb_res.fetchall() if r[1]}

        for row in df.to_dicts():
            r_id = row.get("GP_ID")
            if not r_id:
                continue
            dist_id = dist_map.get(row.get("DISTRICT_ID"))
            tb_id = tb_map.get(row.get("BLOCK_ID"))
            name_en = row.get("GP_ENG") or f"GP {r_id}"

            records.append({
                "rajmaster_id": int(r_id),
                "district_id": dist_id,
                "tehsil_block_id": tb_id,
                "code": str(row.get("GP_CODE") or ""),
                "name_en": str(name_en).strip(),
                "name_hi": str(row.get("GP_MANGAL") or "").strip() or None,
                "sarpanch": f"Sarpanch, {name_en}",
                "lgd_code": int(row.get("GP_LGCODE")) if row.get("GP_LGCODE") else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        if not records:
            return 0

        stmt = insert(GramPanchayat).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rajmaster_id"],
            set_={
                "name_en": stmt.excluded.name_en,
                "name_hi": stmt.excluded.name_hi,
                "district_id": stmt.excluded.district_id,
                "tehsil_block_id": stmt.excluded.tehsil_block_id,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": datetime.utcnow()
            }
        )
        await session.execute(stmt)
        await session.commit()
        return len(records)

    async def _upsert_patwar_villages(self, df: pl.DataFrame, session) -> int:
        dist_res = await session.execute(select(District.id, District.rajmaster_id))
        dist_map = {r[1]: r[0] for r in dist_res.fetchall() if r[1]}

        tb_res = await session.execute(select(TehsilBlock.id, TehsilBlock.rajmaster_id))
        tb_map = {r[1]: r[0] for r in tb_res.fetchall() if r[1]}

        count = 0
        for row in df.to_dicts():
            patwar_id = row.get("PATWAR_ID")
            if not patwar_id:
                continue
            name_en = row.get("PATWAR_ENG") or f"Patwar {patwar_id}"
            name_hi = row.get("PATWAR_MANGAL")
            dist_id = dist_map.get(row.get("DISTRICT_ID"))
            tb_id = tb_map.get(row.get("TEHSIL_ID"))

            v_obj = Village(
                rajmaster_id=int(patwar_id) + 100000,
                district_id=dist_id,
                tehsil_block_id=tb_id,
                code=str(row.get("PATWAR_CODE") or ""),
                name_en=str(name_en).strip(),
                name_hi=str(name_hi).strip() if name_hi else None,
                patwar_circle=f"{name_en} Patwar Circle",
                patwari=f"Patwari {name_en}",
                metadata_json={"source": "rajmaster_patwar", "raw": row}
            )
            session.add(v_obj)
            count += 1
            if count >= 300: # Limit sample batch
                break

        await session.commit()
        return count

    async def _upsert_villages(self, df: pl.DataFrame, session) -> int:
        records = []
        dist_res = await session.execute(select(District.id, District.rajmaster_id))
        dist_map = {r[1]: r[0] for r in dist_res.fetchall() if r[1]}

        tb_res = await session.execute(select(TehsilBlock.id, TehsilBlock.rajmaster_id))
        tb_map = {r[1]: r[0] for r in tb_res.fetchall() if r[1]}

        gp_res = await session.execute(select(GramPanchayat.id, GramPanchayat.rajmaster_id))
        gp_map = {r[1]: r[0] for r in gp_res.fetchall() if r[1]}

        for row in df.to_dicts():
            r_id = row.get("VILLAGE_ID")
            if not r_id:
                continue
            dist_id = dist_map.get(row.get("DISTRICT_ID"))
            tb_id = tb_map.get(row.get("TEHSIL_ID")) or tb_map.get(row.get("BLOCK_ID"))
            gp_id = gp_map.get(row.get("GP_ID"))
            name_en = row.get("VILLAGE_ENG") or f"Village {r_id}"

            records.append({
                "rajmaster_id": int(r_id),
                "district_id": dist_id,
                "tehsil_block_id": tb_id,
                "gram_panchayat_id": gp_id,
                "code": str(row.get("VILLAGE_CODE") or ""),
                "name_en": str(name_en).strip(),
                "name_hi": str(row.get("VILLAGE_MANGAL") or "").strip() or None,
                "patwar_circle": row.get("PATWAR_ENG"),
                "patwari": f"Patwari {row.get('PATWAR_ENG') or name_en}",
                "lgd_code": int(row.get("VILLAGE_LGCODE")) if row.get("VILLAGE_LGCODE") else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        if not records:
            return 0

        stmt = insert(Village).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rajmaster_id"],
            set_={
                "name_en": stmt.excluded.name_en,
                "name_hi": stmt.excluded.name_hi,
                "district_id": stmt.excluded.district_id,
                "tehsil_block_id": stmt.excluded.tehsil_block_id,
                "gram_panchayat_id": stmt.excluded.gram_panchayat_id,
                "lgd_code": stmt.excluded.lgd_code,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": datetime.utcnow()
            }
        )
        await session.execute(stmt)
        await session.commit()
        return len(records)

    async def _upsert_ulbs(self, df: pl.DataFrame, session) -> int:
        records = []
        dist_res = await session.execute(select(District.id, District.rajmaster_id))
        dist_map = {r[1]: r[0] for r in dist_res.fetchall() if r[1]}

        for row in df.to_dicts():
            r_id = row.get("CITY_ID")
            if not r_id:
                continue
            dist_id = dist_map.get(row.get("DISTRICT_ID"), 1)
            name_en = row.get("CITY_ENG") or f"ULB {r_id}"
            city_type = row.get("CITY_TYPE_ENG") or "Nagar Palika"

            records.append({
                "rajmaster_id": int(r_id),
                "district_id": dist_id,
                "code": str(row.get("CITY_CODE") or ""),
                "name_en": str(name_en).strip(),
                "name_hi": str(row.get("CITY_MANGAL") or "").strip() or None,
                "ulb_type": str(city_type).strip(),
                "city_name": str(name_en).strip(),
                "lgd_code": int(row.get("LG_CODE")) if row.get("LG_CODE") else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        if not records:
            return 0

        stmt = insert(UrbanLocalBody).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["rajmaster_id"],
            set_={
                "name_en": stmt.excluded.name_en,
                "name_hi": stmt.excluded.name_hi,
                "district_id": stmt.excluded.district_id,
                "ulb_type": stmt.excluded.ulb_type,
                "lgd_code": stmt.excluded.lgd_code,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": datetime.utcnow()
            }
        )
        await session.execute(stmt)
        await session.commit()
        return len(records)

    async def _upsert_urban_wards(self, df: pl.DataFrame, session) -> int:
        records = []
        ulb_res = await session.execute(select(UrbanLocalBody.id, UrbanLocalBody.rajmaster_id))
        ulb_map = {r[1]: r[0] for r in ulb_res.fetchall() if r[1]}

        for row in df.to_dicts():
            r_id = row.get("WARD_ID")
            if not r_id:
                continue
            ulb_id = ulb_map.get(row.get("CITY_ID"), 1)
            ward_num = row.get("WARD_ENG") or str(row.get("WARD_CODE") or f"Ward {r_id}")

            records.append({
                "rajmaster_id": int(r_id),
                "ulb_id": ulb_id,
                "ward_number": str(ward_num).strip(),
                "name_en": str(row.get("WARD_ENG") or "").strip() or None,
                "name_hi": str(row.get("WARD_MANGAL") or "").strip() or None,
                "councillor_parshad": f"Parshad {ward_num}",
                "lgd_code": int(row.get("LG_CODE")) if row.get("LG_CODE") else None,
                "metadata_json": {"source": "rajmaster_scraper", "raw": row}
            })

        count = 0
        for r in records[:300]:
            uw_obj = UrbanWard(**r)
            session.add(uw_obj)
            count += 1
        await session.commit()
        return count

    async def _upsert_pincodes(self, df: pl.DataFrame, session) -> int:
        records_by_pincode = {}

        # 1. Build lookup for districts
        dist_res = await session.execute(select(District.id, District.name_en, District.division_id))
        dist_map = {}
        for d_id, d_name, div_id in dist_res.fetchall():
            d_norm = d_name.lower().strip()
            dist_map[d_norm] = (d_id, div_id)
            dist_map[d_norm.replace("sri ", "").strip()] = (d_id, div_id)
            dist_map[d_norm.replace("-", " ").strip()] = (d_id, div_id)

        # 2. Build lookup for tehsils/blocks
        tb_res = await session.execute(select(TehsilBlock.id, TehsilBlock.name_en, TehsilBlock.district_id))
        tb_map = {}
        for tb_id, tb_name, d_id in tb_res.fetchall():
            tb_norm = tb_name.lower().strip()
            tb_map[(tb_norm, d_id)] = tb_id
            tb_map[tb_norm] = tb_id

        # 3. Process rows from Polars DataFrame
        for row in df.to_dicts():
            raw_pin = str(row.get("PINCODE") or "").strip()
            if not raw_pin or len(raw_pin) < 6:
                continue

            pin = raw_pin[:6]
            if not pin.isdigit():
                continue

            dist_name = str(row.get("DISTRICT_NAME") or "").lower().strip()
            subdist_name = str(row.get("SUBDIST_NAME") or "").strip()
            loc_name = str(row.get("LOCALITY_NAME") or "").strip()
            office_name = str(row.get("OFFICE_NAME") or "").strip()

            dist_info = dist_map.get(dist_name)
            if not dist_info:
                for k, v in dist_map.items():
                    if k in dist_name or dist_name in k:
                        dist_info = v
                        break

            d_id = dist_info[0] if dist_info else 1
            div_id = dist_info[1] if dist_info else 4
            tb_id = tb_map.get((subdist_name.lower(), d_id)) or tb_map.get(subdist_name.lower())

            place_label = loc_name or office_name or subdist_name or dist_name.title()

            if pin not in records_by_pincode:
                records_by_pincode[pin] = {
                    "pincode": pin,
                    "city_or_village": place_label,
                    "district_id": d_id,
                    "division_id": div_id,
                    "tehsil_block_id": tb_id,
                    "localities": [loc_name] if loc_name else [],
                    "offices": [office_name] if office_name else [],
                    "lgd_code": int(row.get("PINCODE_ID")) if row.get("PINCODE_ID") else None,
                    "raw": row
                }
            else:
                existing = records_by_pincode[pin]
                if loc_name and loc_name not in existing["localities"]:
                    existing["localities"].append(loc_name)
                if office_name and office_name not in existing["offices"]:
                    existing["offices"].append(office_name)
                if len(existing["city_or_village"].split(",")) < 3 and place_label not in existing["city_or_village"]:
                    existing["city_or_village"] += f", {place_label}"

        # 4. Upsert into database
        count = 0
        for pin, data in records_by_pincode.items():
            meta = {
                "source": "rajmaster_pincode_scraper",
                "offices": data["offices"][:10],
                "localities": data["localities"][:15],
                "raw_pincode_id": data.get("lgd_code")
            }
            stmt = insert(Pincode).values(
                pincode=data["pincode"],
                city_or_village=data["city_or_village"][:150],
                district_id=data["district_id"],
                division_id=data["division_id"],
                tehsil_block_id=data["tehsil_block_id"],
                metadata_json=meta
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["pincode"],
                set_={
                    "city_or_village": stmt.excluded.city_or_village,
                    "district_id": stmt.excluded.district_id,
                    "division_id": stmt.excluded.division_id,
                    "tehsil_block_id": stmt.excluded.tehsil_block_id,
                    "metadata_json": stmt.excluded.metadata_json,
                    "updated_at": func.now()
                }
            )
            await session.execute(stmt)
            count += 1

        await session.commit()
        return count

    async def _apply_offline_fallback(self, master: str) -> int:
        """Graceful offline fallback seed data in case portal has SSL/network downtime"""
        logger.info(f"Applying offline fallback dataset for {master}...")
        async with AsyncSessionLocal() as session:
            if "DIVISION" in master:
                for d in FALLBACK_DIVISIONS:
                    res = await session.execute(select(Division).filter_by(rajmaster_id=d["rajmaster_id"]))
                    if not res.scalar_one_or_none():
                        session.add(Division(
                            state_id=1,
                            rajmaster_id=d["rajmaster_id"],
                            code=d["code"],
                            name_en=d["name_en"],
                            name_hi=d["name_hi"],
                            divisional_commissioner=d["divisional_commissioner"],
                            lgd_code=d["lgd_code"],
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_DIVISIONS)

            elif "DISTRICT" in master:
                for dst in FALLBACK_DISTRICTS:
                    res = await session.execute(select(District).filter_by(rajmaster_id=dst["rajmaster_id"]))
                    if not res.scalar_one_or_none():
                        session.add(District(
                            division_id=dst["division_id"],
                            rajmaster_id=dst["rajmaster_id"],
                            code=dst["code"],
                            name_en=dst["name_en"],
                            name_hi=dst["name_hi"],
                            collectorate_details=f"District Collectorate, {dst['name_en']}",
                            zila_parishad_details=f"Zila Parishad {dst['name_en']}",
                            zila_pramukh=dst["zila_pramukh"],
                            lgd_code=dst["lgd_code"],
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_DISTRICTS)

            elif "SUB-DIVISION" in master or "SUB DIVISION" in master:
                for sd in FALLBACK_SUBDIVISIONS:
                    res = await session.execute(select(SubDivision).filter_by(rajmaster_id=sd["rajmaster_id"]))
                    if not res.scalar_one_or_none():
                        session.add(SubDivision(
                            district_id=sd["district_id"],
                            rajmaster_id=sd["rajmaster_id"],
                            code=sd["code"],
                            name_en=sd["name_en"],
                            name_hi=sd["name_hi"],
                            sdm_jurisdiction=sd["sdm_jurisdiction"],
                            lgd_code=sd["lgd_code"],
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_SUBDIVISIONS)

            elif "TEHSIL" in master or "BLOCK" in master:
                for tb in FALLBACK_TEHSILS_BLOCKS:
                    res = await session.execute(select(TehsilBlock).filter_by(rajmaster_id=tb["rajmaster_id"]))
                    if not res.scalar_one_or_none():
                        session.add(TehsilBlock(
                            district_id=tb["district_id"],
                            sub_division_id=tb["sub_division_id"],
                            rajmaster_id=tb["rajmaster_id"],
                            code=tb["code"],
                            name_en=tb["name_en"],
                            name_hi=tb["name_hi"],
                            entity_type=tb["entity_type"],
                            tehsildar_details=tb.get("tehsildar_details"),
                            bdo_details=tb.get("bdo_details"),
                            lgd_code=tb["lgd_code"],
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_TEHSILS_BLOCKS)

            elif "VILLAGE" in master:
                for v in FALLBACK_VILLAGES:
                    res = await session.execute(select(Village).filter_by(rajmaster_id=v["rajmaster_id"]))
                    if not res.scalar_one_or_none():
                        session.add(Village(
                            district_id=v["district_id"],
                            tehsil_block_id=v["tehsil_block_id"],
                            gram_panchayat_id=v["gram_panchayat_id"],
                            rajmaster_id=v["rajmaster_id"],
                            code=v["code"],
                            name_en=v["name_en"],
                            name_hi=v["name_hi"],
                            patwar_circle=v["patwar_circle"],
                            patwari=v["patwari"],
                            pincode=v["pincode"],
                            lgd_code=v["lgd_code"],
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_VILLAGES)

            elif "URBAN" in master or "ULB" in master:
                for u in FALLBACK_ULBS:
                    res = await session.execute(select(UrbanLocalBody).filter_by(rajmaster_id=u["rajmaster_id"]))
                    if not res.scalar_one_or_none():
                        session.add(UrbanLocalBody(
                            district_id=u["district_id"],
                            rajmaster_id=u["rajmaster_id"],
                            code=u["code"],
                            name_en=u["name_en"],
                            name_hi=u["name_hi"],
                            ulb_type=u["ulb_type"],
                            city_name=u["city_name"],
                            pincode=u["pincode"],
                            lgd_code=u["lgd_code"],
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_ULBS)

            elif "PINCODE" in master:
                for p in FALLBACK_PINCODES:
                    res = await session.execute(select(Pincode).filter_by(pincode=p["pincode"], city_or_village=p["city_or_village"]))
                    if not res.scalar_one_or_none():
                        session.add(Pincode(
                            pincode=p["pincode"],
                            city_or_village=p["city_or_village"],
                            district_id=p.get("district_id"),
                            division_id=p.get("division_id"),
                            tehsil_block_id=p.get("tehsil_block_id"),
                            ulb_id=p.get("ulb_id"),
                            gram_panchayat_id=p.get("gram_panchayat_id"),
                            metadata_json={"source": "offline_fallback"}
                        ))
                await session.commit()
                return len(FALLBACK_PINCODES)

        return 0

async def sync_all_masters(limit_per_master: int = 200):
    scraper = RajMasterScraper()
    target_masters = [
        "DIVISION RAJASTHAN",
        "DISTRICT RAJASTHAN",
        "SUB-DIVISION",
        "TEHSIL RAJASTHAN",
        "BLOCK RAJASTHAN",
        "GRAM PANCHAYAT RAJASTHAN",
        "URBAN LOCAL BODY(CITY) RAJASTHAN",
        "WARD RAJASTHAN",
        "VILLAGE RAJASTHAN",
    ]

    print(f"=== Starting RajMaster ETL Sync ({len(target_masters)} targets, limit: {limit_per_master}) ===")
    results = []
    for m in target_masters:
        print(f"-> Syncing: {m}...")
        run = await scraper.sync_master(m, max_records=limit_per_master)
        print(f"   [{run.status.upper()}] Fetched: {run.rows_fetched}, Upserted: {run.rows_upserted}")
        results.append(run)
    
    await async_engine.dispose()
    print("=== All RajMaster sync runs completed ===")
    return results

def main():
    parser = argparse.ArgumentParser(description="Rajasthan RajMaster Scraper & ETL Pipeline")
    parser.add_argument("--all", action="store_true", help="Sync all standard masters")
    parser.add_argument("--master", type=str, help="Specific master name to sync")
    parser.add_argument("--limit", type=int, default=200, help="Max rows to fetch per master")
    args = parser.parse_args()

    if args.all or not args.master:
        asyncio.run(sync_all_masters(limit_per_master=args.limit))
    else:
        scraper = RajMasterScraper()
        run = asyncio.run(scraper.sync_master(args.master, max_records=args.limit))
        print(f"Run {run.id} [{run.status}]: fetched {run.rows_fetched}, upserted {run.rows_upserted}")

if __name__ == "__main__":
    main()
