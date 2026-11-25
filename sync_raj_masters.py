"""
=============================================================================
RAJ MASTERS PRODUCTION ASYNC ETL SYNCHRONIZATION ENGINE
Government of Rajasthan Portal (https://rajmasters.rajasthan.gov.in/)
Ingestion & Grounding Layer for AI LLM Agent
=============================================================================
"""

import os
import sys
import json
import time
import asyncio
import logging
import argparse
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, unquote

import httpx
import asyncpg
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)
from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# LOGGING CONFIGURATION
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("sync_raj_masters")

# ---------------------------------------------------------------------------
# CONFIGURATION & SETTINGS
# ---------------------------------------------------------------------------
class SyncSettings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    rajmasters_base_url: str = Field(default="https://rajmasters.rajasthan.gov.in", alias="RAJMASTERS_BASE_URL")
    rajmasters_client_id: Optional[str] = Field(default=None, alias="RAJMASTERS_CLIENT_ID")
    rajmasters_api_key: Optional[str] = Field(default=None, alias="RAJMASTERS_API_KEY")
    postgres_dsn: str = Field(
        default="postgresql://postgres:Admin%40123@127.0.0.1:5432/finalairajmaster",
        alias="POSTGRES_DSN"
    )
    embedding_api_url: str = Field(
        default="http://localhost:11434/api/embeddings",
        alias="EMBEDDING_API_URL"
    )
    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")
    batch_chunk_size: int = Field(default=2000, alias="BATCH_CHUNK_SIZE")
    http_timeout_seconds: float = Field(default=45.0, alias="HTTP_TIMEOUT_SECONDS")

settings = SyncSettings()

