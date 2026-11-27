import logging
import re
from typing import List, Dict, Any, Optional
from sqlalchemy import select, or_, func
from app.db.session import AsyncSessionLocal
from app.db.models import (
    State, Division, District, SubDivision, TehsilBlock,
    GramPanchayat, PanchayatWard, Village, UrbanLocalBody, UrbanWard,
    Pincode
)

logger = logging.getLogger(__name__)

NAME_ALIASES = {
    "balotra": ["balotra", "balotara", "बालोतरा"],
    "balotara": ["balotara", "balotra", "बालोतरा"],
    "didwana": ["didwana", "didwana-kuchaman", "deedwana", "डीडवाना"],
    "kuchaman": ["kuchaman", "didwana-kuchaman", "कुचामन"],
    "neemkathana": ["neem ka thana", "neemkathana", "नीम का थाना"],
    "neem ka thana": ["neem ka thana", "neemkathana", "नीम का थाना"],
    "kotputli": ["kotputli", "kotputli-behror", "कोटपूतली"],
    "behror": ["behror", "kotputli-behror", "बहरोड़"],
    "khairthal": ["khairthal", "khairthal-tijara", "खैरथल"],
    "tijara": ["tijara", "khairthal-tijara", "तिजारा"],
    "chittor": ["chittorgarh", "chittaurgarh", "चित्तौड़गढ़"],
    "chittorgarh": ["chittorgarh", "chittaurgarh", "चित्तौड़गढ़"],
    "chittaurgarh": ["chittorgarh", "chittaurgarh", "चित्तौड़गढ़"],
    "jalore": ["jalore", "jalor", "जालौर"],
    "jalor": ["jalore", "jalor", "जालौर"],
    "ganganagar": ["sri ganganagar", "ganganagar", "श्रीगंगानगर"],
    "sri ganganagar": ["sri ganganagar", "ganganagar", "श्रीगंगानगर"],
    "sawaimadhopur": ["sawai madhopur", "सवाई माधोपुर"],
    "sawai madhopur": ["sawai madhopur", "सवाई माधोपुर"],
    "anupgarh": ["anupgarh", "अनूपगढ़"],
    "phalodi": ["phalodi", "फलोदी"],
    "salumbar": ["salumbar", "salumber", "सलूंबर"],
    "shahpura": ["shahpura", "शाहपुरा"],
    "kekri": ["kekri", "केकड़ी"],
    "beawar": ["beawar", "ब्यावर"],
    "dudu": ["dudu", "दूदू"]
}

STOP_WORDS = {
    "what", "where", "which", "tell", "about", "details", "the", "and", "under", "rajasthan",
    "administrative", "lineage", "hierarchy", "information", "village", "tehsil", "district",
    "division", "block", "panchayat", "samiti", "urban", "body", "city", "give", "show", "is",
    "of", "in", "to", "for", "with", "does", "belong", "covers", "head", "heads", "who", "are", "name",
    "names", "corporation", "municipal", "council", "local", "me", "how", "many", "all", "list",
    "comes", "come", "fall", "falls", "role", "duties", "jurisdiction", "officials", "official",
    "collector", "collectorate", "pramukh", "tehsildar", "bdo", "sarpanch", "patwari", "commissioner",
    "sdm", "sdo", "board", "area", "town", "circle", "revenue",
    # Hindi stop words
    "क्या", "कहाँ", "कौन", "किस", "किसे", "कितने", "बताएं", "बताओ", "की", "का", "के", "में",
    "है", "हैं", "आता", "आती", "आते", "पड़ता", "पड़ती", "गांव", "तहसील", "जिला", "संभाग",
    "उपखंड", "ब्लॉक", "पंचायत", "समिति", "नगर", "निगम", "परिषद", "पालिका", "प्रशासनिक",
    "वंशावली", "पदानुक्रम", "विवरण", "जानकारी", "अधिकार", "क्षेत्र", "अध्यक्ष", "प्रधान"
}

