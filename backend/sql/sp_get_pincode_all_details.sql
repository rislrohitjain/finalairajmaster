-- ============================================================================
-- PostgreSQL Stored Procedure & Helper Functions: Complete Pincode Lookup
-- Usage:
--   1) CALL public.sp_get_pincode_all_details('302026');
--   2) SELECT public.fn_get_pincode_all_details('302026');
--   3) SELECT * FROM public.fn_get_pincode_all_details_table('302026');
-- ============================================================================

CREATE OR REPLACE FUNCTION public.fn_get_pincode_all_details(p_pincode TEXT)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_pin TEXT := TRIM(COALESCE(p_pincode, ''));
    v_pin_row JSONB;
    v_division JSONB;
    v_district JSONB;
    v_sub_divisions JSONB;
    v_tehsils_blocks JSONB;
    v_gram_panchayats JSONB;
    v_villages JSONB;
    v_ulbs JSONB;
    v_urban_wards JSONB;
    v_rm_post_offices JSONB;
    v_rm_localities JSONB;
    v_dist_ids BIGINT[];
BEGIN
    IF v_pin = '' THEN
        RETURN jsonb_build_object('error', 'Pincode cannot be empty', 'found', FALSE);
    END IF;

    -- 1. Core Pincode Record (public.pincodes)
    SELECT to_jsonb(p.*)
    INTO v_pin_row
    FROM public.pincodes p
    WHERE p.pincode = v_pin
    LIMIT 1;

    -- Collect all related district_ids across public.pincodes, public.villages, raj_masters.pincode_localities
    SELECT ARRAY(
        SELECT DISTINCT x_did FROM (
            SELECT p.district_id AS x_did FROM public.pincodes p WHERE p.pincode = v_pin AND p.district_id IS NOT NULL
            UNION
            SELECT v.district_id AS x_did FROM public.villages v WHERE v.pincode = v_pin AND v.district_id IS NOT NULL
        ) s
    ) INTO v_dist_ids;

    -- 2. Divisions (public.divisions)
    SELECT COALESCE(jsonb_agg(DISTINCT to_jsonb(dv.*)), '[]'::jsonb)
    INTO v_division
    FROM public.divisions dv
    WHERE dv.id IN (
        SELECT p.division_id FROM public.pincodes p WHERE p.pincode = v_pin AND p.division_id IS NOT NULL
        UNION
        SELECT d.division_id FROM public.districts d WHERE d.id = ANY(v_dist_ids) AND d.division_id IS NOT NULL
    );

    -- 3. Districts (public.districts)
    SELECT COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
        'id', d.id,
        'name_en', d.name_en,
        'name_hi', d.name_hi,
        'code', d.code,
        'lgd_code', d.lgd_code,
        'division_id', d.division_id,
        'collectorate_details', d.collectorate_details,
        'zila_parishad_details', d.zila_parishad_details,
        'zila_pramukh', d.zila_pramukh
    )), '[]'::jsonb)
    INTO v_district
    FROM public.districts d
    WHERE d.id = ANY(v_dist_ids);

    -- 4. Tehsils & Blocks linked via pincodes, villages, or village GPs
    SELECT COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
        'id', tb.id,
        'name_en', tb.name_en,
        'name_hi', tb.name_hi,
        'entity_type', tb.entity_type,
        'code', tb.code,
        'lgd_code', tb.lgd_code,
        'district_id', tb.district_id,
        'sub_division_id', tb.sub_division_id,
        'tehsildar_details', tb.tehsildar_details,
        'bdo_details', tb.bdo_details
    )), '[]'::jsonb)
    INTO v_tehsils_blocks
    FROM public.tehsils_blocks tb
    WHERE tb.id IN (
        SELECT p.tehsil_block_id FROM public.pincodes p WHERE p.pincode = v_pin AND p.tehsil_block_id IS NOT NULL
        UNION
        SELECT v.tehsil_block_id FROM public.villages v WHERE v.pincode = v_pin AND v.tehsil_block_id IS NOT NULL
        UNION
        SELECT gp.tehsil_block_id
        FROM public.gram_panchayats gp
        JOIN public.villages v ON v.gram_panchayat_id = gp.id
        WHERE v.pincode = v_pin AND gp.tehsil_block_id IS NOT NULL
    );

    -- 5. Sub-Divisions linked via those Tehsils/Blocks
    SELECT COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
        'id', sd.id,
        'name_en', sd.name_en,
        'name_hi', sd.name_hi,
        'code', sd.code,
        'district_id', sd.district_id,
        'sdm_jurisdiction', sd.sdm_jurisdiction
    )), '[]'::jsonb)
    INTO v_sub_divisions
    FROM public.sub_divisions sd
    WHERE sd.id IN (
        SELECT tb.sub_division_id
        FROM public.tehsils_blocks tb
        WHERE tb.sub_division_id IS NOT NULL
          AND tb.id IN (
              SELECT p.tehsil_block_id FROM public.pincodes p WHERE p.pincode = v_pin AND p.tehsil_block_id IS NOT NULL
              UNION
              SELECT v.tehsil_block_id FROM public.villages v WHERE v.pincode = v_pin AND v.tehsil_block_id IS NOT NULL
          )
    );

    -- 6. Gram Panchayats linked directly or via villages
    SELECT COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
        'id', gp.id,
        'name_en', gp.name_en,
        'name_hi', gp.name_hi,
        'code', gp.code,
        'lgd_code', gp.lgd_code,
        'sarpanch', gp.sarpanch,
        'tehsil_block_id', gp.tehsil_block_id,
        'district_id', gp.district_id
    )), '[]'::jsonb)
    INTO v_gram_panchayats
    FROM public.gram_panchayats gp
    WHERE gp.id IN (
        SELECT p.gram_panchayat_id FROM public.pincodes p WHERE p.pincode = v_pin AND p.gram_panchayat_id IS NOT NULL
        UNION
        SELECT v.gram_panchayat_id FROM public.villages v WHERE v.pincode = v_pin AND v.gram_panchayat_id IS NOT NULL
    );

    -- 7. Villages matching this pincode (public.villages)
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'id', v.id,
        'name_en', v.name_en,
        'name_hi', v.name_hi,
        'code', v.code,
        'lgd_code', v.lgd_code,
        'patwar_circle', v.patwar_circle,
        'district', d.name_en,
        'tehsil_or_block', tb.name_en,
        'gram_panchayat', gp.name_en,
        'pincode', v.pincode
    ) ORDER BY v.name_en), '[]'::jsonb)
    INTO v_villages
    FROM public.villages v
    LEFT JOIN public.districts d ON d.id = v.district_id
    LEFT JOIN public.tehsils_blocks tb ON tb.id = v.tehsil_block_id
    LEFT JOIN public.gram_panchayats gp ON gp.id = v.gram_panchayat_id
    WHERE v.pincode = v_pin;

    -- 8. Urban Local Bodies (public.urban_local_bodies)
    SELECT COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
        'id', u.id,
        'name_en', u.name_en,
        'name_hi', u.name_hi,
        'ulb_type', u.ulb_type,
        'city_name', u.city_name,
        'code', u.code,
        'lgd_code', u.lgd_code,
        'pincode', u.pincode,
        'district_id', u.district_id
    )), '[]'::jsonb)
    INTO v_ulbs
    FROM public.urban_local_bodies u
    WHERE u.pincode = v_pin
       OR u.id IN (SELECT p.ulb_id FROM public.pincodes p WHERE p.pincode = v_pin AND p.ulb_id IS NOT NULL);

    -- 9. Urban Wards matching this pincode directly (public.urban_wards)
    SELECT COALESCE(jsonb_agg(DISTINCT jsonb_build_object(
        'id', uw.id,
        'ulb_id', uw.ulb_id,
        'ulb_name', u.name_en,
        'ward_number', uw.ward_number,
        'name_en', uw.name_en,
        'name_hi', uw.name_hi,
        'councillor_parshad', uw.councillor_parshad,
        'pincode', uw.pincode,
        'lgd_code', uw.lgd_code
    )), '[]'::jsonb)
    INTO v_urban_wards
    FROM public.urban_wards uw
    LEFT JOIN public.urban_local_bodies u ON u.id = uw.ulb_id
    WHERE uw.pincode = v_pin;

    -- 10. Post Offices (raj_masters.pincodes)
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'id', rp.id,
        'pincode', rp.pincode,
        'office_name', rp.office_name,
        'locality_summary', rp.locality_name,
        'subdist_name', rp.subdist_name,
        'district_name', rp.district_name,
        'state_name', rp.state_name
    ) ORDER BY rp.office_name), '[]'::jsonb)
    INTO v_rm_post_offices
    FROM raj_masters.pincodes rp
    WHERE rp.pincode = v_pin;

    -- 11. Granular Localities (raj_masters.pincode_localities)
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'id', rl.id,
        'raj_master_id', rl.raj_master_id,
        'pincode', rl.pincode,
        'locality_name', rl.locality_name,
        'office_name', rl.office_name,
        'subdist_name', rl.subdist_name,
        'district_name', rl.district_name
    ) ORDER BY rl.locality_name), '[]'::jsonb)
    INTO v_rm_localities
    FROM raj_masters.pincode_localities rl
    WHERE rl.pincode = v_pin;

    RETURN jsonb_build_object(
        'pincode', v_pin,
        'found', (v_pin_row IS NOT NULL OR jsonb_array_length(v_rm_localities) > 0 OR jsonb_array_length(v_villages) > 0),
        'counts', jsonb_build_object(
            'divisions', jsonb_array_length(v_division),
            'districts', jsonb_array_length(v_district),
            'sub_divisions', jsonb_array_length(v_sub_divisions),
            'tehsils_blocks', jsonb_array_length(v_tehsils_blocks),
            'gram_panchayats', jsonb_array_length(v_gram_panchayats),
            'villages', jsonb_array_length(v_villages),
            'urban_local_bodies', jsonb_array_length(v_ulbs),
            'urban_wards', jsonb_array_length(v_urban_wards),
            'post_offices', jsonb_array_length(v_rm_post_offices),
            'localities', jsonb_array_length(v_rm_localities)
        ),
        'public_pincode', v_pin_row,
        'divisions', v_division,
        'districts', v_district,
        'sub_divisions', v_sub_divisions,
        'tehsils_blocks', v_tehsils_blocks,
        'gram_panchayats', v_gram_panchayats,
        'villages', v_villages,
        'urban_local_bodies', v_ulbs,
        'urban_wards', v_urban_wards,
        'raj_masters_post_offices', v_rm_post_offices,
        'raj_masters_localities', v_rm_localities
    );
