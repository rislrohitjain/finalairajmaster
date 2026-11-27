import asyncio
import json
import bcrypt
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import async_engine, AsyncSessionLocal, Base
from app.db.models import (
    State, Division, District, SubDivision, TehsilBlock,
    GramPanchayat, PanchayatWard, Village, UrbanLocalBody, UrbanWard,
    Pincode, Admin, LLMSetting, ScraperRun
)
from app.config import settings

DEFAULT_ADMIN_USER = "8946919241"
DEFAULT_ADMIN_PASS = "123456"

DEFAULT_SYSTEM_PROMPT = """You are the official Rajasthan Geographic & Administrative Master Data Engine.
You provide authoritative, strictly structured data for Rajasthan's 6 administrative and geographic tiers.

STRICT OPERATIONAL RULES:
1. NO FILLER OR CONVERSATIONAL WORDS: Never output greetings, apologies, or conversational filler (e.g., 'Hello', 'Namaste', 'Certainly', 'Sure', 'Here is the information', 'I would be happy to help').
2. NO CLOSING REMARKS: Never output pleasantries or chit-chat (e.g., 'Hope this helps!', 'Let me know if you need anything else', 'Feel free to ask').
3. STRICT STRUCTURED OUTPUT FORMAT: Always present administrative records in clean, predictable markdown:
   - Target Entity: Name (Tier)
   - Administrative Lineage (Top-Down): State -> Division -> District -> Sub-Division -> Tehsil/Block -> Gram Panchayat / ULB -> Village / Ward
   - Administrative Authority & Officials: Collectorate, Zila Pramukh, SDM Jurisdiction, Tehsildar, BDO, Sarpanch, Patwari
   - Administrative Codes: Official LGD Code, Pincode
   - Hierarchy Path: Single-line breadcrumb path
4. OUT-OF-SCOPE ENFORCEMENT: For non-geographic queries, return only the structured out-of-scope notice with the official helpline: 89988555525.
"""

DEFAULT_GREETING = """Welcome here chat with Jain's only"""

# 10 Divisions Seed Data
FALLBACK_DIVISIONS = [
    {"rajmaster_id": 1, "code": "D001", "name_en": "Ajmer Division", "name_hi": "अजमेर संभाग", "divisional_commissioner": "Divisional Commissioner, Ajmer", "lgd_code": 1},
    {"rajmaster_id": 2, "code": "D002", "name_en": "Bharatpur Division", "name_hi": "भरतपुर संभाग", "divisional_commissioner": "Divisional Commissioner, Bharatpur", "lgd_code": 2},
    {"rajmaster_id": 3, "code": "D003", "name_en": "Bikaner Division", "name_hi": "बीकानेर संभाग", "divisional_commissioner": "Divisional Commissioner, Bikaner", "lgd_code": 3},
    {"rajmaster_id": 4, "code": "D004", "name_en": "Jaipur Division", "name_hi": "जयपुर संभाग", "divisional_commissioner": "Divisional Commissioner, Jaipur", "lgd_code": 4},
    {"rajmaster_id": 5, "code": "D005", "name_en": "Jodhpur Division", "name_hi": "जोधपुर संभाग", "divisional_commissioner": "Divisional Commissioner, Jodhpur", "lgd_code": 5},
    {"rajmaster_id": 6, "code": "D006", "name_en": "Kota Division", "name_hi": "कोटा संभाग", "divisional_commissioner": "Divisional Commissioner, Kota", "lgd_code": 6},
    {"rajmaster_id": 7, "code": "D007", "name_en": "Udaipur Division", "name_hi": "उदयपुर संभाग", "divisional_commissioner": "Divisional Commissioner, Udaipur", "lgd_code": 7},
    {"rajmaster_id": 8, "code": "D008", "name_en": "Sikar Division", "name_hi": "सीकर संभाग", "divisional_commissioner": "Divisional Commissioner, Sikar", "lgd_code": 8},
    {"rajmaster_id": 9, "code": "D009", "name_en": "Pali Division", "name_hi": "पाली संभाग", "divisional_commissioner": "Divisional Commissioner, Pali", "lgd_code": 9},
    {"rajmaster_id": 10, "code": "D010", "name_en": "Banswara Division", "name_hi": "बांसवाड़ा संभाग", "divisional_commissioner": "Divisional Commissioner, Banswara", "lgd_code": 10},
]

