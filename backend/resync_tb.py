import asyncio
import asyncpg
import json

async def run():
    conn = await asyncpg.connect("postgresql://postgres:Admin%40123@host.docker.internal:5432/finalairajmaster")
    
    # 1. Load public districts
    pub_districts = await conn.fetch("SELECT id, name_en, rajmaster_id FROM public.districts")
    pub_dist_by_name = {d["name_en"].upper().strip(): d["id"] for d in pub_districts}
    pub_dist_by_rajid = {d["rajmaster_id"]: d["id"] for d in pub_districts if d["rajmaster_id"]}

    # 2. Sync all 426 Tehsils
    tehsils_in_rm = await conn.fetch("""
        SELECT t.raj_master_id, t.name_en, t.name_hi, t.code, t.district_id, t.tehsildar_details,
               d.name_en as dist_name
        FROM raj_masters.tehsils t
        LEFT JOIN raj_masters.districts d ON t.district_id = d.raj_master_id
    """)
    
    t_synced = 0
    for t in tehsils_in_rm:
        dist_id = pub_dist_by_rajid.get(t["district_id"]) or (pub_dist_by_name.get(t["dist_name"].upper()) if t["dist_name"] else None)
        t_name = t["name_en"]
        tehsildar = t["tehsildar_details"] or f"Tehsildar Office, {t_name}"
        meta = json.dumps({"source": "raj_masters.tehsils", "raj_master_id": t["raj_master_id"]})

        existing = await conn.fetchrow(
            "SELECT id FROM public.tehsils_blocks WHERE rajmaster_id = $1 AND entity_type = 'Tehsil'",
            t["raj_master_id"]
        )
        if not existing and dist_id:
            existing = await conn.fetchrow(
                "SELECT id FROM public.tehsils_blocks WHERE district_id = $1 AND LOWER(TRIM(name_en)) = LOWER(TRIM($2)) AND entity_type = 'Tehsil'",
                dist_id, t_name
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
            """, dist_id, t["raj_master_id"], t["code"], t["name_hi"], tehsildar, existing["id"])
        else:
            await conn.execute("""
                INSERT INTO public.tehsils_blocks
                (district_id, rajmaster_id, code, name_en, name_hi, entity_type, tehsildar_details, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'Tehsil', $6, $7::jsonb, NOW(), NOW())
            """, dist_id, t["raj_master_id"], t["code"], t_name, t["name_hi"], tehsildar, meta)
        t_synced += 1

    # 3. Sync all 457 Blocks
    blocks_in_rm = await conn.fetch("""
        SELECT b.raj_master_id, b.name_en, b.name_hi, b.code, b.lgd_code, b.district_id, b.bdo_details,
               d.name_en as dist_name
        FROM raj_masters.blocks b
        LEFT JOIN raj_masters.districts d ON b.district_id = d.raj_master_id
    """)

    b_synced = 0
    for b in blocks_in_rm:
        dist_id = pub_dist_by_rajid.get(b["district_id"]) or (pub_dist_by_name.get(b["dist_name"].upper()) if b["dist_name"] else None)
        b_name = b["name_en"]
        bdo = b["bdo_details"] or f"Block Development Officer (BDO), {b_name}"
        lgd_int = int(b["lgd_code"]) if b["lgd_code"] and b["lgd_code"].isdigit() else None
        meta = json.dumps({"source": "raj_masters.blocks", "raj_master_id": b["raj_master_id"]})

        existing = await conn.fetchrow(
            "SELECT id FROM public.tehsils_blocks WHERE rajmaster_id = $1 AND entity_type LIKE '%Block%'",
            b["raj_master_id"]
        )
        if not existing and dist_id:
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
            """, dist_id, b["raj_master_id"], b["code"], b["name_hi"], bdo, lgd_int, existing["id"])
        else:
            await conn.execute("""
                INSERT INTO public.tehsils_blocks
                (district_id, rajmaster_id, code, name_en, name_hi, entity_type, bdo_details, lgd_code, metadata_json, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'Panchayat Samiti / Block', $6, $7, $8::jsonb, NOW(), NOW())
            """, dist_id, b["raj_master_id"], b["code"], b_name, b["name_hi"], bdo, lgd_int, meta)
        b_synced += 1

    t_cnt = await conn.fetchval("SELECT count(*) FROM public.tehsils_blocks WHERE entity_type = 'Tehsil'")
    b_cnt = await conn.fetchval("SELECT count(*) FROM public.tehsils_blocks WHERE entity_type LIKE '%Block%'")
    tot_cnt = await conn.fetchval("SELECT count(*) FROM public.tehsils_blocks")
    print(f"Done! Synced {t_synced} tehsils and {b_synced} blocks.")
    print(f"Current public.tehsils_blocks totals: Tehsils={t_cnt}, Blocks={b_cnt}, Total={tot_cnt}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(run())