async def _lookup_geographic_hierarchy_impl(query: str) -> Dict[str, Any]:
    clean_query = query.strip()
    digits = re.findall(r"\b\d{6}\b", clean_query) # 6 digit pincode

    result: Dict[str, Any] = {
        "matched": False,
        "entity_type": None,
        "entity_name": None,
        "lineage": {},
        "breadcrumbs": [],
        "details": {},
        "raw_matches": []
    }

    async with AsyncSessionLocal() as session:
        # 1. Pincode Search
        if digits:
            pin = digits[0]
            stmt = select(Pincode).where(Pincode.pincode == pin).limit(5)
            pin_rows = (await session.execute(stmt)).scalars().all()
            if pin_rows:
                p_item = pin_rows[0]
                result["matched"] = True
                result["entity_type"] = "Pincode"
                result["entity_name"] = f"Pincode {p_item.pincode} ({p_item.city_or_village})"
                
                # Fetch parents
                dist = None
                div = None
                tb = None
                ulb = None
                gp = None

                if p_item.district_id:
                    dist = (await session.execute(select(District).where(District.id == p_item.district_id))).scalar_one_or_none()
                if p_item.division_id:
                    div = (await session.execute(select(Division).where(Division.id == p_item.division_id))).scalar_one_or_none()
                elif dist and dist.division_id:
                    div = (await session.execute(select(Division).where(Division.id == dist.division_id))).scalar_one_or_none()
                if p_item.tehsil_block_id:
                    tb = (await session.execute(select(TehsilBlock).where(TehsilBlock.id == p_item.tehsil_block_id))).scalar_one_or_none()
                if p_item.ulb_id:
                    ulb = (await session.execute(select(UrbanLocalBody).where(UrbanLocalBody.id == p_item.ulb_id))).scalar_one_or_none()
                if p_item.gram_panchayat_id:
                    gp = (await session.execute(select(GramPanchayat).where(GramPanchayat.id == p_item.gram_panchayat_id))).scalar_one_or_none()

                lineage = {
                    "state": "Rajasthan",
                    "division": div.name_en if div else "Jaipur Division",
                    "district": dist.name_en if dist else "Jaipur",
                    "tehsil_or_block": tb.name_en if tb else None,
                    "ulb": ulb.name_en if ulb else None,
                    "gram_panchayat": gp.name_en if gp else None,
                    "area_or_village": p_item.city_or_village,
                    "pincode": p_item.pincode
                }
                result["lineage"] = lineage
                result["breadcrumbs"] = [x for x in [
                    "Rajasthan",
                    lineage.get("division"),
                    lineage.get("district"),
                    lineage.get("tehsil_or_block"),
                    lineage.get("ulb") or lineage.get("gram_panchayat"),
                    p_item.city_or_village
                ] if x]
                result["details"] = {
                    "pincode": p_item.pincode,
                    "city_or_village": p_item.city_or_village,
                    "district": dist.name_en if dist else None,
                    "zila_pramukh": dist.zila_pramukh if dist else None,
                    "collectorate": dist.collectorate_details if dist else None
                }
                return result

        # 2. Check for State-Level, Division-Overview, or Districts-List Specific Queries
        q_lower = clean_query.lower()

        # Check for list/overview of districts
        is_district_list_query = (
            any(w in q_lower for w in ["district", "districts", "जिला", "जिले", "zila", "zile"]) and
            any(w in q_lower for w in ["list", "name", "names", "10", "ten", "how many", "all", "naam", "नाम", "सूची", "बताएं", "बताओ", "दिखाएं"])
        ) or any(phrase in q_lower for phrase in [
            "districts of rajasthan", "districts in rajasthan", "rajasthan districts",
            "10 districts", "ten districts", "districts name", "district names"
        ])

        if is_district_list_query:
            stmt = (
                select(District, Division)
                .outerjoin(Division, District.division_id == Division.id)
                .order_by(District.id)
            )
            rows = (await session.execute(stmt)).all()
            districts_list = []
            for d, div in rows:
                districts_list.append({
                    "name_en": d.name_en,
                    "name_hi": d.name_hi,
                    "division": div.name_en if div else "Rajasthan",
                    "zila_pramukh": d.zila_pramukh,
                    "collectorate": d.collectorate_details,
                    "lgd_code": d.lgd_code
                })

            result["matched"] = True
            result["entity_type"] = "DistrictsList"
            result["entity_name"] = "Districts of Rajasthan"
            result["breadcrumbs"] = ["Rajasthan", "10 Divisions", "50 Districts"]
            result["lineage"] = {
                "state": "Rajasthan",
                "divisions_count": 10,
                "districts_count": len(districts_list)
            }
            result["details"] = {
                "districts": districts_list,
                "total_count": len(districts_list),
                "requested_10": True
            }
            return result

        if any(term in q_lower for term in ["secretariat", "chief secretary", "governance", "all 10 divisions", "list the administrative divisions", "divisions of rajasthan", "10 divisions", "ten divisions"]):
            st = (await session.execute(select(State).where(State.id == 1))).scalar_one_or_none()
            all_divs = (await session.execute(select(Division))).scalars().all()
            all_dist = (await session.execute(select(District))).scalars().all()

            result["matched"] = True
            result["entity_type"] = "State"
            result["entity_name"] = "Rajasthan"
            result["lineage"] = {
                "state": "Rajasthan",
                "divisions_count": len(all_divs),
                "districts_count": len(all_dist)
            }
            result["breadcrumbs"] = ["Rajasthan", "10 Administrative Divisions"]
            result["details"] = {
                "state_english": "Rajasthan",
                "state_hindi": "राजस्थान",
                "chief_secretary": st.chief_secretary if st else "Chief Secretary, Government of Rajasthan",
                "governance_details": st.governance_details if st else "Government Secretariat, Jaipur",
                "divisions": [d.name_en for d in all_divs],
                "districts_count": len(all_dist),
                "lgd_code": 8
            }
            return result

        # 3. Extract candidate entities from natural language text
        raw_words = [w for w in re.split(r"[ ,?.!]+", clean_query) if len(w) >= 2]
        candidates = [w for w in raw_words if w.lower() not in STOP_WORDS and len(w) >= 3]

        terms_to_try = []
        if len(candidates) >= 2:
            terms_to_try.append(" ".join(candidates[:2])) # e.g. "Jaipur Greater"
        terms_to_try.extend(candidates)

        for c in list(candidates):
            c_low = c.lower()
            if c_low in NAME_ALIASES:
                for alt in NAME_ALIASES[c_low]:
                    if alt not in terms_to_try:
                        terms_to_try.append(alt)

        if not terms_to_try:
            terms_to_try = [clean_query]

        for term in terms_to_try:
            sterm = f"%{term}%"

            # Check Districts
            dst = (await session.execute(select(District).where(
                or_(District.name_en.ilike(sterm), District.name_hi.ilike(sterm))
            ).limit(1))).scalar_one_or_none()
            if dst:
                div = (await session.execute(select(Division).where(Division.id == dst.division_id))).scalar_one_or_none() if dst.division_id else None
                v_cnt = (await session.execute(select(func.count(Village.id)).where(Village.district_id == dst.id))).scalar() or 0
                tb_cnt = (await session.execute(select(func.count(TehsilBlock.id)).where(TehsilBlock.district_id == dst.id))).scalar() or 0
                gp_cnt = (await session.execute(select(func.count(GramPanchayat.id)).where(GramPanchayat.district_id == dst.id))).scalar() or 0
                ulb_cnt = (await session.execute(select(func.count(UrbanLocalBody.id)).where(UrbanLocalBody.district_id == dst.id))).scalar() or 0

                q_lower = clean_query.lower()
                is_count_query = any(k in q_lower for k in [
                    "number of", "count of", "how many", "total number", "kitne", "kitni", "sankhya", "संख्या", "कितने", "कितनी"
                ])
                asked_villages = any(k in q_lower for k in ["village", "villages", "gaon", "गांव", "गाँव"])
                asked_tehsils = any(k in q_lower for k in ["tehsil", "tehsils", "block", "blocks", "तहसील", "ब्लॉक"])
                asked_panchayats = any(k in q_lower for k in ["panchayat", "gram panchayat", "पंचायत"])

                result["matched"] = True
                result["entity_type"] = "District"
                result["entity_name"] = dst.name_en
                result["lineage"] = {
                    "state": "Rajasthan",
                    "division": div.name_en if div else None,
                    "district": dst.name_en,
                    "collectorate": dst.collectorate_details,
                    "zila_parishad": dst.zila_parishad_details,
                    "zila_pramukh": dst.zila_pramukh,
                    "lgd_code": dst.lgd_code,
                    "villages_count": v_cnt,
                    "tehsils_count": tb_cnt
                }
                result["breadcrumbs"] = [x for x in ["Rajasthan", div.name_en if div else None, dst.name_en] if x]
                result["details"] = {
                    "district_english": dst.name_en,
                    "district_hindi": dst.name_hi,
                    "division": div.name_en if div else None,
                    "zila_pramukh": dst.zila_pramukh,
                    "collectorate": dst.collectorate_details,
                    "lgd_code": dst.lgd_code,
                    "is_count_query": is_count_query,
                    "villages_count": v_cnt,
                    "tehsils_count": tb_cnt,
                    "gram_panchayats_count": gp_cnt,
                    "ulbs_count": ulb_cnt,
                    "asked_villages": asked_villages,
                    "asked_tehsils": asked_tehsils,
                    "asked_panchayats": asked_panchayats
                }
                return result

            # Check Tehsils & Blocks
            tb = (await session.execute(select(TehsilBlock).where(
                or_(TehsilBlock.name_en.ilike(sterm), TehsilBlock.name_hi.ilike(sterm))
            ).limit(1))).scalar_one_or_none()
            if tb:
                dist = (await session.execute(select(District).where(District.id == tb.district_id))).scalar_one_or_none() if tb.district_id else None
                div = (await session.execute(select(Division).where(Division.id == dist.division_id))).scalar_one_or_none() if dist and dist.division_id else None
                sd = (await session.execute(select(SubDivision).where(SubDivision.id == tb.sub_division_id))).scalar_one_or_none() if tb.sub_division_id else None
                result["matched"] = True
                result["entity_type"] = tb.entity_type
                result["entity_name"] = tb.name_en
                result["lineage"] = {
                    "state": "Rajasthan",
                    "division": div.name_en if div else None,
                    "district": dist.name_en if dist else None,
                    "sub_division": sd.name_en if sd else None,
                    "tehsil_or_block": tb.name_en,
                    "entity_type": tb.entity_type,
                    "lgd_code": tb.lgd_code
                }
                result["breadcrumbs"] = [x for x in ["Rajasthan", div.name_en if div else None, dist.name_en if dist else None, sd.name_en if sd else None, tb.name_en] if x]
                result["details"] = {
                    "entity_english": tb.name_en,
                    "entity_hindi": tb.name_hi,
                    "entity_type": tb.entity_type,
                    "tehsildar": tb.tehsildar_details,
                    "bdo": tb.bdo_details,
                    "sdm_jurisdiction": sd.sdm_jurisdiction if sd else None,
                    "lgd_code": tb.lgd_code
                }
                return result

            # Check Urban Local Bodies
            ulb = (await session.execute(select(UrbanLocalBody).where(
                or_(UrbanLocalBody.name_en.ilike(sterm), UrbanLocalBody.name_hi.ilike(sterm), UrbanLocalBody.city_name.ilike(sterm))
            ).limit(1))).scalar_one_or_none()
            if ulb:
                dist = (await session.execute(select(District).where(District.id == ulb.district_id))).scalar_one_or_none()
                div = (await session.execute(select(Division).where(Division.id == dist.division_id))).scalar_one_or_none() if dist and dist.division_id else None
                result["matched"] = True
                result["entity_type"] = f"Urban Local Body ({ulb.ulb_type})"
                result["entity_name"] = ulb.name_en
                result["lineage"] = {
                    "state": "Rajasthan",
                    "division": div.name_en if div else None,
                    "district": dist.name_en if dist else None,
                    "city": ulb.city_name,
                    "ulb_name": ulb.name_en,
                    "ulb_type": ulb.ulb_type,
                    "lgd_code": ulb.lgd_code,
                    "pincode": ulb.pincode
                }
                result["breadcrumbs"] = [x for x in ["Rajasthan", div.name_en if div else None, dist.name_en if dist else None, ulb.name_en] if x]
                result["details"] = {
                    "ulb_english": ulb.name_en,
                    "ulb_hindi": ulb.name_hi,
                    "ulb_type": ulb.ulb_type,
                    "city": ulb.city_name,
                    "district": dist.name_en if dist else None,
                    "collectorate": dist.collectorate_details if dist else None,
                    "pincode": ulb.pincode,
                    "lgd_code": ulb.lgd_code
                }
                return result

            # Check Villages
            v = (await session.execute(select(Village).where(
                or_(Village.name_en.ilike(sterm), Village.name_hi.ilike(sterm), Village.patwar_circle.ilike(sterm))
            ).limit(1))).scalar_one_or_none()
            if v:
                dist = (await session.execute(select(District).where(District.id == v.district_id))).scalar_one_or_none() if v.district_id else None
                div = (await session.execute(select(Division).where(Division.id == dist.division_id))).scalar_one_or_none() if dist and dist.division_id else None
                tb = (await session.execute(select(TehsilBlock).where(TehsilBlock.id == v.tehsil_block_id))).scalar_one_or_none() if v.tehsil_block_id else None
                gp = (await session.execute(select(GramPanchayat).where(GramPanchayat.id == v.gram_panchayat_id))).scalar_one_or_none() if v.gram_panchayat_id else None
                result["matched"] = True
                result["entity_type"] = "Village"
                result["entity_name"] = v.name_en
                result["lineage"] = {
                    "state": "Rajasthan",
                    "division": div.name_en if div else None,
                    "district": dist.name_en if dist else None,
                    "tehsil": tb.name_en if tb else None,
                    "gram_panchayat": gp.name_en if gp else None,
                    "patwar_circle": v.patwar_circle,
                    "village": v.name_en,
                    "lgd_code": v.lgd_code,
                    "pincode": v.pincode
                }
                result["breadcrumbs"] = [x for x in ["Rajasthan", div.name_en if div else None, dist.name_en if dist else None, tb.name_en if tb else None, gp.name_en if gp else None, v.name_en] if x]
                result["details"] = {
                    "village_english": v.name_en,
                    "village_hindi": v.name_hi,
                    "patwar_circle": v.patwar_circle,
                    "patwari": v.patwari,
                    "sarpanch": gp.sarpanch if gp else None,
                    "pincode": v.pincode,
                    "lgd_code": v.lgd_code
                }
                return result

            # Check Divisions
            div = (await session.execute(select(Division).where(
                or_(Division.name_en.ilike(sterm), Division.name_hi.ilike(sterm))
            ).limit(1))).scalar_one_or_none()
            if div:
                dist_list = (await session.execute(select(District).where(District.division_id == div.id))).scalars().all()
                result["matched"] = True
                result["entity_type"] = "Division"
                result["entity_name"] = div.name_en
                result["lineage"] = {
                    "state": "Rajasthan",
                    "division": div.name_en,
                    "divisional_commissioner": div.divisional_commissioner,
                    "districts": [d.name_en for d in dist_list]
                }
                result["breadcrumbs"] = ["Rajasthan", div.name_en]
                result["details"] = {
                    "division_english": div.name_en,
                    "division_hindi": div.name_hi,
                    "divisional_commissioner": div.divisional_commissioner,
                    "districts_count": len(dist_list),
                    "districts": [d.name_en for d in dist_list],
                    "lgd_code": div.lgd_code
                }
                return result

    return result