# Core Districts Seed Data with Division Mapping
FALLBACK_DISTRICTS = [
    # Jaipur Division
    {"rajmaster_id": 1, "code": "101", "name_en": "Jaipur", "name_hi": "जयपुर", "division_id": 4, "lgd_code": 86, "zila_pramukh": "Zila Pramukh, Jaipur"},
    {"rajmaster_id": 2, "code": "102", "name_en": "Jaipur Rural", "name_hi": "जयपुर ग्रामीण", "division_id": 4, "lgd_code": 765, "zila_pramukh": "Zila Pramukh, Jaipur Rural"},
    {"rajmaster_id": 3, "code": "103", "name_en": "Dudu", "name_hi": "दूदू", "division_id": 4, "lgd_code": 766, "zila_pramukh": "Zila Pramukh, Dudu"},
    {"rajmaster_id": 4, "code": "104", "name_en": "Kotputli-Behror", "name_hi": "कोटपूतली-बहरोड़", "division_id": 4, "lgd_code": 767, "zila_pramukh": "Zila Pramukh, Kotputli-Behror"},
    {"rajmaster_id": 5, "code": "105", "name_en": "Dausa", "name_hi": "दौसा", "division_id": 4, "lgd_code": 88, "zila_pramukh": "Zila Pramukh, Dausa"},
    {"rajmaster_id": 6, "code": "106", "name_en": "Alwar", "name_hi": "अलवर", "division_id": 4, "lgd_code": 85, "zila_pramukh": "Zila Pramukh, Alwar"},
    {"rajmaster_id": 7, "code": "107", "name_en": "Khairthal-Tijara", "name_hi": "खैरथल-तिजारा", "division_id": 4, "lgd_code": 770, "zila_pramukh": "Zila Pramukh, Khairthal-Tijara"},

    # Jodhpur Division
    {"rajmaster_id": 8, "code": "108", "name_en": "Jodhpur", "name_hi": "जोधपुर", "division_id": 5, "lgd_code": 94, "zila_pramukh": "Zila Pramukh, Jodhpur"},
    {"rajmaster_id": 9, "code": "109", "name_en": "Jodhpur Rural", "name_hi": "जोधपुर ग्रामीण", "division_id": 5, "lgd_code": 771, "zila_pramukh": "Zila Pramukh, Jodhpur Rural"},
    {"rajmaster_id": 10, "code": "110", "name_en": "Phalodi", "name_hi": "फलोदी", "division_id": 5, "lgd_code": 772, "zila_pramukh": "Zila Pramukh, Phalodi"},
    {"rajmaster_id": 11, "code": "111", "name_en": "Jaisalmer", "name_hi": "जैसलमेर", "division_id": 5, "lgd_code": 93, "zila_pramukh": "Zila Pramukh, Jaisalmer"},
    {"rajmaster_id": 12, "code": "112", "name_en": "Barmer", "name_hi": "बाड़मेर", "division_id": 5, "lgd_code": 91, "zila_pramukh": "Zila Pramukh, Barmer"},
    {"rajmaster_id": 13, "code": "113", "name_en": "Balotra", "name_hi": "बालोतरा", "division_id": 5, "lgd_code": 773, "zila_pramukh": "Zila Pramukh, Balotra"},

    # Ajmer Division
    {"rajmaster_id": 14, "code": "114", "name_en": "Ajmer", "name_hi": "अजमेर", "division_id": 1, "lgd_code": 84, "zila_pramukh": "Zila Pramukh, Ajmer"},
    {"rajmaster_id": 15, "code": "115", "name_en": "Beawar", "name_hi": "ब्यावर", "division_id": 1, "lgd_code": 774, "zila_pramukh": "Zila Pramukh, Beawar"},
    {"rajmaster_id": 16, "code": "116", "name_en": "Kekri", "name_hi": "केकड़ी", "division_id": 1, "lgd_code": 775, "zila_pramukh": "Zila Pramukh, Kekri"},
    {"rajmaster_id": 17, "code": "117", "name_en": "Tonk", "name_hi": "टोंक", "division_id": 1, "lgd_code": 108, "zila_pramukh": "Zila Pramukh, Tonk"},
    {"rajmaster_id": 18, "code": "118", "name_en": "Nagaur", "name_hi": "नागौर", "division_id": 1, "lgd_code": 99, "zila_pramukh": "Zila Pramukh, Nagaur"},
    {"rajmaster_id": 19, "code": "119", "name_en": "Didwana-Kuchaman", "name_hi": "डीडवाना-कुचामन", "division_id": 1, "lgd_code": 776, "zila_pramukh": "Zila Pramukh, Didwana-Kuchaman"},
    {"rajmaster_id": 20, "code": "120", "name_en": "Shahpura", "name_hi": "शाहपुरा", "division_id": 1, "lgd_code": 777, "zila_pramukh": "Zila Pramukh, Shahpura"},

    # Bikaner Division
    {"rajmaster_id": 21, "code": "121", "name_en": "Bikaner", "name_hi": "बीकानेर", "division_id": 3, "lgd_code": 87, "zila_pramukh": "Zila Pramukh, Bikaner"},
    {"rajmaster_id": 22, "code": "122", "name_en": "Sri Ganganagar", "name_hi": "श्रीगंगानगर", "division_id": 3, "lgd_code": 92, "zila_pramukh": "Zila Pramukh, Sri Ganganagar"},
    {"rajmaster_id": 23, "code": "123", "name_en": "Anupgarh", "name_hi": "अनूपगढ़", "division_id": 3, "lgd_code": 778, "zila_pramukh": "Zila Pramukh, Anupgarh"},
    {"rajmaster_id": 24, "code": "124", "name_en": "Hanumangarh", "name_hi": "हनुमानगढ़", "division_id": 3, "lgd_code": 110, "zila_pramukh": "Zila Pramukh, Hanumangarh"},

    # Kota Division
    {"rajmaster_id": 25, "code": "125", "name_en": "Kota", "name_hi": "कोटा", "division_id": 6, "lgd_code": 97, "zila_pramukh": "Zila Pramukh, Kota"},
    {"rajmaster_id": 26, "code": "126", "name_en": "Bundi", "name_hi": "बूंदी", "division_id": 6, "lgd_code": 90, "zila_pramukh": "Zila Pramukh, Bundi"},
    {"rajmaster_id": 27, "code": "127", "name_en": "Baran", "name_hi": "बारां", "division_id": 6, "lgd_code": 89, "zila_pramukh": "Zila Pramukh, Baran"},
    {"rajmaster_id": 28, "code": "128", "name_en": "Jhalawar", "name_hi": "झालावाड़", "division_id": 6, "lgd_code": 95, "zila_pramukh": "Zila Pramukh, Jhalawar"},

    # Bharatpur Division
    {"rajmaster_id": 29, "code": "129", "name_en": "Bharatpur", "name_hi": "भरतपुर", "division_id": 2, "lgd_code": 98, "zila_pramukh": "Zila Pramukh, Bharatpur"},
    {"rajmaster_id": 30, "code": "130", "name_en": "Dholpur", "name_hi": "धौलपुर", "division_id": 2, "lgd_code": 109, "zila_pramukh": "Zila Pramukh, Dholpur"},
    {"rajmaster_id": 31, "code": "131", "name_en": "Karauli", "name_hi": "करौली", "division_id": 2, "lgd_code": 111, "zila_pramukh": "Zila Pramukh, Karauli"},
    {"rajmaster_id": 32, "code": "132", "name_en": "Deeg", "name_hi": "डीग", "division_id": 2, "lgd_code": 779, "zila_pramukh": "Zila Pramukh, Deeg"},
    {"rajmaster_id": 33, "code": "133", "name_en": "Sawai Madhopur", "name_hi": "सवाई माधोपुर", "division_id": 2, "lgd_code": 103, "zila_pramukh": "Zila Pramukh, Sawai Madhopur"},
    {"rajmaster_id": 34, "code": "134", "name_en": "Gangapur City", "name_hi": "गंगापुर सिटी", "division_id": 2, "lgd_code": 780, "zila_pramukh": "Zila Pramukh, Gangapur City"},

    # Udaipur Division
    {"rajmaster_id": 35, "code": "135", "name_en": "Udaipur", "name_hi": "उदयपुर", "division_id": 7, "lgd_code": 107, "zila_pramukh": "Zila Pramukh, Udaipur"},
    {"rajmaster_id": 36, "code": "136", "name_en": "Chittorgarh", "name_hi": "चित्तौड़गढ़", "division_id": 7, "lgd_code": 100, "zila_pramukh": "Zila Pramukh, Chittorgarh"},
    {"rajmaster_id": 37, "code": "137", "name_en": "Rajsamand", "name_hi": "राजसमंद", "division_id": 7, "lgd_code": 102, "zila_pramukh": "Zila Pramukh, Rajsamand"},
    {"rajmaster_id": 38, "code": "138", "name_en": "Bhilwara", "name_hi": "भीलवाड़ा", "division_id": 7, "lgd_code": 101, "zila_pramukh": "Zila Pramukh, Bhilwara"},
    {"rajmaster_id": 39, "code": "139", "name_en": "Salumbar", "name_hi": "सलूंबर", "division_id": 7, "lgd_code": 781, "zila_pramukh": "Zila Pramukh, Salumbar"},

    # Sikar Division
    {"rajmaster_id": 40, "code": "140", "name_en": "Sikar", "name_hi": "सीकर", "division_id": 8, "lgd_code": 105, "zila_pramukh": "Zila Pramukh, Sikar"},
    {"rajmaster_id": 41, "code": "141", "name_en": "Jhunjhunu", "name_hi": "झुंझुनूं", "division_id": 8, "lgd_code": 96, "zila_pramukh": "Zila Pramukh, Jhunjhunu"},
    {"rajmaster_id": 42, "code": "142", "name_en": "Churu", "name_hi": "चूरू", "division_id": 8, "lgd_code": 104, "zila_pramukh": "Zila Pramukh, Churu"},
    {"rajmaster_id": 43, "code": "143", "name_en": "Neem Ka Thana", "name_hi": "नीम का थाना", "division_id": 8, "lgd_code": 782, "zila_pramukh": "Zila Pramukh, Neem Ka Thana"},

    # Pali Division
    {"rajmaster_id": 44, "code": "144", "name_en": "Pali", "name_hi": "पाली", "division_id": 9, "lgd_code": 106, "zila_pramukh": "Zila Pramukh, Pali"},
    {"rajmaster_id": 45, "code": "145", "name_en": "Jalore", "name_hi": "जालोर", "division_id": 9, "lgd_code": 112, "zila_pramukh": "Zila Pramukh, Jalore"},
    {"rajmaster_id": 46, "code": "146", "name_en": "Sanchore", "name_hi": "सांचौर", "division_id": 9, "lgd_code": 783, "zila_pramukh": "Zila Pramukh, Sanchore"},
    {"rajmaster_id": 47, "code": "147", "name_en": "Sirohi", "name_hi": "सिरोही", "division_id": 9, "lgd_code": 113, "zila_pramukh": "Zila Pramukh, Sirohi"},

    # Banswara Division
    {"rajmaster_id": 48, "code": "148", "name_en": "Banswara", "name_hi": "बांसवाड़ा", "division_id": 10, "lgd_code": 114, "zila_pramukh": "Zila Pramukh, Banswara"},
    {"rajmaster_id": 49, "code": "149", "name_en": "Dungarpur", "name_hi": "डूंगरपुर", "division_id": 10, "lgd_code": 115, "zila_pramukh": "Zila Pramukh, Dungarpur"},
    {"rajmaster_id": 50, "code": "150", "name_en": "Pratapgarh", "name_hi": "प्रतापगढ़", "division_id": 10, "lgd_code": 116, "zila_pramukh": "Zila Pramukh, Pratapgarh"}
]

FALLBACK_SUBDIVISIONS = [
    {"rajmaster_id": 1, "district_id": 1, "code": "SD01", "name_en": "Jaipur", "name_hi": "जयपुर", "sdm_jurisdiction": "SDM Office Jaipur City", "lgd_code": 1001},
    {"rajmaster_id": 2, "district_id": 1, "code": "SD02", "name_en": "Sanganer", "name_hi": "सांगानेर", "sdm_jurisdiction": "SDM Office Sanganer", "lgd_code": 1002},
    {"rajmaster_id": 3, "district_id": 1, "code": "SD03", "name_en": "Amer", "name_hi": "आमेर", "sdm_jurisdiction": "SDM Office Amer", "lgd_code": 1003},
    {"rajmaster_id": 4, "district_id": 8, "code": "SD04", "name_en": "Jodhpur", "name_hi": "जोधपुर", "sdm_jurisdiction": "SDM Office Jodhpur City", "lgd_code": 1004},
    {"rajmaster_id": 5, "district_id": 14, "code": "SD05", "name_en": "Ajmer", "name_hi": "अजमेर", "sdm_jurisdiction": "SDM Office Ajmer City", "lgd_code": 1005},
    {"rajmaster_id": 6, "district_id": 25, "code": "SD06", "name_en": "Kota", "name_hi": "कोटा", "sdm_jurisdiction": "SDM Office Kota City", "lgd_code": 1006},
    {"rajmaster_id": 7, "district_id": 35, "code": "SD07", "name_en": "Girwa (Udaipur)", "name_hi": "गिर्वा (उदयपुर)", "sdm_jurisdiction": "SDM Office Girwa", "lgd_code": 1007},
    {"rajmaster_id": 8, "district_id": 21, "code": "SD08", "name_en": "Bikaner", "name_hi": "बीकानेर", "sdm_jurisdiction": "SDM Office Bikaner City", "lgd_code": 1008},
    {"rajmaster_id": 9, "district_id": 29, "code": "SD09", "name_en": "Bharatpur", "name_hi": "भरतपुर", "sdm_jurisdiction": "SDM Office Bharatpur City", "lgd_code": 1009},
    {"rajmaster_id": 10, "district_id": 40, "code": "SD10", "name_en": "Sikar", "name_hi": "सीकर", "sdm_jurisdiction": "SDM Office Sikar City", "lgd_code": 1010},
]