# ---------------------------------------------------------------------------
# UNIVERSAL FIELD EXTRACTOR FOR DIVERSE PORTAL KEY NAMING
# ---------------------------------------------------------------------------
def get_val(row: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return row[c]
        for k, v in row.items():
            if k.upper() == c.upper() and v not in (None, ""):
                return v
    return None

def extract_standard_fields(row: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    p = prefix.upper()
    r_id = get_val(row, [
        f"{p}_ID", f"{p}ID", f"{p.replace('_', '')}_ID", "ID", "CODE_ID", "ROW_ID"
    ])
    if r_id is None:
        for k, v in row.items():
            if k.upper().endswith("_ID") and v not in (None, ""):
                r_id = v
                break

    name_en = get_val(row, [
        f"{p}_ENG", f"{p}_NAME_ENG", f"{p}_NAME", f"{p}_ENGLISH",
        "NAME_ENG", "NAME", "TITLE_ENG", "LOCALITY_NAME", "OFFICE_NAME", "CITY_NAME_ENG"
    ]) or (f"Record {r_id}" if r_id else "Unnamed Record")

    name_hi = get_val(row, [
        f"{p}_MANGAL", f"{p}_HND", f"{p}_NAME_HND", f"{p}_HINDI",
        "NAME_HND", "MANGAL", "HINDI", "OFFICE_NAME"
    ])

    code = get_val(row, [f"{p}_CODE", "CODE", f"{p.replace('_', '')}_CODE", "C_CODE"])
    lgd = get_val(row, ["LGD_CODE", "LGDCODE", "CENSUS_CODE", "LGD"])

    return {
        "raj_master_id": r_id,
        "name_en": str(name_en).strip(),
        "name_hi": str(name_hi).strip() if name_hi else None,
        "code": str(code).strip() if code else None,
        "lgd_code": str(lgd).strip() if lgd else None
    }

# ---------------------------------------------------------------------------
# MASTER METADATA & EXACT 57 PORTAL MASTERS MAPPING
# ---------------------------------------------------------------------------
MASTER_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ----------------- TIER 1: Independent Lookups & Top Boundaries -----------------
    "DIVISION RAJASTHAN": {"table": "divisions", "tier": 1, "expected": 10, "prefix": "DIVISION"},
    "URBAN LOCAL BODY(CITY) TYPE": {"table": "ulb_types", "tier": 1, "expected": 4, "prefix": "CITYTYPE"},
    "URBAN LOCAL BODY(CITY) CATEGORY": {"table": "ulb_categories", "tier": 1, "expected": 4, "prefix": "CATEGORY"},
    "POLICE RANGE AND COMMISSIONERATE": {"table": "police_ranges", "tier": 1, "expected": 10, "prefix": "RANGE"},
    "PARLIAMENT CONSTITUENCY RAJASTHAN": {"table": "parliament_constituencies", "tier": 1, "expected": 25, "prefix": "PC"},
    "CASTE CATEGORY": {"table": "caste_categories", "tier": 1, "expected": 14, "prefix": "CATEGORY"},
    "ADMIN DEPARTMENT": {"table": "admin_departments", "tier": 1, "expected": 70, "prefix": "DEPT"},
    "ORGANIZATION CATEGORY": {"table": "organization_categories", "tier": 1, "expected": 8, "prefix": "ORG_CAT"},
    "OFFICE LEVEL": {"table": "office_levels", "tier": 1, "expected": 36, "prefix": "LEVEL"},
    "SERVICE": {"table": "services", "tier": 1, "expected": 6, "prefix": "SERVICE"},
    "SECTOR": {"table": "asset_sectors", "tier": 1, "expected": 30, "prefix": "SECTOR"},

    # 20 Reference Small Masters -> generic_lookups
    "ADDRESS TYPE": {"table": "generic_lookups", "tier": 1, "expected": 6, "lookup_type": "ADDRESS_TYPE"},
    "DISABILITY CATEGORY": {"table": "generic_lookups", "tier": 1, "expected": 23, "lookup_type": "DISABILITY_CATEGORY"},
    "DOCUMENT TYPE": {"table": "generic_lookups", "tier": 1, "expected": 33, "lookup_type": "DOCUMENT_TYPE"},
    "EMPLOYEE CATEGORY": {"table": "generic_lookups", "tier": 1, "expected": 2, "lookup_type": "EMPLOYEE_CATEGORY"},
    "EMPLOYEE POSTED IN": {"table": "generic_lookups", "tier": 1, "expected": 4, "lookup_type": "EMPLOYEE_POSTED_IN"},
    "EMPLOYEE STATUS": {"table": "generic_lookups", "tier": 1, "expected": 3, "lookup_type": "EMPLOYEE_STATUS"},
    "EMPLOYEE SUB STATUS": {"table": "generic_lookups", "tier": 1, "expected": 12, "lookup_type": "EMPLOYEE_SUB_STATUS"},
    "EMPLOYEE TYPE": {"table": "generic_lookups", "tier": 1, "expected": 7, "lookup_type": "EMPLOYEE_TYPE"},
    "GENDER": {"table": "generic_lookups", "tier": 1, "expected": 3, "lookup_type": "GENDER"},
    "LAND CATEGORY": {"table": "generic_lookups", "tier": 1, "expected": 2, "lookup_type": "LAND_CATEGORY"},
    "MARITAL STATUS": {"table": "generic_lookups", "tier": 1, "expected": 7, "lookup_type": "MARITAL_STATUS"},
    "OCCUPATION": {"table": "generic_lookups", "tier": 1, "expected": 12, "lookup_type": "OCCUPATION"},
    "PAY COMMISSION": {"table": "generic_lookups", "tier": 1, "expected": 5, "lookup_type": "PAY_COMMISSION"},
    "POSTED REASON": {"table": "generic_lookups", "tier": 1, "expected": 7, "lookup_type": "POSTED_REASON"},
    "POSTING TYPE": {"table": "generic_lookups", "tier": 1, "expected": 4, "lookup_type": "POSTING_TYPE"},
    "RATION CARD TYPE": {"table": "generic_lookups", "tier": 1, "expected": 6, "lookup_type": "RATION_CARD_TYPE"},
    "RELIGION": {"table": "generic_lookups", "tier": 1, "expected": 10, "lookup_type": "RELIGION"},
    "RESIDENTIAL STATUS": {"table": "generic_lookups", "tier": 1, "expected": 3, "lookup_type": "RESIDENTIAL_STATUS"},
    "STATE INDIA": {"table": "generic_lookups", "tier": 1, "expected": 37, "lookup_type": "STATE_INDIA"},
    "TITLE": {"table": "generic_lookups", "tier": 1, "expected": 7, "lookup_type": "TITLE"},

    # ----------------- TIER 2: Districts, Banks, Ranges & Secondary Groups ----------
    "DISTRICT RAJASTHAN": {"table": "districts", "tier": 2, "expected": 50, "prefix": "DISTRICT"},
    "BANK INDIA": {"table": "banks", "tier": 2, "expected": 389, "prefix": "BANK"},
    "POLICE DISTRICT": {"table": "police_districts", "tier": 2, "expected": 52, "prefix": "PD"},
    "ORGANIZATION": {"table": "organizations", "tier": 2, "expected": 449, "prefix": "ORG"},
    "DESIGNATION": {"table": "designations", "tier": 2, "expected": 959, "prefix": "DESIGNATION"},
    "CASTE": {"table": "castes", "tier": 2, "expected": 538, "prefix": "CASTE"},
    "ASSET CATEGORY": {"table": "asset_categories", "tier": 2, "expected": 45, "prefix": "CATEGORY"},
    "PROJECTED 2017 DISTRICT POPULATION": {"table": "des_district_population_2017", "tier": 2, "expected": 33, "prefix": "DISTRICT"},

    # ----------------- TIER 3: Sub-Divisions, Blocks, Assembly Constituencies -------
    "SUB-DIVISION": {"table": "sub_divisions", "tier": 3, "expected": 328, "prefix": "SUB_DIVISION"},
    "BLOCK RAJASTHAN": {"table": "blocks", "tier": 3, "expected": 458, "prefix": "BLOCK"},
    "POLICE CIRCLE": {"table": "police_circles", "tier": 3, "expected": 259, "prefix": "CIRCLE"},
    "ASSEMBLY CONSTITUENCY RAJASTHAN": {"table": "assembly_constituencies", "tier": 3, "expected": 200, "prefix": "AC"},
    "ASSET SUBCATEGORY": {"table": "asset_subcategories", "tier": 3, "expected": 744, "prefix": "SUBCATEGORY"},
    "BLOCK WISE POPULATION": {"table": "des_block_population", "tier": 3, "expected": 295, "prefix": "BLOCK"},

    # ----------------- TIER 4: Tehsils, Gram Panchayats, ULBs, Police Stations ------
    "TEHSIL RAJASTHAN": {"table": "tehsils", "tier": 4, "expected": 426, "prefix": "TEHSIL"},
    "GRAM PANCHAYAT RAJASTHAN": {"table": "gram_panchayats", "tier": 4, "expected": 14505, "prefix": "GP"},
    "URBAN LOCAL BODY(CITY) RAJASTHAN": {"table": "ulbs", "tier": 4, "expected": 309, "prefix": "CITY"},
    "POLICE STATION": {"table": "police_stations", "tier": 4, "expected": 957, "prefix": "PS"},
    "BANK BRANCH INDIA": {"table": "bank_branches", "tier": 4, "expected": 197112, "prefix": "BRANCH"},
    "URBAN LOCAL BODY(CITY) WISE POPULATION": {"table": "des_ulb_population", "tier": 4, "expected": 189, "prefix": "ULB"},

    # ----------------- TIER 5: Sub-Tehsils, ILR Circles, Patwar Circles, Wards ------
    "SUB-TEHSIL": {"table": "sub_tehsils", "tier": 5, "expected": 290, "prefix": "SUBTEHSIL"},
    "ILR RAJASTHAN": {"table": "ilr_circles", "tier": 5, "expected": 2815, "prefix": "ILR"},
    "PATWAR RAJASTHAN": {"table": "patwar_circles", "tier": 5, "expected": 11336, "prefix": "PATWAR"},
    "WARD RAJASTHAN": {"table": "wards", "tier": 5, "expected": 10245, "prefix": "WARD"},

    # ----------------- TIER 6: Villages, Village Population, Pincodes ---------------
    "VILLAGE RAJASTHAN": {"table": "villages", "tier": 6, "expected": 51892, "prefix": "VILLAGE"},
    "VILLAGE WISE POPULATION": {"table": "des_village_population", "tier": 6, "expected": 44787, "prefix": "VILLAGE"},
    "PINCODE RAJASTHAN": {"table": "pincodes", "tier": 6, "expected": 53967, "prefix": "PINCODE"}
}

# ---------------------------------------------------------------------------
# RESILIENT HTTP CLIENT WITH TENACITY EXPONENTIAL RETRY
# ---------------------------------------------------------------------------
class RajMasterApiClient:
    def __init__(self, base_url: str, timeout: float = 45.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session_cookies: Dict[str, str] = {}

    @retry(
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1.5, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def fetch_master_page(
        self,
        client: httpx.AsyncClient,
        master_name: str,
        page: int,
        page_size: int = 500
    ) -> Tuple[List[Dict[str, Any]], int]:
        url_list = f"{self.base_url}/Home/List?master={master_name}"
        url_data = f"{self.base_url}/Home/ListData"

        get_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        if page == 1 or not self.session_cookies:
            r_init = await client.get(url_list, headers=get_headers, timeout=self.timeout)
            if r_init.status_code == 200:
                self.session_cookies.update(client.cookies)

        payload = {
            "master": master_name,
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

        post_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Referer": url_list
        }

        if settings.rajmasters_api_key:
            post_headers["Authorization"] = f"Bearer {settings.rajmasters_api_key}"

        r_data = await client.post(url_data, json=payload, headers=post_headers, timeout=self.timeout)
        r_data.raise_for_status()

        data_json = r_data.json()
        raw_rows = data_json.get("data", [])
        total_count = int(data_json.get("TotalCount") or len(raw_rows))

        parsed_records = []
        for item in raw_rows:
            if isinstance(item, list):
                row_dict = {kv["Key"]: kv.get("Value") for kv in item if isinstance(kv, dict) and "Key" in kv}
                parsed_records.append(row_dict)
            elif isinstance(item, dict):
                parsed_records.append(item)

        return parsed_records, total_count

# ---------------------------------------------------------------------------
# POSTGRESQL ASYNC BATCH UPSERT PIPELINE (IDEMPOTENT & CHUNKED)
# ---------------------------------------------------------------------------
class RajMastersETLPipeline:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.api_client = RajMasterApiClient(settings.rajmasters_base_url, settings.http_timeout_seconds)
        self.pool: Optional[asyncpg.Pool] = None

    async def init_pool(self):
        parsed = urlparse(self.dsn)
        user = unquote(parsed.username or "postgres")
        password = unquote(parsed.password or "Admin@123")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5432
        database = parsed.path.lstrip("/") or "finalairajmaster"

        self.pool = await asyncpg.create_pool(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database,
            min_size=5,
            max_size=20,
            command_timeout=120
        )
        logger.info(f"Connected to PostgreSQL database '{database}' on {host}:{port}")

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("Closed PostgreSQL connection pool.")

    async def log_audit_start(self, master_name: str, tier: int, expected: int, mode: str) -> int:
        async with self.pool.acquire() as conn:
            run_id = await conn.fetchval(
                """
                INSERT INTO raj_masters.sync_audit_log 
                (master_name, tier_level, expected_count, status, mode, created_at)
                VALUES ($1, $2, $3, 'STARTED', $4, NOW())
                RETURNING id;
                """,
                master_name, tier, expected, mode
            )
            return run_id

    async def log_audit_finish(
        self,
        run_id: int,
        fetched: int,
        upserted: int,
        status: str,
        duration: float,
        error_msg: Optional[str] = None
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE raj_masters.sync_audit_log
                SET fetched_count = $1,
                    upserted_count = $2,
                    status = $3,
                    duration_seconds = $4,
                    error_message = $5,
                    completed_at = NOW()
                WHERE id = $6;
                """,
                fetched, upserted, status, duration, error_msg, run_id
            )

    async def upsert_generic_lookups(self, lookup_type: str, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, lookup_type)
            raj_id = std["raj_master_id"]
            if raj_id is None:
                continue
            payload = json.dumps(r)
            batch_tuples.append((
                lookup_type, str(raj_id), std["code"], std["name_en"], std["name_hi"], payload
            ))

        if not batch_tuples:
            return 0

        query = """
            INSERT INTO raj_masters.generic_lookups
            (master_type, raj_master_id, code, name_en, name_hi, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (master_type, raj_master_id) DO UPDATE SET
                code = EXCLUDED.code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, batch_tuples)
        return len(batch_tuples)

    async def upsert_generic_records(
        self,
        table_name: str,
        records: List[Dict[str, Any]],
        meta: Dict[str, Any]
    ) -> int:
        if not records:
            return 0

        prefix = meta.get("prefix", "")
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, prefix)
            raj_id = std["raj_master_id"]
            if raj_id is None:
                continue

            try:
                raj_id_val = int(raj_id)
            except (ValueError, TypeError):
                continue

            payload = json.dumps(r)
            batch_tuples.append((
                raj_id_val, std["code"], std["lgd_code"], std["name_en"], std["name_hi"], payload
            ))

        if not batch_tuples:
            return 0

        upsert_query = f"""
            INSERT INTO raj_masters.{table_name} 
            (raj_master_id, code, lgd_code, name_en, name_hi, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """

        total_upserted = 0
        chunk_size = settings.batch_chunk_size

        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), chunk_size):
                chunk = batch_tuples[i : i + chunk_size]
                await conn.executemany(upsert_query, chunk)
                total_upserted += len(chunk)

        return total_upserted

    async def upsert_districts(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "DISTRICT")
            r_id = std["raj_master_id"]
            if not r_id:
                continue
            div_id = get_val(r, ["DIVISION_ID", "DIV_ID"])
            collectorate = f"District Collectorate, {std['name_en']}"
            zila_pramukh = f"Zila Pramukh, {std['name_en']}"
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(div_id) if div_id else None, std["code"], std["lgd_code"],
                std["name_en"], std["name_hi"], collectorate, zila_pramukh, payload
            ))

        query = """
            INSERT INTO raj_masters.districts
            (raj_master_id, division_id, code, lgd_code, name_en, name_hi, collectorate_details, zila_pramukh, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                division_id = EXCLUDED.division_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                collectorate_details = EXCLUDED.collectorate_details,
                zila_pramukh = EXCLUDED.zila_pramukh,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, batch_tuples)
        return len(batch_tuples)

    async def upsert_subdivisions(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "SUB_DIVISION")
            r_id = std["raj_master_id"]
            d_id = get_val(r, ["DISTRICT_ID", "DIST_ID"])
            if not r_id or not d_id:
                continue
            sdm_jurisdiction = f"SDM Office, {std['name_en']}"
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(d_id), std["code"], std["lgd_code"],
                std["name_en"], std["name_hi"], sdm_jurisdiction, payload
            ))

        query = """
            INSERT INTO raj_masters.sub_divisions
            (raj_master_id, district_id, code, lgd_code, name_en, name_hi, sdm_jurisdiction, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                sdm_jurisdiction = EXCLUDED.sdm_jurisdiction,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def upsert_tehsils(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "TEHSIL")
            r_id = std["raj_master_id"]
            d_id = get_val(r, ["DISTRICT_ID", "DIST_ID"])
            if not r_id or not d_id:
                continue
            sd_id = get_val(r, ["SUB_DIVISION_ID", "SUBDIV_ID"])
            tehsildar = f"Tehsildar Office, {std['name_en']}"
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(d_id), int(sd_id) if sd_id else None,
                std["code"], std["lgd_code"], std["name_en"], std["name_hi"], tehsildar, payload
            ))

        query = """
            INSERT INTO raj_masters.tehsils
            (raj_master_id, district_id, sub_division_id, code, lgd_code, name_en, name_hi, tehsildar_details, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                sub_division_id = EXCLUDED.sub_division_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                tehsildar_details = EXCLUDED.tehsildar_details,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def upsert_blocks(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "BLOCK")
            r_id = std["raj_master_id"]
            d_id = get_val(r, ["DISTRICT_ID", "DIST_ID"])
            if not r_id or not d_id:
                continue
            bdo = f"BDO / Panchayat Samiti {std['name_en']}"
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(d_id), std["code"], std["lgd_code"],
                std["name_en"], std["name_hi"], bdo, payload
            ))

        query = """
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
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, batch_tuples)
        return len(batch_tuples)

    async def upsert_gram_panchayats(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "GP")
            r_id = std["raj_master_id"]
            b_id = get_val(r, ["BLOCK_ID", "BLOCKID"])
            if not r_id or not b_id:
                continue
            d_id = get_val(r, ["DISTRICT_ID", "DIST_ID"])
            sarpanch = f"Sarpanch, GP {std['name_en']}"
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(b_id), int(d_id) if d_id else None,
                std["code"], std["lgd_code"], std["name_en"], std["name_hi"], sarpanch, payload
            ))

        query = """
            INSERT INTO raj_masters.gram_panchayats
            (raj_master_id, block_id, district_id, code, lgd_code, name_en, name_hi, sarpanch_name, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                block_id = EXCLUDED.block_id,
                district_id = EXCLUDED.district_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                sarpanch_name = EXCLUDED.sarpanch_name,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def upsert_ulbs(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "CITY")
            r_id = std["raj_master_id"]
            d_id = get_val(r, ["DISTRICT_ID", "DIST_ID"])
            if not r_id or not d_id:
                continue
            city = get_val(r, ["CITY_NAME", "CITY_NAME_ENG"]) or std["name_en"]
            t_id = get_val(r, ["CITYTYPE_ID", "CITY_TYPE_ID"])
            c_id = get_val(r, ["CATEGORY_ID"])
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(d_id), int(t_id) if t_id else None, int(c_id) if c_id else None,
                std["code"], std["lgd_code"], std["name_en"], std["name_hi"], str(city).strip(), payload
            ))

        query = """
            INSERT INTO raj_masters.ulbs
            (raj_master_id, district_id, ulb_type_id, ulb_category_id, code, lgd_code, name_en, name_hi, city_name, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                district_id = EXCLUDED.district_id,
                ulb_type_id = EXCLUDED.ulb_type_id,
                ulb_category_id = EXCLUDED.ulb_category_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                city_name = EXCLUDED.city_name,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, batch_tuples)
        return len(batch_tuples)

    async def upsert_wards(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "WARD")
            r_id = std["raj_master_id"]
            ulb_id = get_val(r, ["CITY_ID", "ULB_ID"])
            if not r_id or not ulb_id:
                continue
            ward_num = str(get_val(r, ["WARD_NO", "WARD_NUMBER"]) or r_id).strip()
            councillor = f"Parshad / Councillor Ward {ward_num}"
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(ulb_id), ward_num, std["code"], std["name_en"], std["name_hi"], councillor, payload
            ))

        query = """
            INSERT INTO raj_masters.wards
            (raj_master_id, ulb_id, ward_number, code, name_en, name_hi, councillor_parshad, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                ulb_id = EXCLUDED.ulb_id,
                ward_number = EXCLUDED.ward_number,
                code = EXCLUDED.code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                councillor_parshad = EXCLUDED.councillor_parshad,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def upsert_villages(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "VILLAGE")
            r_id = std["raj_master_id"]
            if not r_id:
                continue
            patwar_id = get_val(r, ["PATWAR_ID", "PATWARI_ID"])
            tehsil_id = get_val(r, ["TEHSIL_ID"])
            dist_id = get_val(r, ["DISTRICT_ID", "DIST_ID"])
            gp_id = get_val(r, ["GP_ID", "GRAM_PANCHAYAT_ID"])
            pincode = get_val(r, ["PINCODE", "PIN_CODE"])
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(patwar_id) if patwar_id else None,
                int(tehsil_id) if tehsil_id else None, int(dist_id) if dist_id else None,
                int(gp_id) if gp_id else None, std["code"], std["lgd_code"],
                std["name_en"], std["name_hi"], str(pincode).strip() if pincode else None, payload
            ))

        query = """
            INSERT INTO raj_masters.villages
            (raj_master_id, patwar_circle_id, tehsil_id, district_id, gram_panchayat_id, code, lgd_code, name_en, name_hi, pincode, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                patwar_circle_id = EXCLUDED.patwar_circle_id,
                tehsil_id = EXCLUDED.tehsil_id,
                district_id = EXCLUDED.district_id,
                gram_panchayat_id = EXCLUDED.gram_panchayat_id,
                code = EXCLUDED.code,
                lgd_code = EXCLUDED.lgd_code,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                pincode = EXCLUDED.pincode,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def upsert_bank_branches(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            std = extract_standard_fields(r, "BRANCH")
            r_id = std["raj_master_id"]
            bank_id = get_val(r, ["BANK_ID"])
            if not r_id or not bank_id:
                continue
            ifsc = str(get_val(r, ["IFSC_CODE", "IFSC"]) or "").strip()
            micr = get_val(r, ["MICR_CODE", "MICR"])
            dist_name = get_val(r, ["DISTRICT_NAME", "DIST_NAME"])
            pincode = get_val(r, ["PINCODE", "PIN_CODE"])
            payload = json.dumps(r)

            batch_tuples.append((
                int(r_id), int(bank_id), ifsc, str(micr).strip() if micr else None,
                std["name_en"], std["name_en"], std["name_hi"],
                str(dist_name).strip() if dist_name else None,
                str(pincode).strip() if pincode else None, payload
            ))

        query = """
            INSERT INTO raj_masters.bank_branches
            (raj_master_id, bank_id, ifsc_code, micr_code, branch_name, name_en, name_hi, district_name, pincode, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NOW())
            ON CONFLICT (raj_master_id) DO UPDATE SET
                bank_id = EXCLUDED.bank_id,
                ifsc_code = EXCLUDED.ifsc_code,
                micr_code = EXCLUDED.micr_code,
                branch_name = EXCLUDED.branch_name,
                name_en = EXCLUDED.name_en,
                name_hi = EXCLUDED.name_hi,
                district_name = EXCLUDED.district_name,
                pincode = EXCLUDED.pincode,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def upsert_pincodes(self, records: List[Dict[str, Any]]) -> int:
        batch_tuples = []
        for r in records:
            raw_pin = str(get_val(r, ["PINCODE", "PIN_CODE"]) or "").strip()
            if not raw_pin or len(raw_pin) < 6:
                continue
            pincode = raw_pin[:6]
            if not pincode.isdigit():
                continue

            loc_name = str(get_val(r, ["LOCALITY_NAME", "LOCALITY"]) or "").strip()
            office_name = str(get_val(r, ["OFFICE_NAME", "OFFICE"]) or loc_name or "General Post Office").strip()
            dist_name = str(get_val(r, ["DISTRICT_NAME", "DISTRICT"]) or "").strip()
            subdist_name = str(get_val(r, ["SUBDIST_NAME", "SUBDIST"]) or "").strip()
            r_id = get_val(r, ["PINCODE_ID", "ID"])
            payload = json.dumps(r)

            batch_tuples.append((
                pincode, office_name, loc_name, dist_name, subdist_name,
                int(r_id) if r_id else None, payload
            ))

        query = """
            INSERT INTO raj_masters.pincodes
            (pincode, office_name, locality_name, district_name, subdist_name, raj_master_id, raw_payload, synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW())
            ON CONFLICT (pincode, office_name) DO UPDATE SET
                locality_name = EXCLUDED.locality_name,
                district_name = EXCLUDED.district_name,
                subdist_name = EXCLUDED.subdist_name,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW();
        """
        async with self.pool.acquire() as conn:
            for i in range(0, len(batch_tuples), settings.batch_chunk_size):
                chunk = batch_tuples[i : i + settings.batch_chunk_size]
                await conn.executemany(query, chunk)
        return len(batch_tuples)

    async def sync_single_master(self, master_name: str, mode: str = "full") -> int:
        meta = MASTER_REGISTRY.get(master_name)
        if not meta:
            logger.warning(f"Master '{master_name}' not recognized in MASTER_REGISTRY.")
            return 0

        tier = meta["tier"]
        table = meta["table"]
        expected = meta["expected"]
        t0 = time.time()

        run_id = await self.log_audit_start(master_name, tier, expected, mode)
        logger.info(f"[{master_name}] Starting sync (Tier {tier}, expected {expected} records)...")

        fetched_records = []
        upserted_count = 0
        error_msg = None
        status = "COMPLETED"

        try:
            async with httpx.AsyncClient(verify=False, timeout=settings.http_timeout_seconds) as client:
                page = 1
                page_size = 500
                total_to_fetch = expected if mode == "full" else min(expected, 2000)

                while len(fetched_records) < total_to_fetch:
                    page_rows, total_portal_count = await self.api_client.fetch_master_page(
                        client, master_name, page=page, page_size=page_size
                    )
                    if not page_rows:
                        break
                    fetched_records.extend(page_rows)
                    if len(fetched_records) >= total_portal_count or len(page_rows) < page_size:
                        break
                    page += 1

            logger.info(f"[{master_name}] Fetched {len(fetched_records)} raw records from portal.")

            if table == "generic_lookups":
                lookup_type = meta.get("lookup_type", master_name)
                upserted_count = await self.upsert_generic_lookups(lookup_type, fetched_records)
            elif table == "districts":
                upserted_count = await self.upsert_districts(fetched_records)
            elif table == "sub_divisions":
                upserted_count = await self.upsert_subdivisions(fetched_records)
            elif table == "tehsils":
                upserted_count = await self.upsert_tehsils(fetched_records)
            elif table == "blocks":
                upserted_count = await self.upsert_blocks(fetched_records)
            elif table == "gram_panchayats":
                upserted_count = await self.upsert_gram_panchayats(fetched_records)
            elif table == "ulbs":
                upserted_count = await self.upsert_ulbs(fetched_records)
            elif table == "wards":
                upserted_count = await self.upsert_wards(fetched_records)
            elif table == "villages":
                upserted_count = await self.upsert_villages(fetched_records)
            elif table == "bank_branches":
                upserted_count = await self.upsert_bank_branches(fetched_records)
            elif table == "pincodes":
                upserted_count = await self.upsert_pincodes(fetched_records)
            else:
                upserted_count = await self.upsert_generic_records(table, fetched_records, meta)

            logger.info(f"[{master_name}] Upserted {upserted_count} records into raj_masters.{table}.")

        except Exception as ex:
            logger.exception(f"[{master_name}] Sync failed: {ex}")
            status = "FAILED"
            error_msg = str(ex)

        duration = round(time.time() - t0, 2)
        await self.log_audit_finish(run_id, len(fetched_records), upserted_count, status, duration, error_msg)
        return upserted_count

    async def run_full_topological_sync(self, mode: str = "full"):
        logger.info("=================================================================")
        logger.info(f"STARTING TOPOLOGICAL ETL SYNC FOR 57 RAJ MASTERS (MODE: {mode.upper()})")
        logger.info("=================================================================")

        by_tier: Dict[int, List[str]] = {}
        for m_name, meta in MASTER_REGISTRY.items():
            t = meta["tier"]
            by_tier.setdefault(t, []).append(m_name)

        total_synced = 0
        overall_start = time.time()

        for tier in sorted(by_tier.keys()):
            logger.info(f"\n--- EXECUTING TIER {tier} MASTERS ({len(by_tier[tier])} datasets) ---")
            for master_name in by_tier[tier]:
                count = await self.sync_single_master(master_name, mode=mode)
                total_synced += count

        duration = round(time.time() - overall_start, 2)
        logger.info("=================================================================")
        logger.info(f"TOPOLOGICAL SYNC COMPLETE: {total_synced} total records in {duration}s")
        logger.info("=================================================================")

    async def generate_entity_embeddings(self, batch_size: int = 100):
        logger.info("\n--- STARTING AI ENTITY EMBEDDING GENERATION ---")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT 
                    v.raj_master_id::text,
                    v.lgd_code,
                    v.name_en,
                    v.name_hi,
                    t.name_en AS tehsil,
                    d.name_en AS district,
                    div.name_en AS division,
                    gp.name_en AS gram_panchayat,
                    v.pincode
                FROM raj_masters.villages v
                LEFT JOIN raj_masters.tehsils t ON v.tehsil_id = t.raj_master_id
                LEFT JOIN raj_masters.districts d ON v.district_id = d.raj_master_id
                LEFT JOIN raj_masters.divisions div ON d.division_id = div.raj_master_id
                LEFT JOIN raj_masters.gram_panchayats gp ON v.gram_panchayat_id = gp.raj_master_id
                LIMIT 5000;
                """
            )
            logger.info(f"Building canonical paths for {len(rows)} villages...")

            tuples_to_embed = []
            for r in rows:
                c_path_en = (
                    f"Village: {r['name_en']} | GP: {r['gram_panchayat'] or 'N/A'} | "
                    f"Tehsil: {r['tehsil'] or 'N/A'} | District: {r['district'] or 'N/A'} | "
                    f"Division: {r['division'] or 'N/A'} | Pincode: {r['pincode'] or 'N/A'}"
                )
                c_path_hi = f"गाँव: {r['name_hi'] or r['name_en']} | तहसील: {r['tehsil'] or ''} | जिला: {r['district'] or ''}"
                meta_json = json.dumps({
                    "pincode": r["pincode"],
                    "district": r["district"],
                    "tehsil": r["tehsil"],
                    "gp": r["gram_panchayat"]
                })
                tuples_to_embed.append((
                    "VILLAGE", r["raj_master_id"], r["lgd_code"], r["name_en"],
                    r["name_hi"], c_path_en, c_path_hi, meta_json
                ))

            upsert_entity_sql = """
                INSERT INTO raj_masters.entity_embeddings
                (entity_type, raj_master_id, lgd_code, name_en, name_hi, canonical_path_en, canonical_path_hi, metadata_json, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
                ON CONFLICT (entity_type, raj_master_id) DO UPDATE SET
                    canonical_path_en = EXCLUDED.canonical_path_en,
                    canonical_path_hi = EXCLUDED.canonical_path_hi,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = NOW();
            """
            for i in range(0, len(tuples_to_embed), batch_size):
                chunk = tuples_to_embed[i : i + batch_size]
                await conn.executemany(upsert_entity_sql, chunk)

            logger.info(f"Upserted {len(tuples_to_embed)} canonical entity strings for lexical and vector resolution.")

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        settings.embedding_api_url,
                        json={"model": settings.embedding_model, "prompt": "Rajasthan State Secretariat"}
                    )
                    if resp.status_code == 200:
                        logger.info(f"Ollama embedding model '{settings.embedding_model}' is active and responding.")
                    else:
                        logger.warning(f"Ollama returned status {resp.status_code}. Hybrid lexical search will serve queries.")
            except Exception as e:
                logger.warning(f"Ollama embeddings endpoint not reachable ({e}). Trigram lexical indexing active.")