def _lookup_in_memory_master(query: str) -> Dict[str, Any]:
    from app.db.init_db import (
        FALLBACK_DIVISIONS, FALLBACK_DISTRICTS, FALLBACK_SUBDIVISIONS,
        FALLBACK_TEHSILS_BLOCKS, FALLBACK_GRAM_PANCHAYATS, FALLBACK_VILLAGES,
        FALLBACK_ULBS
    )
    clean_query = query.strip()
    digits = re.findall(r"\b\d{6}\b", clean_query)

    result: Dict[str, Any] = {
        "matched": False,
        "entity_type": None,
        "entity_name": None,
        "lineage": {},
        "breadcrumbs": [],
        "details": {},
        "raw_matches": []
    }

    # 1. Pincode
    if digits:
        pin = digits[0]
        for v in FALLBACK_VILLAGES:
            if v.get("pincode") == pin:
                dist = next((d for d in FALLBACK_DISTRICTS if d["rajmaster_id"] == v.get("district_id")), None)
                div = next((dv for dv in FALLBACK_DIVISIONS if dist and dv["rajmaster_id"] == dist.get("division_id")), None)
                tb = next((t for t in FALLBACK_TEHSILS_BLOCKS if t["rajmaster_id"] == v.get("tehsil_block_id")), None)
                gp = next((g for g in FALLBACK_GRAM_PANCHAYATS if g["rajmaster_id"] == v.get("gram_panchayat_id")), None)
                result["matched"] = True
                result["entity_type"] = "Pincode"
                result["entity_name"] = f"Pincode {pin} ({v['name_en']})"
                result["lineage"] = {
                    "state": "Rajasthan",
                    "division": div["name_en"] if div else None,
                    "district": dist["name_en"] if dist else None,
                    "tehsil_or_block": tb["name_en"] if tb else None,
                    "gram_panchayat": gp["name_en"] if gp else None,
                    "area_or_village": v["name_en"],
                    "patwar_circle": v.get("patwar_circle"),
                    "patwari": v.get("patwari"),
                    "pincode": pin
                }
                result["breadcrumbs"] = [x for x in ["Rajasthan", div["name_en"] if div else None, dist["name_en"] if dist else None, v["name_en"]] if x]
                result["details"] = {
                    "pincode": pin,
                    "city_or_village": v["name_en"],
                    "district": dist["name_en"] if dist else None,
                    "division": div["name_en"] if div else None,
                    "tehsil": tb["name_en"] if tb else None,
                    "gram_panchayat": gp["name_en"] if gp else None
                }
                return result

    q_lower = clean_query.lower()
    raw_words = [w for w in re.split(r"[ ,?.!]+", clean_query) if len(w) >= 2]
    candidates = [w for w in raw_words if w.lower() not in STOP_WORDS and len(w) >= 3]

    terms = []
    if len(candidates) >= 2:
        terms.append(" ".join(candidates[:2]).lower())
    terms.extend([c.lower() for c in candidates])
    for c in list(candidates):
        c_low = c.lower()
        if c_low in NAME_ALIASES:
            terms.extend([a.lower() for a in NAME_ALIASES[c_low]])
    if not terms:
        terms = [q_lower]

    check_divisions_first = any(k in q_lower for k in ["division", "sambhag", "संभाग"]) and not any(
        any(alias in q_lower for alias in NAME_ALIASES.get(c.lower(), [c.lower()]))
        for c in candidates if any(d["name_en"].lower() == c.lower() for d in FALLBACK_DISTRICTS)
    )

    def match_district():
        for term in terms:
            for d in FALLBACK_DISTRICTS:
                d_en = d["name_en"].lower()
                d_hi = d["name_hi"]
                if term == d_en or term in d_en or term == d_hi or term in d_hi:
                    div = next((dv for dv in FALLBACK_DIVISIONS if dv["rajmaster_id"] == d.get("division_id")), None)
                    result["matched"] = True
                    result["entity_type"] = "District"
                    result["entity_name"] = d["name_en"]
                    result["lineage"] = {
                        "state": "Rajasthan",
                        "division": div["name_en"] if div else "Jodhpur Division",
                        "district": d["name_en"],
                        "collectorate": f"District Collectorate, {d['name_en']}",
                        "zila_parishad": f"Zila Parishad {d['name_en']}",
                        "zila_pramukh": d.get("zila_pramukh") or f"Zila Pramukh, {d['name_en']}",
                        "lgd_code": d.get("lgd_code") or 773
                    }
                    result["breadcrumbs"] = [x for x in ["Rajasthan", div["name_en"] if div else None, d["name_en"]] if x]
                    result["details"] = {
                        "district_english": d["name_en"],
                        "district_hindi": d["name_hi"],
                        "division": div["name_en"] if div else None,
                        "zila_pramukh": d.get("zila_pramukh"),
                        "collectorate": f"District Collectorate, {d['name_en']}",
                        "lgd_code": d.get("lgd_code")
                    }
                    return result
        return None

    def match_division():
        for term in terms:
            for dv in FALLBACK_DIVISIONS:
                dv_en = dv["name_en"].lower()
                dv_hi = dv["name_hi"]
                clean_dv_en = dv_en.replace(" division", "")
                if term in dv_en or term == clean_dv_en or term in dv_hi:
                    child_districts = [cd["name_en"] for cd in FALLBACK_DISTRICTS if cd.get("division_id") == dv["rajmaster_id"]]
                    result["matched"] = True
                    result["entity_type"] = "Division"
                    result["entity_name"] = dv["name_en"]
                    result["lineage"] = {
                        "state": "Rajasthan",
                        "division": dv["name_en"],
                        "divisional_commissioner": dv.get("divisional_commissioner"),
                        "districts": child_districts
                    }
                    result["breadcrumbs"] = ["Rajasthan", dv["name_en"]]
                    result["details"] = {
                        "division_english": dv["name_en"],
                        "division_hindi": dv["name_hi"],
                        "divisional_commissioner": dv.get("divisional_commissioner"),
                        "districts_count": len(child_districts),
                        "districts": child_districts,
                        "lgd_code": dv.get("lgd_code")
                    }
                    return result
        return None

    if check_divisions_first:
        m = match_division()
        if m: return m
        m = match_district()
        if m: return m
    else:
        m = match_district()
        if m: return m
        m = match_division()
        if m: return m

    # 4. Check State (Rajasthan or count queries)
    if any(k in q_lower for k in ["rajasthan", "division", "district", "sambhag", "संभाग"]):
        result["matched"] = True
        result["entity_type"] = "State"
        result["entity_name"] = "Rajasthan"
        result["lineage"] = {
            "state": "Rajasthan",
            "divisions_count": len(FALLBACK_DIVISIONS),
            "districts_count": len(FALLBACK_DISTRICTS)
        }
        result["breadcrumbs"] = ["Rajasthan", "10 Administrative Divisions"]
        result["details"] = {
            "state_english": "Rajasthan",
            "state_hindi": "राजस्थान",
            "chief_secretary": "Chief Secretary, Government of Rajasthan",
            "governance_details": "Government Secretariat, Jaipur",
            "divisions": [d["name_en"] for d in FALLBACK_DIVISIONS],
            "districts_count": len(FALLBACK_DISTRICTS),
            "lgd_code": 8
        }
        return result

    return result

async def lookup_geographic_hierarchy(query: str) -> Dict[str, Any]:
    """
    High-precision fuzzy & exact search across all 6 Rajasthan geographic and administrative levels,
    reconstructing full top-down and bottom-up lineage.
    """
    try:
        res = await _lookup_geographic_hierarchy_impl(query)
        if res.get("matched"):
            return res
    except Exception as e:
        logger.warning(f"DB search error in lookup_geographic_hierarchy: {e}")

    # Fallback to in-memory authoritative Rajasthan Master Directory
    return _lookup_in_memory_master(query)