END;
$$;


-- Tabular version for direct grid inspection in pgAdmin / DBeaver / psql
CREATE OR REPLACE FUNCTION public.fn_get_pincode_all_details_table(p_pincode TEXT)
RETURNS TABLE (
    source_table TEXT,
    entity_type TEXT,
    record_id BIGINT,
    name_en TEXT,
    name_hi TEXT,
    code TEXT,
    lgd_code TEXT,
    parent_hierarchy TEXT,
    extra_details JSONB
)
LANGUAGE sql
STABLE
AS $$
    WITH pin AS (
        SELECT TRIM(COALESCE(p_pincode, '')) AS val
    )
    SELECT 'public.pincodes'::TEXT, 'Pincode Master'::TEXT, p.id::BIGINT,
           p.city_or_village::TEXT, NULL::TEXT, p.pincode::TEXT, NULL::TEXT,
           COALESCE(d.name_en, 'Rajasthan') || COALESCE(' (' || dv.name_en || ')', ''),
           p.metadata_json
    FROM public.pincodes p
    CROSS JOIN pin
    LEFT JOIN public.districts d ON d.id = p.district_id
    LEFT JOIN public.divisions dv ON dv.id = p.division_id
    WHERE p.pincode = pin.val

    UNION ALL

    SELECT 'public.districts'::TEXT, 'District'::TEXT, d.id::BIGINT,
           d.name_en::TEXT, d.name_hi::TEXT, d.code::TEXT, d.lgd_code::TEXT,
           COALESCE(dv.name_en, 'Rajasthan'),
           jsonb_build_object('collectorate', d.collectorate_details, 'zila_pramukh', d.zila_pramukh)
    FROM public.districts d
    LEFT JOIN public.divisions dv ON dv.id = d.division_id
    WHERE d.id IN (
        SELECT p.district_id FROM public.pincodes p, pin WHERE p.pincode = pin.val AND p.district_id IS NOT NULL
        UNION
        SELECT v.district_id FROM public.villages v, pin WHERE v.pincode = pin.val AND v.district_id IS NOT NULL
    )

    UNION ALL

    SELECT 'public.tehsils_blocks'::TEXT, tb.entity_type::TEXT, tb.id::BIGINT,
           tb.name_en::TEXT, tb.name_hi::TEXT, tb.code::TEXT, tb.lgd_code::TEXT,
           COALESCE(d.name_en, 'Rajasthan'),
           jsonb_build_object('tehsildar', tb.tehsildar_details, 'bdo', tb.bdo_details)
    FROM public.tehsils_blocks tb
    LEFT JOIN public.districts d ON d.id = tb.district_id
    WHERE tb.id IN (
        SELECT p.tehsil_block_id FROM public.pincodes p, pin WHERE p.pincode = pin.val AND p.tehsil_block_id IS NOT NULL
        UNION
        SELECT v.tehsil_block_id FROM public.villages v, pin WHERE v.pincode = pin.val AND v.tehsil_block_id IS NOT NULL
    )

    UNION ALL

    SELECT 'public.gram_panchayats'::TEXT, 'Gram Panchayat'::TEXT, gp.id::BIGINT,
           gp.name_en::TEXT, gp.name_hi::TEXT, gp.code::TEXT, gp.lgd_code::TEXT,
           COALESCE(tb.name_en || ', ', '') || COALESCE(d.name_en, 'Rajasthan'),
           jsonb_build_object('sarpanch', gp.sarpanch)
    FROM public.gram_panchayats gp
    LEFT JOIN public.tehsils_blocks tb ON tb.id = gp.tehsil_block_id
    LEFT JOIN public.districts d ON d.id = gp.district_id
    WHERE gp.id IN (
        SELECT p.gram_panchayat_id FROM public.pincodes p, pin WHERE p.pincode = pin.val AND p.gram_panchayat_id IS NOT NULL
        UNION
        SELECT v.gram_panchayat_id FROM public.villages v, pin WHERE v.pincode = pin.val AND v.gram_panchayat_id IS NOT NULL
    )

    UNION ALL

    SELECT 'public.villages'::TEXT, 'Revenue Village'::TEXT, v.id::BIGINT,
           v.name_en::TEXT, v.name_hi::TEXT, v.code::TEXT, v.lgd_code::TEXT,
           COALESCE('GP ' || gp.name_en || ', ', '') || COALESCE(tb.name_en || ', ', '') || COALESCE(d.name_en, 'Rajasthan'),
           jsonb_build_object('patwar_circle', v.patwar_circle, 'pincode', v.pincode)
    FROM public.villages v
    CROSS JOIN pin
    LEFT JOIN public.gram_panchayats gp ON gp.id = v.gram_panchayat_id
    LEFT JOIN public.tehsils_blocks tb ON tb.id = v.tehsil_block_id
    LEFT JOIN public.districts d ON d.id = v.district_id
    WHERE v.pincode = pin.val

    UNION ALL

    SELECT 'public.urban_local_bodies'::TEXT, COALESCE(u.ulb_type, 'ULB')::TEXT, u.id::BIGINT,
           u.name_en::TEXT, u.name_hi::TEXT, u.code::TEXT, u.lgd_code::TEXT,
           COALESCE(d.name_en, 'Rajasthan'),
           jsonb_build_object('city_name', u.city_name, 'pincode', u.pincode)
    FROM public.urban_local_bodies u
    LEFT JOIN public.districts d ON d.id = u.district_id
    WHERE u.pincode = (SELECT val FROM pin)
       OR u.id IN (SELECT p.ulb_id FROM public.pincodes p, pin WHERE p.pincode = pin.val AND p.ulb_id IS NOT NULL)

    UNION ALL

    SELECT 'public.urban_wards'::TEXT, 'Urban Ward'::TEXT, uw.id::BIGINT,
           COALESCE(uw.name_en, uw.ward_number)::TEXT, uw.name_hi::TEXT, uw.ward_number::TEXT, uw.lgd_code::TEXT,
           COALESCE(u.name_en, 'ULB'),
           jsonb_build_object('councillor', uw.councillor_parshad, 'pincode', uw.pincode)
    FROM public.urban_wards uw
    CROSS JOIN pin
    LEFT JOIN public.urban_local_bodies u ON u.id = uw.ulb_id
    WHERE uw.pincode = pin.val

    UNION ALL

    SELECT 'raj_masters.pincodes'::TEXT, 'Post Office'::TEXT, rp.id::BIGINT,
           rp.office_name::TEXT, NULL::TEXT, rp.pincode::TEXT, NULL::TEXT,
           COALESCE(rp.subdist_name || ', ', '') || COALESCE(rp.district_name, 'RAJASTHAN'),
           jsonb_build_object('localities', rp.locality_name)
    FROM raj_masters.pincodes rp
    CROSS JOIN pin
    WHERE rp.pincode = pin.val

    UNION ALL

    SELECT 'raj_masters.pincode_localities'::TEXT, 'Postal Locality'::TEXT, rl.id::BIGINT,
           rl.locality_name::TEXT, NULL::TEXT, rl.pincode::TEXT, rl.raj_master_id::TEXT,
           COALESCE(rl.office_name || ' | ', '') || COALESCE(rl.subdist_name || ', ', '') || COALESCE(rl.district_name, 'RAJASTHAN'),
           jsonb_build_object('office_name', rl.office_name, 'subdist_name', rl.subdist_name)
    FROM raj_masters.pincode_localities rl
    CROSS JOIN pin
    WHERE rl.pincode = pin.val;
$$;


-- Stored Procedure (CALL syntax): CALL public.sp_get_pincode_all_details('302026');
CREATE OR REPLACE PROCEDURE public.sp_get_pincode_all_details(
    IN p_pincode TEXT,
    INOUT p_result JSONB DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
    p_result := public.fn_get_pincode_all_details(p_pincode);
END;
$$;
