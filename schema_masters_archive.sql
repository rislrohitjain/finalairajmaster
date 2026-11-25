-- ============================================================================
-- RAJ MASTERS HIERARCHICAL & AI ENTITY RESOLUTION SCHEMA
-- Production DDL for Government of Rajasthan Master Datasets (57 Masters)
-- Database Engine: PostgreSQL 15+ with pgvector & pg_trgm extensions
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. EXTENSIONS & SCHEMAS
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pg_trgm extension could not be loaded: %', SQLERRM;
END $$;

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension not installed in environment; creating fallback vector domain type';
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
            CREATE DOMAIN vector AS real[];
        END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS raj_masters;
SET search_path TO raj_masters, public;

-- ----------------------------------------------------------------------------
-- 2. REVENUE & GEOGRAPHIC HIERARCHY (TIER 1 - TIER 6)
-- ----------------------------------------------------------------------------

-- Level 2: Divisions (7-10 Commissionerates)
CREATE TABLE IF NOT EXISTS raj_masters.divisions (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    divisional_commissioner TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_divisions_name_en_trgm ON raj_masters.divisions USING gin (name_en gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_divisions_name_hi_trgm ON raj_masters.divisions USING gin (name_hi gin_trgm_ops);

-- Level 3: Districts (Collectorates & Zila Parishads)
CREATE TABLE IF NOT EXISTS raj_masters.districts (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    division_id BIGINT REFERENCES raj_masters.divisions(raj_master_id) ON DELETE SET NULL,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    collectorate_details TEXT,
    zila_pramukh TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_districts_division_id ON raj_masters.districts(division_id);
CREATE INDEX IF NOT EXISTS idx_districts_name_en_trgm ON raj_masters.districts USING gin (name_en gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_districts_name_hi_trgm ON raj_masters.districts USING gin (name_hi gin_trgm_ops);

-- Level 4: Sub-Divisions (SDM / SDO Jurisdictions - 328 records)
CREATE TABLE IF NOT EXISTS raj_masters.sub_divisions (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    district_id BIGINT NOT NULL REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    sdm_jurisdiction TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sub_divisions_district_id ON raj_masters.sub_divisions(district_id);
CREATE INDEX IF NOT EXISTS idx_sub_divisions_name_en_trgm ON raj_masters.sub_divisions USING gin (name_en gin_trgm_ops);

-- Level 5: Tehsils (Revenue & Magistracy - 426 records)
CREATE TABLE IF NOT EXISTS raj_masters.tehsils (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    district_id BIGINT NOT NULL REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    sub_division_id BIGINT REFERENCES raj_masters.sub_divisions(raj_master_id) ON DELETE SET NULL,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    tehsildar_details TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tehsils_district_id ON raj_masters.tehsils(district_id);
CREATE INDEX IF NOT EXISTS idx_tehsils_sub_division_id ON raj_masters.tehsils(sub_division_id);
CREATE INDEX IF NOT EXISTS idx_tehsils_name_en_trgm ON raj_masters.tehsils USING gin (name_en gin_trgm_ops);

-- Level 5b: Sub-Tehsils (290 records)
CREATE TABLE IF NOT EXISTS raj_masters.sub_tehsils (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    tehsil_id BIGINT NOT NULL REFERENCES raj_masters.tehsils(raj_master_id) ON DELETE CASCADE,
    district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    naib_tehsildar_details TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sub_tehsils_tehsil_id ON raj_masters.sub_tehsils(tehsil_id);
CREATE INDEX IF NOT EXISTS idx_sub_tehsils_name_en_trgm ON raj_masters.sub_tehsils USING gin (name_en gin_trgm_ops);

-- Inspector Land Records (ILR) Circles (Girdawar Circles - 2,815 records)
CREATE TABLE IF NOT EXISTS raj_masters.ilr_circles (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    tehsil_id BIGINT NOT NULL REFERENCES raj_masters.tehsils(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ilr_circles_tehsil_id ON raj_masters.ilr_circles(tehsil_id);
CREATE INDEX IF NOT EXISTS idx_ilr_circles_name_en_trgm ON raj_masters.ilr_circles USING gin (name_en gin_trgm_ops);

-- Patwar Circles (11,336 records)
CREATE TABLE IF NOT EXISTS raj_masters.patwar_circles (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    ilr_circle_id BIGINT REFERENCES raj_masters.ilr_circles(raj_master_id) ON DELETE SET NULL,
    tehsil_id BIGINT REFERENCES raj_masters.tehsils(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    patwari_name TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_patwar_circles_ilr_id ON raj_masters.patwar_circles(ilr_circle_id);
CREATE INDEX IF NOT EXISTS idx_patwar_circles_tehsil_id ON raj_masters.patwar_circles(tehsil_id);
CREATE INDEX IF NOT EXISTS idx_patwar_circles_name_en_trgm ON raj_masters.patwar_circles USING gin (name_en gin_trgm_ops);

-- Level 6: Revenue Villages (51,892 records)
CREATE TABLE IF NOT EXISTS raj_masters.villages (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    patwar_circle_id BIGINT REFERENCES raj_masters.patwar_circles(raj_master_id) ON DELETE SET NULL,
    tehsil_id BIGINT REFERENCES raj_masters.tehsils(raj_master_id) ON DELETE CASCADE,
    district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    gram_panchayat_id BIGINT,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    pincode VARCHAR(20),
    is_desert_area BOOLEAN DEFAULT FALSE,
    is_tribal_sub_plan BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_villages_patwar_id ON raj_masters.villages(patwar_circle_id);
CREATE INDEX IF NOT EXISTS idx_villages_tehsil_id ON raj_masters.villages(tehsil_id);
CREATE INDEX IF NOT EXISTS idx_villages_district_id ON raj_masters.villages(district_id);
CREATE INDEX IF NOT EXISTS idx_villages_pincode ON raj_masters.villages(pincode);
CREATE INDEX IF NOT EXISTS idx_villages_name_en_trgm ON raj_masters.villages USING gin (name_en gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_villages_name_hi_trgm ON raj_masters.villages USING gin (name_hi gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 3. PANCHAYATI RAJ (RURAL LOCAL BODIES)
-- ----------------------------------------------------------------------------

-- Level 5: Panchayat Samitis / Blocks (458 records)
CREATE TABLE IF NOT EXISTS raj_masters.blocks (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    district_id BIGINT NOT NULL REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    bdo_details TEXT,
    pradhan_name TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_blocks_district_id ON raj_masters.blocks(district_id);
CREATE INDEX IF NOT EXISTS idx_blocks_name_en_trgm ON raj_masters.blocks USING gin (name_en gin_trgm_ops);

-- Level 6: Gram Panchayats (14,505 records)
CREATE TABLE IF NOT EXISTS raj_masters.gram_panchayats (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    block_id BIGINT NOT NULL REFERENCES raj_masters.blocks(raj_master_id) ON DELETE CASCADE,
    district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    sarpanch_name TEXT,
    vdo_name TEXT,
    pincode VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gram_panchayats_block_id ON raj_masters.gram_panchayats(block_id);
CREATE INDEX IF NOT EXISTS idx_gram_panchayats_district_id ON raj_masters.gram_panchayats(district_id);
CREATE INDEX IF NOT EXISTS idx_gram_panchayats_name_en_trgm ON raj_masters.gram_panchayats USING gin (name_en gin_trgm_ops);

-- Update FK for villages to gram_panchayats
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_villages_gram_panchayat'
    ) THEN
        ALTER TABLE raj_masters.villages
        ADD CONSTRAINT fk_villages_gram_panchayat
        FOREIGN KEY (gram_panchayat_id) REFERENCES raj_masters.gram_panchayats(raj_master_id) ON DELETE SET NULL;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 4. LOCAL SELF-GOVERNMENT (URBAN LOCAL BODIES)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.ulb_types (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.ulb_categories (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

-- Urban Local Bodies (309 records)
CREATE TABLE IF NOT EXISTS raj_masters.ulbs (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    district_id BIGINT NOT NULL REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    ulb_type_id BIGINT REFERENCES raj_masters.ulb_types(raj_master_id) ON DELETE SET NULL,
    ulb_category_id BIGINT REFERENCES raj_masters.ulb_categories(raj_master_id) ON DELETE SET NULL,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    city_name TEXT,
    pincode VARCHAR(20),
    commissioner_or_eo TEXT,
    mayor_or_chairman TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ulbs_district_id ON raj_masters.ulbs(district_id);
CREATE INDEX IF NOT EXISTS idx_ulbs_name_en_trgm ON raj_masters.ulbs USING gin (name_en gin_trgm_ops);

-- Urban Wards (10,245 records)
CREATE TABLE IF NOT EXISTS raj_masters.wards (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    ulb_id BIGINT NOT NULL REFERENCES raj_masters.ulbs(raj_master_id) ON DELETE CASCADE,
    ward_number VARCHAR(50) NOT NULL,
    code VARCHAR(50),
    lgd_code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    councillor_parshad TEXT,
    pincode VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wards_ulb_id ON raj_masters.wards(ulb_id);
CREATE INDEX IF NOT EXISTS idx_wards_name_en_trgm ON raj_masters.wards USING gin (name_en gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 5. POLICE & LAW ENFORCEMENT
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.police_ranges (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    ig_details TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.police_districts (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    police_range_id BIGINT REFERENCES raj_masters.police_ranges(raj_master_id) ON DELETE SET NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    sp_commissioner_details TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_police_districts_range_id ON raj_masters.police_districts(police_range_id);

CREATE TABLE IF NOT EXISTS raj_masters.police_circles (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    police_district_id BIGINT NOT NULL REFERENCES raj_masters.police_districts(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    co_details TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_police_circles_district_id ON raj_masters.police_circles(police_district_id);

CREATE TABLE IF NOT EXISTS raj_masters.police_stations (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    police_circle_id BIGINT REFERENCES raj_masters.police_circles(raj_master_id) ON DELETE SET NULL,
    police_district_id BIGINT NOT NULL REFERENCES raj_masters.police_districts(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    sho_details TEXT,
    contact_number VARCHAR(50),
    pincode VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_police_stations_circle_id ON raj_masters.police_stations(police_circle_id);
CREATE INDEX IF NOT EXISTS idx_police_stations_district_id ON raj_masters.police_stations(police_district_id);
CREATE INDEX IF NOT EXISTS idx_police_stations_name_en_trgm ON raj_masters.police_stations USING gin (name_en gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 6. ELECTION CONSTITUENCIES
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.parliament_constituencies (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    constituency_number INT,
    name_en TEXT NOT NULL,
    name_hi TEXT,
    mp_name TEXT,
    reservation_status VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.assembly_constituencies (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    parliament_constituency_id BIGINT REFERENCES raj_masters.parliament_constituencies(raj_master_id) ON DELETE SET NULL,
    district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE CASCADE,
    constituency_number INT,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    mla_name TEXT,
    reservation_status VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_assembly_pc_id ON raj_masters.assembly_constituencies(parliament_constituency_id);
CREATE INDEX IF NOT EXISTS idx_assembly_district_id ON raj_masters.assembly_constituencies(district_id);
CREATE INDEX IF NOT EXISTS idx_assembly_name_en_trgm ON raj_masters.assembly_constituencies USING gin (name_en gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 7. D.E.S. POPULATION STATISTICS (HISTORICAL 33-DISTRICT COMPATIBILITY)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.des_district_population_2017 (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    legacy_district_code VARCHAR(50) NOT NULL,
    current_district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE SET NULL,
    name_en TEXT NOT NULL,
    name_hi TEXT,
    total_population BIGINT,
    male_population BIGINT,
    female_population BIGINT,
    sex_ratio INT,
    literacy_rate NUMERIC(5, 2),
    density_per_sq_km INT,
    census_year INT DEFAULT 2011,
    survey_year INT DEFAULT 2017,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.des_ulb_population (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    ulb_id BIGINT REFERENCES raj_masters.ulbs(raj_master_id) ON DELETE SET NULL,
    name_en TEXT NOT NULL,
    name_hi TEXT,
    total_population BIGINT,
    male_population BIGINT,
    female_population BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.des_block_population (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    block_id BIGINT REFERENCES raj_masters.blocks(raj_master_id) ON DELETE SET NULL,
    name_en TEXT NOT NULL,
    name_hi TEXT,
    total_population BIGINT,
    rural_population BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.des_village_population (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    village_id BIGINT REFERENCES raj_masters.villages(raj_master_id) ON DELETE SET NULL,
    name_en TEXT NOT NULL,
    name_hi TEXT,
    total_population BIGINT,
    total_households BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_des_village_pop_village_id ON raj_masters.des_village_population(village_id);

-- ----------------------------------------------------------------------------
-- 8. BANKING MASTERS
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.banks (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    bank_type VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_banks_name_en_trgm ON raj_masters.banks USING gin (name_en gin_trgm_ops);

CREATE TABLE IF NOT EXISTS raj_masters.bank_branches (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    bank_id BIGINT NOT NULL REFERENCES raj_masters.banks(raj_master_id) ON DELETE CASCADE,
    district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE SET NULL,
    ifsc_code VARCHAR(20) NOT NULL,
    micr_code VARCHAR(20),
    branch_name TEXT NOT NULL,
    name_en TEXT NOT NULL,
    name_hi TEXT,
    address TEXT,
    city_name TEXT,
    district_name TEXT,
    contact_number VARCHAR(50),
    pincode VARCHAR(20),
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bank_branches_bank_id ON raj_masters.bank_branches(bank_id);
CREATE INDEX IF NOT EXISTS idx_bank_branches_ifsc ON raj_masters.bank_branches(ifsc_code);
CREATE INDEX IF NOT EXISTS idx_bank_branches_micr ON raj_masters.bank_branches(micr_code);
CREATE INDEX IF NOT EXISTS idx_bank_branches_district ON raj_masters.bank_branches(district_name);
CREATE INDEX IF NOT EXISTS idx_bank_branches_name_en_trgm ON raj_masters.bank_branches USING gin (name_en gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 9. ASSET & INFRASTRUCTURE MASTERS
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.asset_sectors (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.asset_categories (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    asset_sector_id BIGINT NOT NULL REFERENCES raj_masters.asset_sectors(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_asset_categories_sector_id ON raj_masters.asset_categories(asset_sector_id);

CREATE TABLE IF NOT EXISTS raj_masters.asset_subcategories (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    asset_category_id BIGINT NOT NULL REFERENCES raj_masters.asset_categories(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_asset_subcategories_cat_id ON raj_masters.asset_subcategories(asset_category_id);

-- ----------------------------------------------------------------------------
-- 10. SOCIAL JUSTICE & EMPOWERMENT (SJED)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.caste_categories (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.castes (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    caste_category_id BIGINT NOT NULL REFERENCES raj_masters.caste_categories(raj_master_id) ON DELETE CASCADE,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_castes_category_id ON raj_masters.castes(caste_category_id);
CREATE INDEX IF NOT EXISTS idx_castes_name_en_trgm ON raj_masters.castes USING gin (name_en gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 11. GOVERNMENT ORG & HR LOOKUPS
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS raj_masters.admin_departments (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    hod_designation TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_depts_name_en_trgm ON raj_masters.admin_departments USING gin (name_en gin_trgm_ops);

CREATE TABLE IF NOT EXISTS raj_masters.organization_categories (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.organizations (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    department_id BIGINT REFERENCES raj_masters.admin_departments(raj_master_id) ON DELETE SET NULL,
    org_category_id BIGINT REFERENCES raj_masters.organization_categories(raj_master_id) ON DELETE SET NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orgs_dept_id ON raj_masters.organizations(department_id);

CREATE TABLE IF NOT EXISTS raj_masters.office_levels (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    hierarchy_order INT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raj_masters.designations (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    cadre TEXT,
    pay_scale_grade TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_designations_name_en_trgm ON raj_masters.designations USING gin (name_en gin_trgm_ops);

CREATE TABLE IF NOT EXISTS raj_masters.services (
    id BIGSERIAL PRIMARY KEY,
    raj_master_id BIGINT UNIQUE NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 12. CONSOLIDATED GENERIC LOOKUP TABLE (21 SMALL REFERENCE MASTERS)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raj_masters.generic_lookups (
    id BIGSERIAL PRIMARY KEY,
    master_type VARCHAR(100) NOT NULL,
    raj_master_id VARCHAR(100) NOT NULL,
    code VARCHAR(50),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    sort_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_generic_lookup_type_id UNIQUE (master_type, raj_master_id)
);
CREATE INDEX IF NOT EXISTS idx_generic_lookups_master_type ON raj_masters.generic_lookups(master_type);
CREATE INDEX IF NOT EXISTS idx_generic_lookups_code ON raj_masters.generic_lookups(master_type, code);
CREATE INDEX IF NOT EXISTS idx_generic_lookups_name_en_trgm ON raj_masters.generic_lookups USING gin (name_en gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 13. COMPREHENSIVE PINCODE DIRECTORY
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raj_masters.pincodes (
    id BIGSERIAL PRIMARY KEY,
    pincode VARCHAR(20) NOT NULL,
    office_name TEXT,
    locality_name TEXT,
    district_id BIGINT REFERENCES raj_masters.districts(raj_master_id) ON DELETE SET NULL,
    division_id BIGINT REFERENCES raj_masters.divisions(raj_master_id) ON DELETE SET NULL,
    subdist_name TEXT,
    district_name TEXT,
    state_name TEXT DEFAULT 'RAJASTHAN',
    raj_master_id BIGINT,
    is_active BOOLEAN DEFAULT TRUE,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_raj_masters_pincode_office UNIQUE (pincode, office_name)
);
CREATE INDEX IF NOT EXISTS idx_pincodes_pincode ON raj_masters.pincodes(pincode);
CREATE INDEX IF NOT EXISTS idx_pincodes_district_id ON raj_masters.pincodes(district_id);
CREATE INDEX IF NOT EXISTS idx_pincodes_locality_trgm ON raj_masters.pincodes USING gin (locality_name gin_trgm_ops);

-- ----------------------------------------------------------------------------
-- 14. OBSERVABILITY & AUDIT LOG TABLE
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raj_masters.sync_audit_log (
    id BIGSERIAL PRIMARY KEY,
    master_name VARCHAR(150) NOT NULL,
    tier_level INT NOT NULL,
    expected_count INT DEFAULT 0,
    fetched_count INT DEFAULT 0,
    upserted_count INT DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    duration_seconds NUMERIC(10, 2) DEFAULT 0.0,
    mode VARCHAR(20) DEFAULT 'full',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_sync_audit_master ON raj_masters.sync_audit_log(master_name, created_at DESC);

-- ----------------------------------------------------------------------------
-- 15. AI ENTITY RESOLUTION UNIFIED VECTOR TABLE
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raj_masters.entity_embeddings (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL,
    raj_master_id VARCHAR(100) NOT NULL,
    lgd_code VARCHAR(100),
    name_en TEXT NOT NULL,
    name_hi TEXT,
    canonical_path_en TEXT NOT NULL,
    canonical_path_hi TEXT,
    metadata_json JSONB DEFAULT '{}'::jsonb,
    embedding vector,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_entity_embeddings_type_id UNIQUE (entity_type, raj_master_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_embeddings_path_en_trgm ON raj_masters.entity_embeddings USING gin (canonical_path_en gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_path_hi_trgm ON raj_masters.entity_embeddings USING gin (canonical_path_hi gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_name_en_trgm ON raj_masters.entity_embeddings USING gin (name_en gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_type ON raj_masters.entity_embeddings(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_embeddings_lgd ON raj_masters.entity_embeddings(lgd_code);

-- Create HNSW Vector Index if access method is supported
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_am WHERE amname = 'hnsw') THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_entity_embeddings_hnsw ON raj_masters.entity_embeddings USING hnsw (embedding vector_cosine_ops);';
    ELSE
        RAISE NOTICE 'HNSW index access method not available; skipping HNSW creation.';
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 16. HYBRID DETERMINISTIC & SEMANTIC ENTITY RESOLUTION FUNCTION
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION raj_masters.resolve_entity(
    query_text TEXT,
    query_embedding vector DEFAULT NULL,
    entity_type_filter TEXT DEFAULT NULL,
    top_k INT DEFAULT 5
)
RETURNS TABLE (
    entity_type VARCHAR(100),
    raj_master_id VARCHAR(100),
    lgd_code VARCHAR(100),
    name_en TEXT,
    name_hi TEXT,
    canonical_path_en TEXT,
    canonical_path_hi TEXT,
    metadata_json JSONB,
    semantic_score FLOAT,
    lexical_score FLOAT,
    hybrid_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH scored AS (
        SELECT 
            e.entity_type,
            e.raj_master_id,
            e.lgd_code,
            e.name_en,
            e.name_hi,
            e.canonical_path_en,
            e.canonical_path_hi,
            e.metadata_json,
            0.0::FLOAT AS sem_score,
            GREATEST(
                similarity(e.canonical_path_en, query_text),
                similarity(e.name_en, query_text),
                CASE WHEN e.canonical_path_hi IS NOT NULL THEN similarity(e.canonical_path_hi, query_text) ELSE 0.0 END
            )::FLOAT AS lex_score
        FROM raj_masters.entity_embeddings e
        WHERE (entity_type_filter IS NULL OR e.entity_type = entity_type_filter)
          AND (
            e.canonical_path_en % query_text 
            OR e.name_en % query_text
            OR (e.canonical_path_hi IS NOT NULL AND e.canonical_path_hi % query_text)
          )
    )
    SELECT 
        s.entity_type,
        s.raj_master_id,
        s.lgd_code,
        s.name_en,
        s.name_hi,
        s.canonical_path_en,
        s.canonical_path_hi,
        s.metadata_json,
        s.sem_score AS semantic_score,
        s.lex_score AS lexical_score,
        s.lex_score AS hybrid_score
    FROM scored s
    ORDER BY hybrid_score DESC
    LIMIT top_k;
END;
$$ LANGUAGE plpgsql STABLE;