FALLBACK_TEHSILS_BLOCKS = [
    {"rajmaster_id": 1, "district_id": 1, "sub_division_id": 1, "code": "T01", "name_en": "Jaipur", "name_hi": "जयपुर", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Jaipur", "lgd_code": 2001},
    {"rajmaster_id": 2, "district_id": 1, "sub_division_id": 2, "code": "T02", "name_en": "Sanganer", "name_hi": "सांगानेर", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Sanganer", "lgd_code": 2002},
    {"rajmaster_id": 3, "district_id": 1, "sub_division_id": 3, "code": "T03", "name_en": "Amer", "name_hi": "आमेर", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Amer", "lgd_code": 2003},
    {"rajmaster_id": 4, "district_id": 1, "sub_division_id": 2, "code": "B01", "name_en": "Sanganer Panchayat Samiti", "name_hi": "सांगानेर पंचायत समिति", "entity_type": "Panchayat Samiti / Block", "bdo_details": "BDO Sanganer", "lgd_code": 2004},
    {"rajmaster_id": 5, "district_id": 1, "sub_division_id": 3, "code": "B02", "name_en": "Amer Panchayat Samiti", "name_hi": "आमेर पंचायत समिति", "entity_type": "Panchayat Samiti / Block", "bdo_details": "BDO Amer", "lgd_code": 2005},
    {"rajmaster_id": 6, "district_id": 8, "sub_division_id": 4, "code": "T04", "name_en": "Jodhpur", "name_hi": "जोधपुर", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Jodhpur", "lgd_code": 2006},
    {"rajmaster_id": 7, "district_id": 14, "sub_division_id": 5, "code": "T05", "name_en": "Ajmer", "name_hi": "अजमेर", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Ajmer", "lgd_code": 2007},
    {"rajmaster_id": 8, "district_id": 25, "sub_division_id": 6, "code": "T06", "name_en": "Ladpura", "name_hi": "लाडपुरा", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Ladpura", "lgd_code": 2008},
    {"rajmaster_id": 9, "district_id": 35, "sub_division_id": 7, "code": "T07", "name_en": "Girwa", "name_hi": "गिर्वा", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Girwa", "lgd_code": 2009},
    {"rajmaster_id": 10, "district_id": 40, "sub_division_id": 10, "code": "T08", "name_en": "Sikar", "name_hi": "सीकर", "entity_type": "Tehsil", "tehsildar_details": "Tehsildar Sikar", "lgd_code": 2010},
]

FALLBACK_GRAM_PANCHAYATS = [
    {"rajmaster_id": 1, "district_id": 1, "tehsil_block_id": 4, "code": "GP01", "name_en": "Muhana", "name_hi": "मुहाना", "sarpanch": "Sarpanch Muhana", "lgd_code": 3001},
    {"rajmaster_id": 2, "district_id": 1, "tehsil_block_id": 4, "code": "GP02", "name_en": "Nevta", "name_hi": "नेवटा", "sarpanch": "Sarpanch Nevta", "lgd_code": 3002},
    {"rajmaster_id": 3, "district_id": 1, "tehsil_block_id": 4, "code": "GP03", "name_en": "Vatika", "name_hi": "वाटिका", "sarpanch": "Sarpanch Vatika", "lgd_code": 3003},
    {"rajmaster_id": 4, "district_id": 1, "tehsil_block_id": 5, "code": "GP04", "name_en": "Kukas", "name_hi": "कूकस", "sarpanch": "Sarpanch Kukas", "lgd_code": 3004},
    {"rajmaster_id": 5, "district_id": 1, "tehsil_block_id": 5, "code": "GP05", "name_en": "Achrol", "name_hi": "अचरोल", "sarpanch": "Sarpanch Achrol", "lgd_code": 3005},
    {"rajmaster_id": 6, "district_id": 14, "tehsil_block_id": 7, "code": "GP06", "name_en": "Gegal", "name_hi": "गेगल", "sarpanch": "Sarpanch Gegal", "lgd_code": 3006},
    {"rajmaster_id": 7, "district_id": 8, "tehsil_block_id": 6, "code": "GP07", "name_en": "Salawas", "name_hi": "सालावास", "sarpanch": "Sarpanch Salawas", "lgd_code": 3007},
    {"rajmaster_id": 8, "district_id": 35, "tehsil_block_id": 9, "code": "GP08", "name_en": "Badi", "name_hi": "बड़ी", "sarpanch": "Sarpanch Badi", "lgd_code": 3008},
]

FALLBACK_VILLAGES = [
    {"rajmaster_id": 1, "district_id": 1, "tehsil_block_id": 2, "gram_panchayat_id": 1, "code": "V01", "name_en": "Muhana", "name_hi": "मुहाना", "patwar_circle": "Muhana Patwar Circle", "patwari": "Patwari Muhana", "pincode": "302029", "lgd_code": 4001},
    {"rajmaster_id": 2, "district_id": 1, "tehsil_block_id": 2, "gram_panchayat_id": 2, "code": "V02", "name_en": "Nevta", "name_hi": "नेवटा", "patwar_circle": "Nevta Patwar Circle", "patwari": "Patwari Nevta", "pincode": "302029", "lgd_code": 4002},
    {"rajmaster_id": 3, "district_id": 1, "tehsil_block_id": 2, "gram_panchayat_id": 3, "code": "V03", "name_en": "Vatika", "name_hi": "वाटिका", "patwar_circle": "Vatika Patwar Circle", "patwari": "Patwari Vatika", "pincode": "303905", "lgd_code": 4003},
    {"rajmaster_id": 4, "district_id": 1, "tehsil_block_id": 3, "gram_panchayat_id": 4, "code": "V04", "name_en": "Kukas", "name_hi": "कूकस", "patwar_circle": "Kukas Patwar Circle", "patwari": "Patwari Kukas", "pincode": "302028", "lgd_code": 4004},
    {"rajmaster_id": 5, "district_id": 1, "tehsil_block_id": 3, "gram_panchayat_id": 5, "code": "V05", "name_en": "Achrol", "name_hi": "अचरोल", "patwar_circle": "Achrol Patwar Circle", "patwari": "Patwari Achrol", "pincode": "303002", "lgd_code": 4005},
    {"rajmaster_id": 6, "district_id": 14, "tehsil_block_id": 7, "gram_panchayat_id": 6, "code": "V06", "name_en": "Gegal", "name_hi": "गेगल", "patwar_circle": "Gegal Circle", "patwari": "Patwari Gegal", "pincode": "305023", "lgd_code": 4006},
    {"rajmaster_id": 7, "district_id": 8, "tehsil_block_id": 6, "gram_panchayat_id": 7, "code": "V07", "name_en": "Salawas", "name_hi": "सालावास", "patwar_circle": "Salawas Circle", "patwari": "Patwari Salawas", "pincode": "342012", "lgd_code": 4007},
    {"rajmaster_id": 8, "district_id": 35, "tehsil_block_id": 9, "gram_panchayat_id": 8, "code": "V08", "name_en": "Badi", "name_hi": "बड़ी", "patwar_circle": "Badi Circle", "patwari": "Patwari Badi", "pincode": "313011", "lgd_code": 4008},
]

FALLBACK_ULBS = [
    {"rajmaster_id": 1, "district_id": 1, "code": "ULB01", "name_en": "Jaipur Greater Municipal Corporation", "name_hi": "नगर निगम जयपुर ग्रेटर", "ulb_type": "Nagar Nigam", "city_name": "Jaipur", "pincode": "302015", "lgd_code": 5001},
    {"rajmaster_id": 2, "district_id": 1, "code": "ULB02", "name_en": "Jaipur Heritage Municipal Corporation", "name_hi": "नगर निगम जयपुर हेरिटेज", "ulb_type": "Nagar Nigam", "city_name": "Jaipur", "pincode": "302002", "lgd_code": 5002},
    {"rajmaster_id": 3, "district_id": 8, "code": "ULB03", "name_en": "Jodhpur Municipal Corporation (North)", "name_hi": "नगर निगम जोधपुर (उत्तर)", "ulb_type": "Nagar Nigam", "city_name": "Jodhpur", "pincode": "342001", "lgd_code": 5003},
    {"rajmaster_id": 4, "district_id": 8, "code": "ULB04", "name_en": "Jodhpur Municipal Corporation (South)", "name_hi": "नगर निगम जोधपुर (दक्षिण)", "ulb_type": "Nagar Nigam", "city_name": "Jodhpur", "pincode": "342003", "lgd_code": 5004},
    {"rajmaster_id": 5, "district_id": 25, "code": "ULB05", "name_en": "Kota Municipal Corporation (North)", "name_hi": "नगर निगम कोटा (उत्तर)", "ulb_type": "Nagar Nigam", "city_name": "Kota", "pincode": "324001", "lgd_code": 5005},
    {"rajmaster_id": 6, "district_id": 14, "code": "ULB06", "name_en": "Ajmer Municipal Corporation", "name_hi": "नगर निगम अजमेर", "ulb_type": "Nagar Nigam", "city_name": "Ajmer", "pincode": "305001", "lgd_code": 5006},
    {"rajmaster_id": 7, "district_id": 35, "code": "ULB07", "name_en": "Udaipur Municipal Corporation", "name_hi": "नगर निगम उदयपुर", "ulb_type": "Nagar Nigam", "city_name": "Udaipur", "pincode": "313001", "lgd_code": 5007},
    {"rajmaster_id": 8, "district_id": 21, "code": "ULB08", "name_en": "Bikaner Municipal Corporation", "name_hi": "नगर निगम बीकानेर", "ulb_type": "Nagar Nigam", "city_name": "Bikaner", "pincode": "334001", "lgd_code": 5008},
    {"rajmaster_id": 9, "district_id": 40, "code": "ULB09", "name_en": "Sikar Municipal Council", "name_hi": "नगर परिषद सीकर", "ulb_type": "Nagar Parishad", "city_name": "Sikar", "pincode": "332001", "lgd_code": 5009},
    {"rajmaster_id": 10, "district_id": 15, "code": "ULB10", "name_en": "Beawar Municipal Council", "name_hi": "नगर परिषद ब्यावर", "ulb_type": "Nagar Parishad", "city_name": "Beawar", "pincode": "305901", "lgd_code": 5010},
]

FALLBACK_URBAN_WARDS = [
    {"rajmaster_id": 1, "ulb_id": 1, "ward_number": "Ward 1", "name_en": "Malviya Nagar Sector 1", "name_hi": "मालवीय नगर सेक्टर 1", "councillor_parshad": "Parshad Ward 1", "pincode": "302017", "lgd_code": 6001},
    {"rajmaster_id": 2, "ulb_id": 1, "ward_number": "Ward 2", "name_en": "Mansarovar Sector 3", "name_hi": "मानसरोवर सेक्टर 3", "councillor_parshad": "Parshad Ward 2", "pincode": "302020", "lgd_code": 6002},
    {"rajmaster_id": 3, "ulb_id": 2, "ward_number": "Ward 1", "name_en": "Chokdi Ramchandra Ji", "name_hi": "चौकड़ी रामचंद्र जी", "councillor_parshad": "Parshad Ward 1", "pincode": "302002", "lgd_code": 6003},
    {"rajmaster_id": 4, "ulb_id": 6, "ward_number": "Ward 10", "name_en": "Civil Lines Ajmer", "name_hi": "सिविल लाइन्स अजमेर", "councillor_parshad": "Parshad Ward 10", "pincode": "305001", "lgd_code": 6004},
]

FALLBACK_PINCODES = [
    # --- 1. Jaipur Division (Jaipur, Jaipur Rural, Dudu, Kotputli-Behror, Dausa, Alwar, Khairthal-Tijara) ---
    # Jaipur Urban Core (302001 - 302040)
    {"pincode": "302001", "city_or_village": "Jaipur GPO / M.I. Road / Ashok Nagar", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 2},
    {"pincode": "302002", "city_or_village": "Jaipur City / Johari Bazar / Badi Chaupar", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 2},
    {"pincode": "302003", "city_or_village": "C-Scheme / Bhagwan Das Road / Civil Lines", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302004", "city_or_village": "Adarsh Nagar / Raja Park / Tilak Nagar", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302005", "city_or_village": "Bais Godam / Hawa Sadak / Sudarshanpura", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302006", "city_or_village": "Gopalpura Bypass / Tonk Road / Bajaj Nagar", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302007", "city_or_village": "Shastri Nagar / Subhash Nagar / Kanwatia Hospital", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 2},
    {"pincode": "302008", "city_or_village": "Vidyadhar Nagar / Sector 1-10", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302009", "city_or_village": "Chandpole Bazar / Purani Basti", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 2},
    {"pincode": "302010", "city_or_village": "Durgapura / Railway Station / Maharani Farm", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302011", "city_or_village": "Goner Road / Luniyawas / Transport Nagar", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302012", "city_or_village": "Jhotwara / Kalwar Road / Khatipura", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302013", "city_or_village": "Bani Park / Collectorate Circle / Sindhi Camp", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 2},
    {"pincode": "302014", "city_or_village": "Brahampuri / Govind Dev Ji Temple", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 2},
    {"pincode": "302015", "city_or_village": "Tonk Phatak / Gandhi Nagar / Barkat Nagar", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302016", "city_or_village": "Ambawari / Murlipura / Sikar Road", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302017", "city_or_village": "Malviya Nagar / D-Block / Calgiri Marg", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302018", "city_or_village": "Mansarovar Sector 1-6 / Shipra Path", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302019", "city_or_village": "Vaishali Nagar / Chitrakoot / Queens Road", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302020", "city_or_village": "Mansarovar / New Sanganer Road / Sector 7-12", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302021", "city_or_village": "Vaishali West / Gandhi Path / Panchyawala", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302022", "city_or_village": "Sitapura Industrial Area / RIICO Phase 1-4", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302023", "city_or_village": "Vidyadhar Nagar Central / Sector 2-5", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302024", "city_or_village": "Mahesh Nagar / 80 Feet Road", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302025", "city_or_village": "Jawahar Nagar / Sector 1-7", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302026", "city_or_village": "Jagatpura / Malviya Industrial Area / Model Town", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302027", "city_or_village": "Amer Fort Heritage / Jal Mahal Area", "district_id": 1, "division_id": 4, "tehsil_block_id": 3, "ulb_id": 2},
    {"pincode": "302028", "city_or_village": "Amer Town / Kukas RIICO Industrial Hub", "district_id": 1, "division_id": 4, "tehsil_block_id": 3, "gram_panchayat_id": 4},
    {"pincode": "302029", "city_or_village": "Sanganer Bazar / Muhana Mandi / Diggi Road", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1, "gram_panchayat_id": 1},
    {"pincode": "302030", "city_or_village": "Sanganer Airport / Terminal 2 / Jawahar Circle", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302031", "city_or_village": "Sirsi Road / Meenawala / Kanakpura", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302032", "city_or_village": "VKI Area / Vishwakarma Industrial Area Road 1-14", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302033", "city_or_village": "Pratap Nagar / Sector 8-19 / Haldi Ghati Marg", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302034", "city_or_village": "Bhakrota / Ajmer Road / Mahindra World City", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302035", "city_or_village": "Mahapura / SEZ Zone / Ajmer Expressway", "district_id": 1, "division_id": 4, "tehsil_block_id": 2, "ulb_id": 1},
    {"pincode": "302036", "city_or_village": "Hathoj / Kalwar Road Rural Area", "district_id": 1, "division_id": 4, "tehsil_block_id": 1},
    {"pincode": "302037", "city_or_village": "Bagwada Industrial Hub / Amer Rural", "district_id": 1, "division_id": 4, "tehsil_block_id": 3},
    {"pincode": "302038", "city_or_village": "Harmada / Chomu Road Bypass", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302039", "city_or_village": "Bindayaka Industrial Area / Sirsi", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},
    {"pincode": "302040", "city_or_village": "Murlipura Scheme / Dadi Ka Phatak", "district_id": 1, "division_id": 4, "tehsil_block_id": 1, "ulb_id": 1},

    # Jaipur Rural / Sub-Divisions (303xxx)
    {"pincode": "303001", "city_or_village": "Bassi Head Post Office / Railway Station", "district_id": 2, "division_id": 4},
    {"pincode": "303002", "city_or_village": "Achrol / Chandwaji NH-48 Educational Valley", "district_id": 2, "division_id": 4, "tehsil_block_id": 3, "gram_panchayat_id": 5},
    {"pincode": "303004", "city_or_village": "Jamwa Ramgarh Dam / Sub-Division HQ", "district_id": 2, "division_id": 4},
    {"pincode": "303005", "city_or_village": "Chaksu City / Sheetla Mata Mandir", "district_id": 2, "division_id": 4},
    {"pincode": "303006", "city_or_village": "Dhanota / Shahpura Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303007", "city_or_village": "Dudu District HQ & Sub-Division", "district_id": 3, "division_id": 4},
    {"pincode": "303008", "city_or_village": "Sambhar Lake / Salt City & Shakambhari", "district_id": 2, "division_id": 4},
    {"pincode": "303009", "city_or_village": "Jobner / Sri Karan Narendra Agri University", "district_id": 2, "division_id": 4},
    {"pincode": "303012", "city_or_village": "Kotkhawda Tehsil & Mandi", "district_id": 2, "division_id": 4},
    {"pincode": "303102", "city_or_village": "Kishangarh Renwal Grain Mandi", "district_id": 2, "division_id": 4},
    {"pincode": "303103", "city_or_village": "Chomu City / Radha Swami Bagh", "district_id": 2, "division_id": 4},
    {"pincode": "303104", "city_or_village": "Govindgarh Grain Mandi & Block HQ", "district_id": 2, "division_id": 4},
    {"pincode": "303105", "city_or_village": "Morija / Iron Ore Mining Zone", "district_id": 2, "division_id": 4},
    {"pincode": "303106", "city_or_village": "Samod Heritage Palace & Village", "district_id": 2, "division_id": 4},
    {"pincode": "303107", "city_or_village": "Chitwadi / Chomu Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303108", "city_or_village": "Phulera Railway Junction & Town", "district_id": 2, "division_id": 4},
    {"pincode": "303109", "city_or_village": "Bichun Fort & Heritage Tehsil", "district_id": 3, "division_id": 4},
    {"pincode": "303110", "city_or_village": "Narayana Dadu Dayal Peeth", "district_id": 2, "division_id": 4},
    {"pincode": "303301", "city_or_village": "Dausa Border / Bassi Rural Corridor", "district_id": 2, "division_id": 4},
    {"pincode": "303328", "city_or_village": "Kotputli City / District HQ & Cement Zone", "district_id": 4, "division_id": 4},
    {"pincode": "303338", "city_or_village": "Paota Sub-Division & Mining", "district_id": 4, "division_id": 4},
    {"pincode": "303601", "city_or_village": "Viratnagar / Buddhist Stupa & Ashoka Inscriptions", "district_id": 2, "division_id": 4},
    {"pincode": "303602", "city_or_village": "Med / Viratnagar Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303603", "city_or_village": "Bairath Historical Heritage", "district_id": 2, "division_id": 4},
    {"pincode": "303604", "city_or_village": "Bhabhru Inscription Site", "district_id": 2, "division_id": 4},
    {"pincode": "303701", "city_or_village": "Manoharpur Industrial Area", "district_id": 2, "division_id": 4},
    {"pincode": "303702", "city_or_village": "Bassi Tehsil / RIICO Industrial Area", "district_id": 2, "division_id": 4},
    {"pincode": "303704", "city_or_village": "Kanota Fort & Heritage Town", "district_id": 2, "division_id": 4},
    {"pincode": "303706", "city_or_village": "Toonga Historical Battlefield & Mandi", "district_id": 2, "division_id": 4},
    {"pincode": "303712", "city_or_village": "Rohini / Bassi Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303801", "city_or_village": "Bhojpura Kalan / Phulera Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303803", "city_or_village": "Goner Jagannath Ji Temple & Sub-Tehsil", "district_id": 2, "division_id": 4},
    {"pincode": "303804", "city_or_village": "Dabla Kalan / Jamwa Ramgarh", "district_id": 2, "division_id": 4},
    {"pincode": "303805", "city_or_village": "Andhi Stone Mining Zone", "district_id": 2, "division_id": 4},
    {"pincode": "303806", "city_or_village": "Kalyan Pura / Shahpura Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303807", "city_or_village": "Raithal Village / Chomu", "district_id": 2, "division_id": 4},
    {"pincode": "303901", "city_or_village": "Bagru Industrial Area / Sanganeri Handblock Print", "district_id": 2, "division_id": 4},
    {"pincode": "303902", "city_or_village": "Jirota / Sanganer Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303903", "city_or_village": "Shivdaspura Railway Station / Tonk Road", "district_id": 2, "division_id": 4},
    {"pincode": "303904", "city_or_village": "Madhorajpura Tehsil HQ", "district_id": 2, "division_id": 4},
    {"pincode": "303905", "city_or_village": "Vatika / Rural Sanganer Agricultural Hub", "district_id": 2, "division_id": 4, "tehsil_block_id": 2, "gram_panchayat_id": 3},
    {"pincode": "303908", "city_or_village": "Titariya / Chaksu Rural", "district_id": 2, "division_id": 4},
    {"pincode": "303007", "city_or_village": "Dudu Collectorate & Town", "district_id": 3, "division_id": 4},
    {"pincode": "303328", "city_or_village": "Kotputli City / District HQ", "district_id": 4, "division_id": 4},
    {"pincode": "301402", "city_or_village": "Behror Sub-Division", "district_id": 4, "division_id": 4},
    {"pincode": "303303", "city_or_village": "Dausa Head Post Office", "district_id": 5, "division_id": 4},
    {"pincode": "303313", "city_or_village": "Bandikui Junction", "district_id": 5, "division_id": 4},
    {"pincode": "303507", "city_or_village": "Lalsot Tehsil", "district_id": 5, "division_id": 4},
    {"pincode": "301001", "city_or_village": "Alwar City / Hope Circus", "district_id": 6, "division_id": 4},
    {"pincode": "301019", "city_or_village": "Matsya Industrial Area, Alwar", "district_id": 6, "division_id": 4},
    {"pincode": "301404", "city_or_village": "Rajgarh Tehsil, Alwar", "district_id": 6, "division_id": 4},
    {"pincode": "301701", "city_or_village": "Khairthal Mandi & District HQ", "district_id": 7, "division_id": 4},
    {"pincode": "301030", "city_or_village": "Bhiwadi Industrial Corridor", "district_id": 7, "division_id": 4},
    {"pincode": "301026", "city_or_village": "Tijara Sub-Division", "district_id": 7, "division_id": 4},

    # --- 2. Jodhpur Division (Jodhpur, Jodhpur Rural, Phalodi, Jaisalmer, Barmer, Balotra) ---
    {"pincode": "342001", "city_or_village": "Jodhpur City / Head Post Office", "district_id": 8, "division_id": 5, "tehsil_block_id": 6, "ulb_id": 3},
    {"pincode": "342003", "city_or_village": "Sardarpura, Jodhpur", "district_id": 8, "division_id": 5, "tehsil_block_id": 6, "ulb_id": 4},
    {"pincode": "342005", "city_or_village": "Ratanada / Air Force Area, Jodhpur", "district_id": 8, "division_id": 5, "tehsil_block_id": 6},
    {"pincode": "342006", "city_or_village": "Residency Road / Shastri Nagar, Jodhpur", "district_id": 8, "division_id": 5, "tehsil_block_id": 6},
    {"pincode": "342008", "city_or_village": "Kudi Bhagtasni Housing Board, Jodhpur", "district_id": 8, "division_id": 5, "tehsil_block_id": 6},
    {"pincode": "342011", "city_or_village": "Basni Industrial Area Phase 1-2, Jodhpur", "district_id": 8, "division_id": 5, "tehsil_block_id": 6},
    {"pincode": "342012", "city_or_village": "Salawas Craft Village", "district_id": 9, "division_id": 5, "tehsil_block_id": 6, "gram_panchayat_id": 7},
    {"pincode": "342015", "city_or_village": "Nandri / Banar Road, Jodhpur", "district_id": 8, "division_id": 5},
    {"pincode": "342027", "city_or_village": "Mandore Garden & Heritage Area", "district_id": 8, "division_id": 5},
    {"pincode": "342301", "city_or_village": "Bilara Tehsil", "district_id": 9, "division_id": 5},
    {"pincode": "342305", "city_or_village": "Osian Temple Town", "district_id": 9, "division_id": 5},
    {"pincode": "342307", "city_or_village": "Bhopalgarh Sub-Division", "district_id": 9, "division_id": 5},
    {"pincode": "342304", "city_or_village": "Phalodi City / Solar Hub", "district_id": 10, "division_id": 5},
    {"pincode": "345001", "city_or_village": "Jaisalmer Fort / Golden City", "district_id": 11, "division_id": 5},
    {"pincode": "345021", "city_or_village": "Pokhran Nuclear Test Site & Town", "district_id": 11, "division_id": 5},
    {"pincode": "344001", "city_or_village": "Barmer City / Refinery Zone", "district_id": 12, "division_id": 5},
    {"pincode": "344031", "city_or_village": "Baytu Sub-Division", "district_id": 12, "division_id": 5},
    {"pincode": "344704", "city_or_village": "Chohtan Desert Tehsil", "district_id": 12, "division_id": 5},
    {"pincode": "344022", "city_or_village": "Balotra City / Textile Hub", "district_id": 13, "division_id": 5},
    {"pincode": "344026", "city_or_village": "Siwana Fort & Tehsil", "district_id": 13, "division_id": 5},
    {"pincode": "344032", "city_or_village": "Sindhari Sub-Division", "district_id": 13, "division_id": 5},

    # --- 3. Ajmer Division (Ajmer, Beawar, Kekri, Tonk, Nagaur, Didwana-Kuchaman, Shahpura) ---
    {"pincode": "305001", "city_or_village": "Ajmer Head Post Office / Dargah", "district_id": 14, "division_id": 1, "tehsil_block_id": 7, "ulb_id": 6},
    {"pincode": "305002", "city_or_village": "Kaiserganj / Railway Colony, Ajmer", "district_id": 14, "division_id": 1, "tehsil_block_id": 7},
    {"pincode": "305003", "city_or_village": "Makhupura Industrial Area, Ajmer", "district_id": 14, "division_id": 1, "tehsil_block_id": 7},
    {"pincode": "305004", "city_or_village": "Adarsh Nagar, Ajmer", "district_id": 14, "division_id": 1, "tehsil_block_id": 7},
    {"pincode": "305006", "city_or_village": "Civil Lines / Collectorate, Ajmer", "district_id": 14, "division_id": 1, "tehsil_block_id": 7},
    {"pincode": "305007", "city_or_village": "Vaishali Nagar / Ana Sagar, Ajmer", "district_id": 14, "division_id": 1, "tehsil_block_id": 7},
    {"pincode": "305008", "city_or_village": "Pushkar Holy Lake Town", "district_id": 14, "division_id": 1, "tehsil_block_id": 7},
    {"pincode": "305023", "city_or_village": "Gegal Industrial Estate", "district_id": 14, "division_id": 1, "tehsil_block_id": 7, "gram_panchayat_id": 6},
    {"pincode": "305404", "city_or_village": "Kishangarh Marble City", "district_id": 14, "division_id": 1},
    {"pincode": "305405", "city_or_village": "Madanganj Kishangarh", "district_id": 14, "division_id": 1},
    {"pincode": "305801", "city_or_village": "Nasirabad Cantonment", "district_id": 14, "division_id": 1},
    {"pincode": "305901", "city_or_village": "Beawar City / Cement Capital", "district_id": 15, "division_id": 1, "ulb_id": 10},
    {"pincode": "305408", "city_or_village": "Kekri City / District HQ", "district_id": 16, "division_id": 1},
    {"pincode": "304001", "city_or_village": "Tonk City / Nawab Town", "district_id": 17, "division_id": 1},
    {"pincode": "304021", "city_or_village": "Niwai / Banasthali Vidyapith", "district_id": 17, "division_id": 1},
    {"pincode": "304502", "city_or_village": "Malpura Sub-Division", "district_id": 17, "division_id": 1},
    {"pincode": "304804", "city_or_village": "Deoli Industrial Town", "district_id": 17, "division_id": 1},
    {"pincode": "341001", "city_or_village": "Nagaur City / Fort Area", "district_id": 18, "division_id": 1},
    {"pincode": "341021", "city_or_village": "Merta City / Meera Bai Dham", "district_id": 18, "division_id": 1},
    {"pincode": "341303", "city_or_village": "Didwana Salt Lake City", "district_id": 19, "division_id": 1},
    {"pincode": "341508", "city_or_village": "Kuchaman City / Educational Valley", "district_id": 19, "division_id": 1},
    {"pincode": "341519", "city_or_village": "Makrana White Marble Capital", "district_id": 19, "division_id": 1},
    {"pincode": "311404", "city_or_village": "Shahpura Phad Painting City", "district_id": 20, "division_id": 1},

    # --- 4. Bikaner Division (Bikaner, Sri Ganganagar, Anupgarh, Hanumangarh) ---
    {"pincode": "334001", "city_or_village": "Bikaner City / Kote Gate", "district_id": 21, "division_id": 3, "ulb_id": 8},
    {"pincode": "334002", "city_or_village": "Sadul Colony / Karni Nagar, Bikaner", "district_id": 21, "division_id": 3},
    {"pincode": "334003", "city_or_village": "Ganga Shahar / Bhinnsar, Bikaner", "district_id": 21, "division_id": 3},
    {"pincode": "334004", "city_or_village": "Lalgarh Palace Area, Bikaner", "district_id": 21, "division_id": 3},
    {"pincode": "334401", "city_or_village": "Nokha Mandi", "district_id": 21, "division_id": 3},
    {"pincode": "334603", "city_or_village": "Lunkaransar Saline Basin", "district_id": 21, "division_id": 3},
    {"pincode": "334803", "city_or_village": "Sri Dungargarh Sub-Division", "district_id": 21, "division_id": 3},
    {"pincode": "335001", "city_or_village": "Sri Ganganagar City / Food Basket", "district_id": 22, "division_id": 3},
    {"pincode": "335025", "city_or_village": "Suratgarh Thermal Power Station", "district_id": 22, "division_id": 3},
    {"pincode": "335701", "city_or_village": "Anupgarh Border City & District HQ", "district_id": 23, "division_id": 3},
    {"pincode": "335703", "city_or_village": "Raisinghnagar Mandi", "district_id": 23, "division_id": 3},
    {"pincode": "335512", "city_or_village": "Hanumangarh Junction", "district_id": 24, "division_id": 3},
    {"pincode": "335513", "city_or_village": "Hanumangarh Town / Bhatner Fort", "district_id": 24, "division_id": 3},
    {"pincode": "335504", "city_or_village": "Nohar Grain Market", "district_id": 24, "division_id": 3},
    {"pincode": "335511", "city_or_village": "Bhadra Sub-Division", "district_id": 24, "division_id": 3},

    # --- 5. Kota Division (Kota, Bundi, Baran, Jhalawar) ---
    {"pincode": "324001", "city_or_village": "Kota City / Rampura Bazar", "district_id": 25, "division_id": 6, "tehsil_block_id": 8, "ulb_id": 5},
    {"pincode": "324002", "city_or_village": "Nayapura / Chambal Garden, Kota", "district_id": 25, "division_id": 6},
    {"pincode": "324005", "city_or_village": "Talwandi / Vigyan Nagar Coaching Hub, Kota", "district_id": 25, "division_id": 6},
    {"pincode": "324006", "city_or_village": "DCM Industrial Area, Kota", "district_id": 25, "division_id": 6},
    {"pincode": "324007", "city_or_village": "Dadabari, Kota", "district_id": 25, "division_id": 6},
    {"pincode": "324008", "city_or_village": "Mahaveer Nagar Extension, Kota", "district_id": 25, "division_id": 6},
    {"pincode": "324009", "city_or_village": "Kunhari / Landmark City, Kota", "district_id": 25, "division_id": 6},
    {"pincode": "325001", "city_or_village": "Ramganj Mandi / Kota Stone Capital", "district_id": 25, "division_id": 6},
    {"pincode": "323001", "city_or_village": "Bundi City / Stepwell Heritage", "district_id": 26, "division_id": 6},
    {"pincode": "323801", "city_or_village": "Keshoraipatan Sugar Mills", "district_id": 26, "division_id": 6},
    {"pincode": "325205", "city_or_village": "Baran City / Spice Market", "district_id": 27, "division_id": 6},
    {"pincode": "325207", "city_or_village": "Chhabra Thermal Power Plant", "district_id": 27, "division_id": 6},
    {"pincode": "325216", "city_or_village": "Antah Gas Power Station", "district_id": 27, "division_id": 6},
    {"pincode": "326001", "city_or_village": "Jhalawar City / Garh Palace", "district_id": 28, "division_id": 6},
    {"pincode": "326023", "city_or_village": "Jhalrapatan Sun Temple City", "district_id": 28, "division_id": 6},
    {"pincode": "326033", "city_or_village": "Aklera Mandi", "district_id": 28, "division_id": 6},

    # --- 6. Bharatpur Division (Bharatpur, Dholpur, Karauli, Deeg, Sawai Madhopur, Gangapur City) ---
    {"pincode": "321001", "city_or_village": "Bharatpur City / Keoladeo National Park", "district_id": 29, "division_id": 2},
    {"pincode": "321203", "city_or_village": "Kumher Sub-Division", "district_id": 29, "division_id": 2},
    {"pincode": "321302", "city_or_village": "Bayana Historical Fort", "district_id": 29, "division_id": 2},
    {"pincode": "328001", "city_or_village": "Dholpur City / Red Stone Capital", "district_id": 30, "division_id": 2},
    {"pincode": "328023", "city_or_village": "Bari Sub-Division", "district_id": 30, "division_id": 2},
    {"pincode": "322241", "city_or_village": "Karauli City / Kaila Devi Dham", "district_id": 31, "division_id": 2},
    {"pincode": "322201", "city_or_village": "Hindaun City / Industrial Area", "district_id": 31, "division_id": 2},
    {"pincode": "321201", "city_or_village": "Deeg City / Water Palace District HQ", "district_id": 32, "division_id": 2},
    {"pincode": "321301", "city_or_village": "Kaman Heritage Town", "district_id": 32, "division_id": 2},
    {"pincode": "322001", "city_or_village": "Sawai Madhopur City / Ranthambore Tiger Reserve", "district_id": 33, "division_id": 2},
    {"pincode": "322202", "city_or_village": "Gangapur City / Railway Junction District HQ", "district_id": 34, "division_id": 2},

    # --- 7. Udaipur Division (Udaipur, Chittorgarh, Rajsamand, Bhilwara, Salumbar) ---
    {"pincode": "313001", "city_or_village": "Udaipur City / Lake Palace / Chetak Circle", "district_id": 35, "division_id": 7, "tehsil_block_id": 9, "ulb_id": 7},
    {"pincode": "313002", "city_or_village": "Surajpole / Hiran Magri Sector 3-5, Udaipur", "district_id": 35, "division_id": 7},
    {"pincode": "313003", "city_or_village": "Pratapnagar / Transport Nagar, Udaipur", "district_id": 35, "division_id": 7},
    {"pincode": "313004", "city_or_village": "Fatehpura / Saheliyon ki Bari, Udaipur", "district_id": 35, "division_id": 7},
    {"pincode": "313011", "city_or_village": "Badi / Badgaon Rural Lake Area", "district_id": 35, "division_id": 7, "tehsil_block_id": 9, "gram_panchayat_id": 8},
    {"pincode": "313301", "city_or_village": "Mavli Junction", "district_id": 35, "division_id": 7},
    {"pincode": "312001", "city_or_village": "Chittorgarh Fort & City", "district_id": 36, "division_id": 7},
    {"pincode": "312601", "city_or_village": "Nimbahera Cement Manufacturing Hub", "district_id": 36, "division_id": 7},
    {"pincode": "313324", "city_or_village": "Rajsamand / Kankroli Marble Hub", "district_id": 37, "division_id": 7},
    {"pincode": "313302", "city_or_village": "Nathdwara Shrinathji Temple Town", "district_id": 37, "division_id": 7},
    {"pincode": "311001", "city_or_village": "Bhilwara City / Textile City of India", "district_id": 38, "division_id": 7},
    {"pincode": "311002", "city_or_village": "Bhilwara Growth Centre Industrial Zone", "district_id": 38, "division_id": 7},
    {"pincode": "311401", "city_or_village": "Gulabpura Spinning Mills", "district_id": 38, "division_id": 7},
    {"pincode": "313705", "city_or_village": "Salumbar City / Jaisamand Lake District HQ", "district_id": 39, "division_id": 7},

    # --- 8. Sikar Division (Sikar, Jhunjhunu, Churu, Neem Ka Thana) ---
    {"pincode": "332001", "city_or_village": "Sikar City / Shekhawati Gateway", "district_id": 40, "division_id": 8, "tehsil_block_id": 10, "ulb_id": 9},
    {"pincode": "332021", "city_or_village": "Piprali Educational Zone, Sikar", "district_id": 40, "division_id": 8},
    {"pincode": "332403", "city_or_village": "Fatehpur Shekhawati Haveli Heritage", "district_id": 40, "division_id": 8},
    {"pincode": "332404", "city_or_village": "Laxmangarh Sub-Division", "district_id": 40, "division_id": 8},
    {"pincode": "333001", "city_or_village": "Jhunjhunu City / Khetan Bazar", "district_id": 41, "division_id": 8},
    {"pincode": "333031", "city_or_village": "Chirawa Peda City", "district_id": 41, "division_id": 8},
    {"pincode": "333041", "city_or_village": "Nawalgarh Open Air Art Gallery", "district_id": 41, "division_id": 8},
    {"pincode": "333515", "city_or_village": "Pilani BITS Campus & Science City", "district_id": 41, "division_id": 8},
    {"pincode": "331001", "city_or_village": "Churu City / Desert Gateway", "district_id": 42, "division_id": 8},
    {"pincode": "331022", "city_or_village": "Ratangarh Junction", "district_id": 42, "division_id": 8},
    {"pincode": "331023", "city_or_village": "Sujangarh Sub-Division", "district_id": 42, "division_id": 8},
    {"pincode": "331029", "city_or_village": "Salasar Balaji Dham", "district_id": 42, "division_id": 8},
    {"pincode": "331304", "city_or_village": "Sardarshahar Wood Carving Town", "district_id": 42, "division_id": 8},
    {"pincode": "332715", "city_or_village": "Neem Ka Thana Mining & District HQ", "district_id": 43, "division_id": 8},

    # --- 9. Pali Division (Pali, Jalore, Sanchore, Sirohi) ---
    {"pincode": "306401", "city_or_village": "Pali City / Industrial Area", "district_id": 44, "division_id": 9},
    {"pincode": "306402", "city_or_village": "Pali Marwar Junction Hub", "district_id": 44, "division_id": 9},
    {"pincode": "306502", "city_or_village": "Sojat Mehndi City", "district_id": 44, "division_id": 9},
    {"pincode": "306702", "city_or_village": "Sumerpur Grain Mandi", "district_id": 44, "division_id": 9},
    {"pincode": "306104", "city_or_village": "Falna Umbrella City / Golden Temple Ranakpur", "district_id": 44, "division_id": 9},
    {"pincode": "343001", "city_or_village": "Jalore Granite City & Fort", "district_id": 45, "division_id": 9},
    {"pincode": "343029", "city_or_village": "Bhinmal Sanskrit Poet Magh Heritage", "district_id": 45, "division_id": 9},
    {"pincode": "343041", "city_or_village": "Sanchore Dairy & District HQ", "district_id": 46, "division_id": 9},
    {"pincode": "307001", "city_or_village": "Sirohi City / Sword Craft", "district_id": 47, "division_id": 9},
    {"pincode": "307501", "city_or_village": "Abu Road Railway Junction", "district_id": 47, "division_id": 9},
    {"pincode": "307513", "city_or_village": "Mount Abu / Hill Station of Rajasthan", "district_id": 47, "division_id": 9},

    # --- 10. Banswara Division (Banswara, Dungarpur, Pratapgarh) ---
    {"pincode": "327001", "city_or_village": "Banswara City / City of Hundred Islands", "district_id": 48, "division_id": 10},
    {"pincode": "327022", "city_or_village": "Kushalgarh Tribal Sub-Division", "district_id": 48, "division_id": 10},
    {"pincode": "314001", "city_or_village": "Dungarpur City / Green Marble & Palaces", "district_id": 49, "division_id": 10},
    {"pincode": "314027", "city_or_village": "Sagwara Metal Craft & Mandi", "district_id": 49, "division_id": 10},
    {"pincode": "312605", "city_or_village": "Pratapgarh City / Thewa Gold Jewelry Art", "district_id": 50, "division_id": 10},
    {"pincode": "312615", "city_or_village": "Dhariawad Forest Sub-Division", "district_id": 50, "division_id": 10},
]

async def init_models():
    """Create all tables in PostgreSQL, including pgvector extension and rag_support table"""
    async with async_engine.begin() as conn:
        try:
            from sqlalchemy import text
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rag_support (
                    id SERIAL PRIMARY KEY,
                    record_type VARCHAR(10) NOT NULL,
                    session_id VARCHAR(100),
                    role VARCHAR(20),
                    content TEXT NOT NULL,
                    embedding VECTOR(384),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_rag_support_embedding 
                ON rag_support USING hnsw (embedding vector_cosine_ops);
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_rag_support_type_session 
                ON rag_support (record_type, session_id);
            """))
        except Exception as e:
            # Fallback if vector extension is not available on local host
            from sqlalchemy import text
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rag_support (
                    id SERIAL PRIMARY KEY,
                    record_type VARCHAR(10) NOT NULL,
                    session_id VARCHAR(100),
                    role VARCHAR(20),
                    content TEXT NOT NULL,
                    embedding JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
        await conn.run_sync(Base.metadata.create_all)
    print("All PostgreSQL tables verified/created successfully.")

async def seed_initial_data():
    """Seed default state, admin, llm_settings, and fallback geographic hierarchy"""
    async with AsyncSessionLocal() as session:
        # 1. State
        res_state = await session.execute(select(State).filter_by(id=1))
        state = res_state.scalar_one_or_none()
        if not state:
            state = State(
                id=1,
                name_en="Rajasthan",
                name_hi="राजस्थान",
                code="RJ",
                lgd_code=8,
                chief_secretary="Chief Secretary, Government of Rajasthan",
                governance_details="Government Secretariat, Jaipur, Rajasthan (10 Divisions, 50 Districts)",
                metadata_json={"area_sq_km": 342239, "official_language": "Hindi"}
            )
            session.add(state)
            await session.commit()
            print("Seeded State: Rajasthan")

        # 2. Admin
        res_admin = await session.execute(select(Admin).filter_by(username=DEFAULT_ADMIN_USER))
        admin = res_admin.scalar_one_or_none()
        if not admin:
            hashed = bcrypt.hashpw(DEFAULT_ADMIN_PASS.encode(), bcrypt.gensalt()).decode()
            admin = Admin(
                username=DEFAULT_ADMIN_USER,
                password_hash=hashed,
                role="admin"
            )
            session.add(admin)
            await session.commit()
            print(f"Seeded Admin: {DEFAULT_ADMIN_USER}")

        # 3. LLM Setting
        res_llm = await session.execute(select(LLMSetting).filter_by(id=1))
        llm_cfg = res_llm.scalar_one_or_none()
        if not llm_cfg:
            llm_cfg = LLMSetting(
                id=1,
                active_model=settings.DEFAULT_OLLAMA_MODEL,
                temperature=0.2,
                max_tokens=1024,
                system_prompt=DEFAULT_SYSTEM_PROMPT,
                greeting_message=DEFAULT_GREETING,
                support_phone=settings.SUPPORT_PHONE
            )
            session.add(llm_cfg)
            await session.commit()
            print("Seeded LLM Settings")
        else:
            llm_cfg.system_prompt = DEFAULT_SYSTEM_PROMPT
            llm_cfg.greeting_message = DEFAULT_GREETING
            await session.commit()
            print("Updated LLM Settings with structured output prompt.")

        # 4. Divisions
        for d in FALLBACK_DIVISIONS:
            res = await session.execute(select(Division).filter_by(rajmaster_id=d["rajmaster_id"]))
            if not res.scalar_one_or_none():
                div = Division(
                    state_id=1,
                    rajmaster_id=d["rajmaster_id"],
                    code=d["code"],
                    name_en=d["name_en"],
                    name_hi=d["name_hi"],
                    divisional_commissioner=d["divisional_commissioner"],
                    lgd_code=d["lgd_code"],
                    metadata_json={"source": "seed"}
                )
                session.add(div)
        await session.commit()

        # 5. Districts
        for dst in FALLBACK_DISTRICTS:
            res = await session.execute(select(District).filter_by(rajmaster_id=dst["rajmaster_id"]))
            if not res.scalar_one_or_none():
                d_obj = District(
                    division_id=dst["division_id"],
                    rajmaster_id=dst["rajmaster_id"],
                    code=dst["code"],
                    name_en=dst["name_en"],
                    name_hi=dst["name_hi"],
                    collectorate_details=f"District Collectorate, {dst['name_en']}",
                    zila_parishad_details=f"Zila Parishad {dst['name_en']}",
                    zila_pramukh=dst["zila_pramukh"],
                    lgd_code=dst["lgd_code"],
                    metadata_json={"source": "seed"}
                )
                session.add(d_obj)
        await session.commit()

        # 6. Sub-Divisions
        for sd in FALLBACK_SUBDIVISIONS:
            res = await session.execute(select(SubDivision).filter_by(rajmaster_id=sd["rajmaster_id"]))
            if not res.scalar_one_or_none():
                sd_obj = SubDivision(
                    district_id=sd["district_id"],
                    rajmaster_id=sd["rajmaster_id"],
                    code=sd["code"],
                    name_en=sd["name_en"],
                    name_hi=sd["name_hi"],
                    sdm_jurisdiction=sd["sdm_jurisdiction"],
                    lgd_code=sd["lgd_code"],
                    metadata_json={"source": "seed"}
                )
                session.add(sd_obj)
        await session.commit()

        # 7. Tehsils & Blocks
        for tb in FALLBACK_TEHSILS_BLOCKS:
            res = await session.execute(
                select(TehsilBlock).filter_by(name_en=tb["name_en"], entity_type=tb["entity_type"])
            )
            if not res.scalars().first():
                tb_obj = TehsilBlock(
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
                    metadata_json={"source": "seed"}
                )
                session.add(tb_obj)
        await session.commit()

        # 8. Gram Panchayats
        for gp in FALLBACK_GRAM_PANCHAYATS:
            res = await session.execute(select(GramPanchayat).filter_by(name_en=gp["name_en"]))
            if not res.scalars().first():
                gp_obj = GramPanchayat(
                    district_id=gp["district_id"],
                    tehsil_block_id=gp["tehsil_block_id"],
                    rajmaster_id=gp["rajmaster_id"],
                    code=gp["code"],
                    name_en=gp["name_en"],
                    name_hi=gp["name_hi"],
                    sarpanch=gp["sarpanch"],
                    lgd_code=gp["lgd_code"],
                    metadata_json={"source": "seed"}
                )
                session.add(gp_obj)
        await session.commit()

        # 9. Villages
        for v in FALLBACK_VILLAGES:
            res = await session.execute(select(Village).filter_by(name_en=v["name_en"]))
            if not res.scalars().first():
                v_obj = Village(
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
                    metadata_json={"source": "seed"}
                )
                session.add(v_obj)
        await session.commit()

        # 10. ULBs
        for u in FALLBACK_ULBS:
            res = await session.execute(select(UrbanLocalBody).filter_by(name_en=u["name_en"]))
            if not res.scalars().first():
                u_obj = UrbanLocalBody(
                    district_id=u["district_id"],
                    rajmaster_id=u["rajmaster_id"],
                    code=u["code"],
                    name_en=u["name_en"],
                    name_hi=u["name_hi"],
                    ulb_type=u["ulb_type"],
                    city_name=u["city_name"],
                    pincode=u["pincode"],
                    lgd_code=u["lgd_code"],
                    metadata_json={"source": "seed"}
                )
                session.add(u_obj)
        await session.commit()

        # 11. Urban Wards
        for uw in FALLBACK_URBAN_WARDS:
            res = await session.execute(select(UrbanWard).filter_by(ulb_id=uw["ulb_id"], ward_number=uw["ward_number"]))
            if not res.scalars().first():
                uw_obj = UrbanWard(
                    ulb_id=uw["ulb_id"],
                    rajmaster_id=uw["rajmaster_id"],
                    ward_number=uw["ward_number"],
                    name_en=uw["name_en"],
                    name_hi=uw["name_hi"],
                    councillor_parshad=uw["councillor_parshad"],
                    pincode=uw["pincode"],
                    lgd_code=uw["lgd_code"],
                    metadata_json={"source": "seed"}
                )
                session.add(uw_obj)
        await session.commit()

        # 12. Pincodes
        for p in FALLBACK_PINCODES:
            res = await session.execute(select(Pincode).filter_by(pincode=p["pincode"]))
            existing = res.scalar_one_or_none()
            if not existing:
                p_obj = Pincode(
                    pincode=p["pincode"],
                    city_or_village=p["city_or_village"],
                    district_id=p.get("district_id"),
                    division_id=p.get("division_id"),
                    tehsil_block_id=p.get("tehsil_block_id"),
                    ulb_id=p.get("ulb_id"),
                    gram_panchayat_id=p.get("gram_panchayat_id"),
                    metadata_json={"source": "seed"}
                )
                session.add(p_obj)
            else:
                existing.city_or_village = p["city_or_village"]
                existing.district_id = p.get("district_id")
                existing.division_id = p.get("division_id")
                if p.get("tehsil_block_id"):
                    existing.tehsil_block_id = p.get("tehsil_block_id")
                if p.get("ulb_id"):
                    existing.ulb_id = p.get("ulb_id")
        await session.commit()

    print("Initial seed data populated successfully.")

async def main():
    await init_models()
    await seed_initial_data()
    await async_engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