# ---------------------------------------------------------------------------
# CLI ENTRYPOINT
# ---------------------------------------------------------------------------
async def async_main():
    parser = argparse.ArgumentParser(description="RAJ MASTERS ETL Synchronization Pipeline & AI Entity Resolution")
    parser.add_argument("--mode", choices=["full", "delta"], default="full", help="Synchronization mode: full or delta")
    parser.add_argument("--only", type=str, default=None, help="Sync only a specific master name (e.g. 'PINCODE RAJASTHAN')")
    parser.add_argument("--generate-embeddings", action="store_true", help="Generate composite canonical paths & embeddings")

    args = parser.parse_args()

    pipeline = RajMastersETLPipeline(settings.postgres_dsn)
    await pipeline.init_pool()

    try:
        if args.only:
            matched_key = None
            for k in MASTER_REGISTRY.keys():
                if args.only.upper() in k:
                    matched_key = k
                    break
            if matched_key:
                await pipeline.sync_single_master(matched_key, mode=args.mode)
            else:
                logger.error(f"No master matched query '{args.only}'.")
        else:
            await pipeline.run_full_topological_sync(mode=args.mode)

        if args.generate_embeddings:
            await pipeline.generate_entity_embeddings()

    finally:
        await pipeline.close()

if __name__ == "__main__":
    asyncio.run(async_main())
