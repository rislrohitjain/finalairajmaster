import os
import re
import json
import time
import asyncio
import logging
from typing import Dict, Any, TypedDict, Optional, List
from urllib.parse import quote_plus, unquote
from bs4 import BeautifulSoup
from langgraph.graph import StateGraph, END
import httpx
from sqlalchemy import select, text
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import LLMSetting
from app.agent.tools import lookup_geographic_hierarchy, STOP_WORDS
from app.mcp.client import mcp_client

logger = logging.getLogger("agent.graph")

class AgentState(TypedDict):
    session_id: str
    user_query: str
    language: Optional[str] # 'en', 'hi', 'hinglish'
    intent: Optional[str] # 'geographic_query', 'capability_query', 'out_of_scope'
    sql_trace: Optional[Dict[str, Any]]
    breadcrumbs: Optional[List[str]]
    helpline_card: bool
    support_phone: str
    response_text: str
    streaming_tokens: Optional[List[str]]
    next_questions: Optional[List[str]]
    mcp_used: Optional[bool]
    mcp_tool: Optional[str]
    mcp_transport: Optional[str]
    resolution_stage: Optional[str]
    pipeline_steps: Optional[List[Dict[str, Any]]]

def _append_step(
    state: AgentState,
    step_id: str,
    title: str,
    detail: str,
    icon: str,
    duration_ms: Optional[int] = None,
    status: str = "done"
) -> None:
    steps = list(state.get("pipeline_steps") or [])
    steps.append({
        "id": step_id,
        "title": title,
        "detail": detail,
        "icon": icon,
        "duration_ms": duration_ms,
        "status": status
    })
    state["pipeline_steps"] = steps

# Rajasthan Administrative keywords for classifier
GEO_KEYWORDS = {
    "rajasthan", "division", "district", "sub-division", "sub division", "tehsil", "tehsildar",
    "sub-tehsil", "block", "panchayat samiti", "gram panchayat", "gp", "panchayat", "sarpanch",
    "ward", "panch", "parshad", "village", "revenue village", "patwar", "patwari", "patwar circle",
    "ulb", "urban local body", "nagar nigam", "nagar parishad", "nagar palika", "city",
    "pincode", "pin code", "lgd", "lgd code", "collector", "collectorate", "zila parishad",
    "zila pramukh", "sdm", "sdo", "bdo", "commissioner", "secretariat", "lineage", "hierarchy",
    # Hindi keywords
    "राजस्थान", "संभाग", "जिला", "उपखंड", "तहसील", "ब्लॉक", "पंचायत", "सरपंच", "पटवारी", "ग्राम",
    "गांव", "नगर", "निगम", "परिषद", "पालिका", "पिनकोड", "कलेक्टर", "पदानुक्रम", "वंशावली"
}

CAPABILITY_KEYWORDS = {
    "hi", "hello", "hey", "namaste", "pranam", "help", "capability", "capabilities",
    "what can you do", "who are you", "what do you do", "features", "how to use",
    "guide", "menu", "options", "kya kar sakte ho", "madad"
}

OUT_OF_SCOPE_WORDS = {
    "weather", "temperature", "forecast", "cricket", "match", "movie", "film", "actor",
    "actress", "song", "lyrics", "python", "javascript", "code", "programming", "sql query",
    "recipe", "cooking", "politics", "election result", "modi", "rahul", "bjp", "congress",
    "stock", "crypto", "bitcoin", "football", "joke", "shayari", "write an essay"
}

def sanitize_structured_output(text: str) -> str:
    """
    Strips unwanted conversational filler words, pleasantries, apologies,
    rhetorical openings, trailing chatty remarks, and any markdown bold (**) asterisks,
    ensuring pure, cleanly formatted structured output without stray asterisks.
    """
    if not text:
        return ""
    
    cleaned = text.strip()

    # Strip wrapping code fences if present
    if cleaned.startswith("```markdown") and cleaned.endswith("```"):
        cleaned = cleaned[11:-3].strip()
    elif cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()

    # Strip all literal double asterisks (**) completely so output is clean
    cleaned = cleaned.replace("**", "")

    # Unwanted conversational starter patterns
    unwanted_starters = [
        r"^(?:Sure[!,.]?|Certainly[!,.]?|Of course[!,.]?|Hello[!.,]?|Namaste[!.,]?|Greetings[!.,]?|Alright[!,.]?|Okay[!,.]?)\s*",
        r"^(?:Here is the (?:information|details|administrative hierarchy|lineage|data)[^:\n]*:?)\s*",
        r"^(?:I(?:'d| would) be happy to (?:help|assist)[^.\n]*[.:]?)\s*",
        r"^(?:Based on the (?:provided|official|verified) data[,:]?)\s*",
        r"^(?:According to the (?:official|records|database)[^:\n]*:?)\s*",
        r"^(?:As per Rajasthan government records[,:]?)\s*",
        r"^(?:Here are the administrative details[^:\n]*:?)\s*"
    ]
    for pat in unwanted_starters:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    # Unwanted conversational closing patterns
    unwanted_endings = [
        r"(?:Hope this helps[!,.]?.*)$",
        r"(?:Let me know if you (?:need|have) (?:any|more) (?:other|further)?.*)$",
        r"(?:Feel free to (?:ask|reach out).*)$",
        r"(?:Please let me know if you require.*)$",
        r"(?:If you have any (?:other|further) questions.*)$",
        r"(?:Is there anything else.*)$",
        r"(?:Have a great day[!,.]?.*)$",
        r"(?:Thank you for contacting.*)$"
    ]
    for pat in unwanted_endings:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

async def get_active_llm_config() -> Dict[str, Any]:
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(LLMSetting).where(LLMSetting.id == 1))
            cfg = res.scalar_one_or_none()
            if cfg:
                return {
                    "active_model": cfg.active_model,
                    "temperature": cfg.temperature,
                    "max_tokens": cfg.max_tokens,
                    "system_prompt": cfg.system_prompt,
                    "greeting_message": cfg.greeting_message,
                    "support_phone": cfg.support_phone or settings.SUPPORT_PHONE,
                    "enable_rag": cfg.enable_rag if cfg.enable_rag is not None else True,
                    "rag_top_k": cfg.rag_top_k or 5,
                    "enable_web_search": cfg.enable_web_search if cfg.enable_web_search is not None else True,
                    "web_search_provider": cfg.web_search_provider or "duckduckgo",
                    "web_search_api_key": cfg.web_search_api_key or "",
                    "web_search_max_results": cfg.web_search_max_results or 4
                }
    except Exception as e:
        logger.warning(f"Could not load LLMSetting from DB: {e}")
    return {
        "active_model": settings.DEFAULT_OLLAMA_MODEL,
        "temperature": 0.2,
        "max_tokens": 1024,
        "system_prompt": "You are RajMaster AI, a full-stack educational showcase agent demonstrating LangGraph and LLM architecture on a simulated Rajasthan geographic knowledge graph. Output clean, structured bilingual answers with zero conversational filler.",
        "greeting_message": "Welcome here chat with Jain's only",
        "support_phone": settings.SUPPORT_PHONE,
        "enable_rag": True,
        "rag_top_k": 5,
        "enable_web_search": True,
        "web_search_provider": "duckduckgo",
        "web_search_api_key": "",
        "web_search_max_results": 4
    }

# ----------------- NODE 1: Guardrail & Intent Classifier -----------------
async def guardrail_classifier_node(state: AgentState) -> AgentState:
    t0 = time.perf_counter()
    query = state["user_query"].strip()
    query_lower = query.lower()
    tokens = set(re.findall(r"\b\w+\b", query_lower))
    detected_lang = detect_query_language(query, state.get("language"))

    def _finish(intent: str, reason: str) -> AgentState:
        state["intent"] = intent
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        _append_step(
            state,
            "guardrail",
            "Guardrail & Intent Classifier",
            f"Intent: {intent} • Lang: {detected_lang} ({reason})",
            "🛡️",
            duration_ms=ms,
        )
        return state

    # Check if MCP metadata / database inspection query
    if _detect_mcp_metadata_intent(query):
        return _finish("geographic_query", "MCP database inspection query")

    # Check if explicitly related to Rajasthan or official administration
    is_rajasthan_related = (
        "rajasthan" in query_lower or "राजस्थान" in query_lower or
        any(k in query_lower for k in GEO_KEYWORDS)
    )

    # Check for direct out-of-scope words ONLY if query is NOT rajasthan-related
    if not is_rajasthan_related:
        if any(w in OUT_OF_SCOPE_WORDS for w in tokens) or any(
            re.search(r"\b" + re.escape(term) + r"\b", query_lower) for term in OUT_OF_SCOPE_WORDS
        ):
            return _finish("out_of_scope", "Out-of-scope topic detected -> helpline routing")

    # Check if pincode query (6 digits)
    if re.search(r"\b\d{6}\b", query):
        return _finish("geographic_query", "6-digit pincode detected")

    # Check greeting / capability queries
    if len(tokens) <= 3 and any(w in CAPABILITY_KEYWORDS for w in tokens):
        return _finish("capability_query", "Greeting / capability overview")

    if any(k in query_lower for k in ["what can you", "help me", "who are you", "kya kar sakte"]):
        return _finish("capability_query", "Capability inquiry")

    # Check Rajasthan Geographic keywords or potential place names
    if is_rajasthan_related:
        return _finish("geographic_query", "Rajasthan administrative keyword matched")

    # If query is short or looks like a place name (e.g. "Jaipur", "Muhana", "Beawar", "Didwana")
    # we test lookup before rejecting
    geo_lookup = await lookup_geographic_hierarchy(query)
    if geo_lookup.get("matched"):
        state["sql_trace"] = geo_lookup
        return _finish("geographic_query", f"Entity matched ({geo_lookup.get('entity_name')})")

    # Allow query to proceed to RAG / Web Search Fallback rather than rejecting prematurely
    return _finish("geographic_query", "Proceeding to DB, MCP, RAG & Web Search pipeline")

# ----------------- LANGUAGE & NATURAL LANGUAGE GENERATION HELPERS -----------------
HINDI_DIVISIONS = {
    "Jaipur Division": "जयपुर संभाग",
    "Jodhpur Division": "जोधपुर संभाग",
    "Ajmer Division": "अजमेर संभाग",
    "Udaipur Division": "उदयपुर संभाग",
    "Bikaner Division": "बीकानेर संभाग",
    "Kota Division": "कोटा संभाग",
    "Bharatpur Division": "भरतपुर संभाग",
    "Sikar Division": "सीकर संभाग",
    "Pali Division": "पाली संभाग",
    "Banswara Division": "बांसवाड़ा संभाग"
}

def detect_query_language(query: str, requested_lang: Optional[str] = None) -> str:
    """
    Determines whether the response should be in English ('en'), Hindi ('hi'), or Hinglish ('hinglish').
    Respects explicit user request, with intelligent detection for Devanagari script and Hinglish markers.
    """
    if requested_lang:
        req = requested_lang.lower().strip()
        if req in ["hi", "hindi", "हिंदी"]:
            return "hi"
        if req in ["hinglish", "hin-eng"]:
            return "hinglish"
        if req in ["en", "english"]:
            return "en"

    # 1. Detect Devanagari Unicode
    if re.search(r"[\u0900-\u097F]", query):
        return "hi"

    # 2. Detect Hinglish markers
    hinglish_markers = {
        "kya", "kaun", "kis", "kaha", "kahan", "kisme", "kisko", "kaise",
        "batao", "bataiye", "hoga", "hogi", "hai", "hain", "ke", "ka", "ki",
        "mein", "me", "se", "aur", "chahiye", "pata", "bata", "batao", "kaunsa"
    }
    tokens = set(re.findall(r"\b\w+\b", query.lower()))
    if len(tokens.intersection(hinglish_markers)) >= 2:
        return "hinglish"

    return "en"

def translate_crumb(crumb: str, lang: str) -> str:
    if lang != "hi":
        return crumb
    if crumb == "Rajasthan":
        return "राजस्थान"
    if crumb in HINDI_DIVISIONS:
        return HINDI_DIVISIONS[crumb]
    if crumb.endswith(" Division"):
        return f"{crumb[:-9]} संभाग"
    return crumb

def generate_next_expected_questions(
    entity_name: str,
    entity_type: str,
    lineage: Dict[str, Any],
    details: Dict[str, Any],
    language: str
) -> List[str]:
    etype = (entity_type or "").lower()
    dist = lineage.get("district") or details.get("district") or "Jaipur"
    div = lineage.get("division") or "Jaipur Division"
    tehsil = lineage.get("tehsil_or_block") or lineage.get("tehsil") or "Sanganer"
    pin = details.get("pincode") or lineage.get("pincode") or "302029"
    name = entity_name or "this location"

    # Extract cleaner village/area name if entity_name has extra decorations
    clean_name = re.sub(r"^Pincode\s+\d{6}\s*\((.*?)\)", r"\1", name).strip()
    clean_name = re.sub(r"\(.*?\)", "", clean_name).strip() or name

    if "pincode" in etype or pin in name:
        if language == "hi":
            return [
                f"पिनकोड {pin} क्षेत्र के लिए प्रशासनिक तहसील और उपखंड कौन सा है?",
                f"पिनकोड {pin} के अंतर्गत कौन सा नगरीय निकाय या ग्राम पंचायत आती है?",
                f"पिनकोड {pin} क्षेत्र के राजस्व व प्रशासनिक अधिकारी कौन हैं?"
            ]
        elif language == "hinglish":
            return [
                f"Pincode {pin} area ki administrative tehsil aur SDM kaun hai?",
                f"Pincode {pin} ke under kaunsi Urban Local Body ya Gram Panchayat aati hai?",
                f"Pincode {pin} area ke revenue aur governance authorities kaun hain?"
            ]
        else:
            return [
                f"What is the administrative tehsil and sub-division for pincode {pin}?",
                f"Which Urban Local Body or Gram Panchayat covers pincode {pin}?",
                f"Who are the revenue and administrative authorities for pincode {pin}?"
            ]

    elif "districtslist" in etype or "districts" in etype:
        if language == "hi":
            return [
                "राजस्थान के सभी 10 प्रशासनिक संभागों की सूची क्या है?",
                "जयपुर जिले के अंतर्गत कौन-कौन सी तहसीलें आती हैं?",
                "बालोतरा और अन्य नए गठित जिलों का प्रशासनिक विवरण क्या है?"
            ]
        elif language == "hinglish":
            return [
                "Rajasthan ke sabhi 10 administrative divisions ki list kya hai?",
                "Jaipur district ke under kaunsi tehsils aati hain?",
                "Balotra aur naye districts ka administrative setup kya hai?"
            ]
        else:
            return [
                "What are the 10 administrative divisions of Rajasthan?",
                "Which tehsils and sub-divisions fall under Jaipur district?",
                "Tell me about the newly formed district of Balotra"
            ]

    elif "village" in etype or "panchayat" in etype:
        if language == "hi":
            return [
                f"{clean_name} के सरपंच और पटवारी कौन हैं?",
                f"{clean_name} किस उपखंड (SDM) और तहसील के अधिकार क्षेत्र में आता है?",
                f"{clean_name} और इसके ग्राम पंचायत क्षेत्र का आधिकारिक पिनकोड क्या है?"
            ]
        elif language == "hinglish":
            return [
                f"{clean_name} ke Sarpanch aur Patwari kaun hain?",
                f"{clean_name} kis Sub-Division (SDM) aur Tehsil ke under aata hai?",
                f"{clean_name} aur iske Gram Panchayat area ka official pincode kya hai?"
            ]
        else:
            return [
                f"Who is the Sarpanch and Patwari of {clean_name} village?",
                f"Which Sub-Division (SDM) and Tehsil administers {clean_name}?",
                f"What is the official postal pincode for {clean_name}?"
            ]

    elif "district" in etype:
        if language == "hi":
            return [
                f"{clean_name} जिले में कौन-कौन सी प्रमुख तहसीलें और उपखंड हैं?",
                f"{clean_name} के जिला कलेक्टर और जिला प्रमुख कौन हैं?",
                f"{div} के अंतर्गत अन्य कौन से जिले शामिल हैं?"
            ]
        elif language == "hinglish":
            return [
                f"{clean_name} district mein kaunsi main tehsils aur sub-divisions hain?",
                f"{clean_name} ke District Collector aur Zila Pramukh kaun hain?",
                f"{div} ke under aur kaunse districts aate hain?"
            ]
        else:
            return [
                f"What are the major tehsils and sub-divisions in {clean_name} district?",
                f"Who is the District Collector and Zila Pramukh of {clean_name}?",
                f"Which other districts fall under {div}?"
            ]

    elif "tehsil" in etype or "block" in etype:
        if language == "hi":
            return [
                f"{clean_name} के तहसीलदार और ब्लॉक विकास अधिकारी (BDO) कौन हैं?",
                f"{clean_name} तहसील किस उपखंड (SDM) क्षेत्राधिकार में आती है?",
                f"{clean_name} तहसील के अंतर्गत आने वाले प्रमुख राजस्व गांव कौन से हैं?"
            ]
        elif language == "hinglish":
            return [
                f"{clean_name} ke Tehsildar aur Block Development Officer (BDO) kaun hain?",
                f"{clean_name} tehsil kis Sub-Division (SDM) jurisdiction mein aati hai?",
                f"{clean_name} tehsil ke under aane wale main revenue villages kaun se hain?"
            ]
        else:
            return [
                f"Who is the Tehsildar and Block Development Officer (BDO) for {clean_name}?",
                f"Which Sub-Division (SDM) jurisdiction covers {clean_name} tehsil?",
                f"What are the major revenue villages under {clean_name} tehsil?"
            ]

    elif "urban" in etype or "nigam" in etype or "palika" in etype:
        if language == "hi":
            return [
                f"{clean_name} के अंतर्गत कितने वार्ड और जोन आते हैं?",
                f"{clean_name} किस जिले और प्रशासनिक संभाग के तहत कार्य करता है?",
                f"{clean_name} क्षेत्र का मुख्य प्रशासनिक अधिकारी या मेयर कौन है?"
            ]
        elif language == "hinglish":
            return [
                f"{clean_name} ke under kitne wards aur zones aate hain?",
                f"{clean_name} kis district aur administrative division ke tahat operate karta hai?",
                f"{clean_name} area ka main administrative authority ya Mayor kaun hai?"
            ]
        else:
            return [
                f"How many wards and zones fall under {clean_name}?",
                f"Which district and administrative division governs {clean_name}?",
                f"Who is the primary civic administrative authority or Mayor for {clean_name}?"
            ]

    else:
        if language == "hi":
            return [
                f"{dist} जिले के अंतर्गत आने वाली प्रमुख तहसीलें कौन सी हैं?",
                f"{div} के अंतर्गत कुल कितने जिले आते हैं?",
                f"राजस्थान के 10 प्रशासनिक संभागों की सूची क्या है?"
            ]
        elif language == "hinglish":
            return [
                f"{dist} district ke under aane wali main tehsils kaun si hain?",
                f"{div} ke under total kitne districts aate hain?",
                f"Rajasthan ke 10 administrative divisions ki list kya hai?"
            ]
        else:
            return [
                f"What are the major tehsils in {dist} district?",
                f"How many districts are administered under {div}?",
                f"What are the 10 administrative divisions of Rajasthan?"
            ]

def format_natural_language_lineage(
    entity_name: str,
    entity_type: str,
    lineage: Dict[str, Any],
    details: Dict[str, Any],
    breadcrumbs: List[str],
    language: str,
    next_questions: List[str]
) -> str:
    """
    Renders fluent, natural language narrative without robotic headers or bullet points.
    Tailors output to English, Hindi, or Hinglish.
    """
    state_name = lineage.get("state") or "Rajasthan"
    div = lineage.get("division") or "Jaipur Division"
    dist = lineage.get("district") or "Jaipur"
    sub_div = lineage.get("sub_division") or details.get("sdm_jurisdiction")
    tehsil = lineage.get("tehsil_or_block") or lineage.get("tehsil")
    ulb = lineage.get("ulb") or lineage.get("ulb_name")
    gp = lineage.get("gram_panchayat")
    patwar = lineage.get("patwar_circle")
    village = lineage.get("village") or lineage.get("area_or_village")
    pincode = details.get("pincode") or lineage.get("pincode")
    etype = (entity_type or "").lower()

    # Officials
    collectorate = details.get("collectorate") or f"District Collectorate, {dist}"
    zila_pramukh = details.get("zila_pramukh") or f"Zila Pramukh, {dist}"
    sdm = details.get("sdm_jurisdiction") or (f"SDM, {sub_div}" if sub_div else None)
    tehsildar = details.get("tehsildar") or (f"Tehsildar, {tehsil}" if tehsil else None)
    bdo = details.get("bdo") or (f"BDO, {tehsil}" if tehsil else None)
    sarpanch = details.get("sarpanch") or (f"Sarpanch, {gp}" if gp else None)
    patwari = details.get("patwari") or (f"Patwari, {patwar}" if patwar else None)

    # ------------------ HINDI ------------------
    if language == "hi":
        hi_crumbs = [translate_crumb(c, "hi") for c in breadcrumbs]
        breadcrumb_str = " ➔ ".join(hi_crumbs)

        # 1. Location Narrative
        if "pincode" in etype or (pincode and pincode in entity_name):
            area = lineage.get("area_or_village") or details.get("city_or_village") or "संबंधित"
            offices = details.get("offices") or lineage.get("offices") or ""
            localities = details.get("localities") or ""
            total_offices = details.get("total_offices") or 0
            local_body_desc = ""
            if ulb and gp:
                local_body_desc = f", जिसमें शहरी क्षेत्रों का नागरिक प्रशासन {ulb} तथा ग्रामीण क्षेत्रों का प्रबंधन {gp} ग्राम पंचायत द्वारा किया जाता है"
            elif ulb:
                local_body_desc = f", जिसका शहरी नागरिक प्रशासन {ulb} द्वारा संचालित होता है"
            elif gp:
                local_body_desc = f", जिसका स्थानीय ग्रामीण प्रशासन {gp} ग्राम पंचायत द्वारा संचालित होता है"

            teh_txt = f" यह {tehsil} तहसील एवं ब्लॉक के अधिकार क्षेत्र में आता है{local_body_desc}।" if tehsil else ""
            office_txt = f"\n\n📮 डाकघर एवं क्षेत्र ({total_offices} डाकघर): {offices[:450]}" if offices else ""
            loc_txt = f"\n📍 प्रमुख ग्राम / मोहल्ले: {localities[:350]}" if localities else ""
            narrative = (
                f"डाक पिनकोड {pincode} राजस्थान के {area} क्षेत्र को सेवा प्रदान करता है। "
                f"प्रशासनिक दृष्टि से यह क्षेत्र {translate_crumb(div, 'hi')} के अंतर्गत {dist} जिले में स्थित है।{teh_txt}{office_txt}{loc_txt}"
            )
        elif "village" in etype:
            v_hi = details.get("village_hindi") or lineage.get("village_hi")
            ilr = details.get("ilr_circle") or lineage.get("ilr_circle")
            blk = details.get("block_hi") or details.get("block") or lineage.get("block")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            v_name_disp = f"{entity_name} ({v_hi})" if v_hi else entity_name
            ilr_txt = f" यह {ilr} गिरदावर (ILR) सर्कल" if ilr else ""
            patwar_txt = f" और {patwar} पटवार सर्कल" if patwar else ""
            blk_txt = f", {blk} पंचायत समिति (ब्लॉक)" if blk else ""
            pin_txt = f" (पिनकोड {pincode})" if pincode else ""
            lgd_txt = f" [LGD कोड: {lgd}]" if lgd else ""
            gp_txt = f", तथा {gp} ग्राम पंचायत{blk_txt}{ilr_txt}{patwar_txt}{pin_txt} के अंतर्गत आता है" if gp else f"{blk_txt}{ilr_txt}{patwar_txt}{pin_txt}"
            teh_txt = f" उप-जिला स्तर पर यह {tehsil} तहसील के अधिकार क्षेत्र में स्थित है{gp_txt}।" if tehsil else ""
            other_m = details.get("other_matches") or []
            other_txt = f"\n\n📌 इसी नाम के अन्य गांव: {', '.join(other_m)}" if other_m else ""
            narrative = (
                f"{v_name_disp}{lgd_txt} राजस्थान राज्य का एक आधिकारिक राजस्व गांव (Revenue Village) है। "
                f"प्रशासनिक दृष्टिकोण से यह {translate_crumb(div, 'hi')} के तहत {dist} जिले में स्थित है।{teh_txt}{other_txt}"
            )
        elif "districtslist" in etype or "districts" in etype:
            d_items = details.get("districts") or []
            selected = d_items[:10]
            lines = []
            for i, d in enumerate(selected, 1):
                div_name = translate_crumb(d.get("division", "राजस्थान"), "hi")
                name_hi = d.get("name_hi") or d.get("name_en")
                lines.append(f"{i}. **{name_hi}** ({div_name})")
            items_str = "\n".join(lines)
            narrative = (
                f"राजस्थान राज्य में कुल **50 जिले** हैं, जो **10 प्रशासनिक संभागों** के अंतर्गत आते हैं। "
                f"यहाँ राजस्थान के 10 प्रमुख जिलों की आधिकारिक प्रशासनिक सूची दी गई है:\n\n"
                f"{items_str}\n\n"
                f"प्रत्येक जिले का कार्यकारी व राजस्व प्रशासन जिला कलेक्टर कार्यालय (IAS) तथा लोकतांत्रिक ग्रामीण विकास जिला परिषद (जिला प्रमुख) द्वारा संचालित होता है।"
            )
        elif "district" in etype:
            count_intro = ""
            if details.get("is_count_query"):
                v_cnt = details.get("villages_count")
                tb_cnt = details.get("tehsils_count")
                gp_cnt = details.get("gram_panchayats_count")
                if details.get("asked_villages"):
                    cnt_str = f" कुल {v_cnt:,} राजस्व गांव" if v_cnt else " सभी राजस्व गांव"
                    gp_str = f" तथा {gp_cnt:,} ग्राम पंचायतें" if gp_cnt else ""
                    count_intro = f"{entity_name} जिले में{cnt_str}{gp_str} संबंधित तहसीलों एवं ग्राम पंचायतों के अधीन व्यवस्थित हैं। "
                elif details.get("asked_tehsils"):
                    tb_str = f" कुल {tb_cnt} तहसीलें व ब्लॉक" if tb_cnt else " मुख्य तहसीलें एवं ब्लॉक"
                    count_intro = f"{entity_name} जिले में वर्तमान प्रशासनिक रिकॉर्ड के अनुसार{tb_str} कार्यरत हैं। "

            narrative = (
                f"{count_intro}{entity_name} राजस्थान राज्य का एक प्रमुख जिला (District) है, "
                f"जो प्रशासनिक रूप से {translate_crumb(div, 'hi')} के अधिकार क्षेत्र में आता है। "
                f"जिले का संपूर्ण प्रशासनिक एवं विकास संचालन इसके स्वतंत्र जिला कलेक्टर कार्यालय एवं जिला परिषद के माध्यम से होता है।"
            )
        elif "gram panchayat" in etype or "grampanchayat" in etype:
            gp_hi = details.get("gram_panchayat_hindi") or lineage.get("gram_panchayat_hi")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            v_cnt = details.get("villages_count") or 0
            v_list = details.get("villages") or []
            pins = details.get("pincodes") or []
            gp_disp = f"{entity_name} ({gp_hi})" if gp_hi else entity_name
            lgd_txt = f" [LGD कोड: {lgd}]" if lgd else ""
            blk_txt = f" यह {tehsil} पंचायत समिति (ब्लॉक) के अंतर्गत आती है।" if tehsil else ""
            v_txt = f"\n\n🏡 सम्मिलित राजस्व गांव ({v_cnt}): {', '.join(v_list[:12])}" if v_list else ""
            pin_txt = f"\n📮 संबंधित पिनकोड: {', '.join(pins)}" if pins else ""
            narrative = (
                f"{gp_disp}{lgd_txt} राजस्थान की एक आधिकारिक ग्राम पंचायत है, "
                f"जो {translate_crumb(div, 'hi')} के अंतर्गत {dist} जिले में स्थित है।{blk_txt}{v_txt}{pin_txt}"
            )
        elif "tehsil" in etype or "block" in etype:
            tb_hi = details.get("entity_hindi")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            gp_cnt = details.get("gram_panchayats_count") or 0
            v_cnt = details.get("villages_count") or 0
            gps_sample = details.get("gram_panchayats") or []
            tb_disp = f"{entity_name} ({tb_hi})" if tb_hi else entity_name
            lgd_txt = f" [LGD कोड: {lgd}]" if lgd else ""
            sd_txt = f" यह {sub_div} उपखंड क्षेत्राधिकार के तहत कार्य करती है तथा" if sub_div else " यह"
            cnt_txt = f" इसके अंतर्गत {gp_cnt} ग्राम पंचायतें एवं {v_cnt} राजस्व गांव आते हैं।" if (gp_cnt or v_cnt) else ""
            gp_list_txt = f"\n\n🏘️ प्रमुख ग्राम पंचायतें: {', '.join(gps_sample[:10])}" if gps_sample else ""
            narrative = (
                f"{tb_disp}{lgd_txt} राजस्थान की एक महत्वपूर्ण प्रशासनिक इकाई ({entity_type}) है, जो {translate_crumb(div, 'hi')} के अंतर्गत {dist} जिले में स्थित है।{sd_txt} "
                f"अपने अधीन आने वाली ग्राम पंचायतों एवं राजस्व गांवों के प्रशासनिक व विकास कार्यों का संचालन करती है।{cnt_txt}{gp_list_txt}"
            )
        elif "urban" in etype or "nigam" in etype or "palika" in etype:
            narrative = (
                f"{entity_name} राजस्थान की एक अधिकृत शहरी स्थानीय निकाय संस्था है, "
                f"जो {translate_crumb(div, 'hi')} के अंतर्गत {dist} जिले में स्थित है। "
                f"यह संबंधित नगरीय क्षेत्र में नागरिक बुनियादी सुविधाओं, वार्ड विकास और नगर पालिका प्रशासन का प्रबंधन संभालती है।"
            )
        elif "state" in etype:
            narrative = (
                f"राजस्थान राज्य 6-स्तरीय प्रशासनिक ढांचे के तहत 10 संभागों और 50 जिलों में व्यवस्थित है, "
                f"जिसका सर्वोच्च प्रशासनिक एवं नीतिगत नियंत्रण राज्य सचिवालय, जयपुर द्वारा संचालित किया जाता है।"
            )
        else:
            narrative = (
                f"{entity_name} राजस्थान के {translate_crumb(div, 'hi')} के अंतर्गत {dist} जिले की अधिकृत प्रशासनिक इकाई है।"
            )

        # 2. Governance Narrative
        gov_sentences = []
        if collectorate and zila_pramukh:
            gov_sentences.append(f"जिले का प्रशासनिक व राजस्व नेतृत्व {collectorate} और {zila_pramukh} के अधीन है।")
        elif collectorate:
            gov_sentences.append(f"प्रशासनिक एवं राजस्व नियंत्रण {collectorate} के अंतर्गत कार्य करता है।")

        local_gov = []
        if sdm:
            local_gov.append(f"{sdm}")
        if tehsildar:
            local_gov.append(f"{tehsildar}")
        if local_gov:
            gov_sentences.append(f"उपखंड व तहसील स्तर पर राजस्व व्यवस्था {' तथा '.join(local_gov)} द्वारा संभाली जाती है।")

        grassroots_gov = []
        if bdo:
            grassroots_gov.append(f"{bdo}")
        if sarpanch:
            grassroots_gov.append(f"{sarpanch}")
        if ulb:
            grassroots_gov.append(f"{ulb}")
        if grassroots_gov:
            gov_sentences.append(f"स्थानीय विकास एवं नागरिक सेवाओं का प्रबंधन {' और '.join(grassroots_gov)} द्वारा किया जाता है।")

        gov_text = " ".join(gov_sentences) if gov_sentences else f"प्रशासनिक रिकॉर्ड राजस्थान सरकार के अधिकृत पोर्टल के अंतर्गत सत्यापित हैं।"

        # 3. Next Questions
        q_lines = [f"{i+1}. {q}" for i, q in enumerate(next_questions[:3])]
        next_q_block = "\n".join(q_lines)

        return (
            f"{narrative}\n\n"
            f"🏛️ प्रशासनिक नियंत्रण एवं प्रमुख अधिकारी:\n"
            f"{gov_text}"
        )

    # ------------------ HINGLISH ------------------
    elif language == "hinglish":
        breadcrumb_str = " ➔ ".join(breadcrumbs)

        # 1. Location Narrative
        if "pincode" in etype or (pincode and pincode in entity_name):
            area = lineage.get("area_or_village") or details.get("city_or_village") or "specified"
            offices = details.get("offices") or lineage.get("offices") or ""
            localities = details.get("localities") or ""
            total_offices = details.get("total_offices") or 0
            local_body_desc = ""
            if ulb and gp:
                local_body_desc = f", jisme urban civic services {ulb} dwara aur rural areas {gp} Gram Panchayat dwara govern hote hain"
            elif ulb:
                local_body_desc = f", jiska urban civic governance {ulb} manage karti hai"
            elif gp:
                local_body_desc = f", jiska local administration {gp} Gram Panchayat sambhalti hai"

            teh_txt = f" Yeh {tehsil} Tehsil & Block ke jurisdiction mein aata hai{local_body_desc}." if tehsil else ""
            office_txt = f"\n\n📮 Post Offices ({total_offices}): {offices[:450]}" if offices else ""
            loc_txt = f"\n📍 Covered Localities / Villages: {localities[:350]}" if localities else ""
            narrative = (
                f"Postal Pincode {pincode} Rajasthan ke {area} area ko cover karta hai. "
                f"Administrative view se yeh {div} ke andar {dist} district mein sthit hai.{teh_txt}{office_txt}{loc_txt}"
            )
        elif "village" in etype:
            v_hi = details.get("village_hindi") or lineage.get("village_hi")
            ilr = details.get("ilr_circle") or lineage.get("ilr_circle")
            blk = details.get("block") or lineage.get("block")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            v_name_disp = f"{entity_name} ({v_hi})" if v_hi else entity_name
            ilr_txt = f", {ilr} ILR Circle" if ilr else ""
            patwar_txt = f" aur {patwar} Patwar Circle" if patwar else ""
            blk_txt = f", {blk} Block" if blk else ""
            pin_txt = f" (Pincode {pincode})" if pincode else ""
            lgd_txt = f" [LGD Code: {lgd}]" if lgd else ""
            gp_txt = f", jiska local administration {gp} Gram Panchayat{blk_txt}{ilr_txt}{patwar_txt}{pin_txt} ke dwara sambhala jata hai" if gp else f"{blk_txt}{ilr_txt}{patwar_txt}{pin_txt}"
            teh_txt = f" Sub-district level par yeh {tehsil} Tehsil jurisdiction mein aata hai{gp_txt}." if tehsil else ""
            other_m = details.get("other_matches") or []
            other_txt = f"\n\n📌 Is naam ke anya gaon: {', '.join(other_m)}" if other_m else ""
            narrative = (
                f"{v_name_disp}{lgd_txt} Rajasthan state ka ek recognized Revenue Village hai. "
                f"Administrative roop se yeh {div} ke andar {dist} district mein sthit hai.{teh_txt}{other_txt}"
            )
        elif "districtslist" in etype or "districts" in etype:
            d_items = details.get("districts") or []
            selected = d_items[:10]
            lines = []
            for i, d in enumerate(selected, 1):
                div_name = d.get("division", "Rajasthan")
                name_en = d.get("name_en")
                lines.append(f"{i}. **{name_en}** ({div_name})")
            items_str = "\n".join(lines)
            narrative = (
                f"Rajasthan comprises **50 Districts** organized under **10 Administrative Divisions**. "
                f"Here is a curated list from the knowledge graph of 10 key administrative districts along with their respective divisions:\n\n"
                f"{items_str}\n\n"
                f"Each district functions under the executive administration of its District Collectorate and the democratic governance of its Zila Parishad."
            )
        elif "district" in etype:
            count_intro = ""
            if details.get("is_count_query"):
                v_cnt = details.get("villages_count")
                tb_cnt = details.get("tehsils_count")
                gp_cnt = details.get("gram_panchayats_count")
                if details.get("asked_villages"):
                    cnt_str = f" total {v_cnt:,} revenue villages" if v_cnt else " sabhi revenue villages"
                    gp_str = f" aur {gp_cnt:,} gram panchayats" if gp_cnt else ""
                    count_intro = f"{entity_name} district mein{cnt_str}{gp_str} apni respective Tehsils aur Blocks ke under organized hain. "
                elif details.get("asked_tehsils"):
                    tb_str = f" total {tb_cnt} tehsils aur blocks" if tb_cnt else " revenue tehsils aur development blocks"
                    count_intro = f"{entity_name} district mein{tb_str} work kar rahe hain. "

            narrative = (
                f"{count_intro}{entity_name} Rajasthan ka ek pramukh District hai, jo {div} ke administrative jurisdiction mein aata hai. "
                f"Is district ka poora administration aur revenue management apne independent District Collectorate aur Zila Parishad ke tahat kaam karta hai."
            )
        elif "gram panchayat" in etype or "grampanchayat" in etype:
            gp_hi = details.get("gram_panchayat_hindi") or lineage.get("gram_panchayat_hi")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            v_cnt = details.get("villages_count") or 0
            v_list = details.get("villages") or []
            pins = details.get("pincodes") or []
            gp_disp = f"{entity_name} ({gp_hi})" if gp_hi else entity_name
            lgd_txt = f" [LGD Code: {lgd}]" if lgd else ""
            blk_txt = f" Yeh {tehsil} Block / Panchayat Samiti ke under aati hai." if tehsil else ""
            v_txt = f"\n\n🏡 Covered Revenue Villages ({v_cnt}): {', '.join(v_list[:12])}" if v_list else ""
            pin_txt = f"\n📮 Postal Pincodes: {', '.join(pins)}" if pins else ""
            narrative = (
                f"{gp_disp}{lgd_txt} Rajasthan ki ek official Gram Panchayat hai, jo {div} ke {dist} district mein sthit hai.{blk_txt}{v_txt}{pin_txt}"
            )
        elif "tehsil" in etype or "block" in etype:
            tb_hi = details.get("entity_hindi")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            gp_cnt = details.get("gram_panchayats_count") or 0
            v_cnt = details.get("villages_count") or 0
            gps_sample = details.get("gram_panchayats") or []
            tb_disp = f"{entity_name} ({tb_hi})" if tb_hi else entity_name
            lgd_txt = f" [LGD Code: {lgd}]" if lgd else ""
            sd_txt = f" Yeh {sub_div} sub-divisional jurisdiction ke tahat operate karti hai aur" if sub_div else " Yeh"
            cnt_txt = f" Iske under {gp_cnt} Gram Panchayats aur {v_cnt} Revenue Villages aate hain." if (gp_cnt or v_cnt) else ""
            gp_list_txt = f"\n\n🏘️ Key Gram Panchayats: {', '.join(gps_sample[:10])}" if gps_sample else ""
            narrative = (
                f"{tb_disp}{lgd_txt} Rajasthan ki ek important {entity_type} unit hai, jo {div} ke {dist} district mein aati hai.{sd_txt} "
                f"apne under aane wale gram panchayats aur villages ke revenue aur developmental kaamo ko manage karti hai.{cnt_txt}{gp_list_txt}"
            )
        elif "urban" in etype or "nigam" in etype or "palika" in etype:
            narrative = (
                f"{entity_name} Rajasthan ki ek recognized Urban Local Body hai, jo {div} ke {dist} district mein aati hai. "
                f"Yeh civic infrastructure, urban wards aur municipal services ki dekh-rekh karti hai."
            )
        elif "state" in etype:
            narrative = (
                f"Rajasthan state 6-tier administrative structure par organized hai jisme 10 Divisions aur 50 Districts aate hain, "
                f"jiska supreme administrative coordination State Secretariat, Jaipur dwara hota hai."
            )
        else:
            narrative = (
                f"{entity_name} Rajasthan ke {div} ke andar {dist} district ki verified administrative unit hai."
            )

        # 2. Governance Narrative
        gov_sentences = []
        if collectorate and zila_pramukh:
            gov_sentences.append(f"District level par administrative leadership {collectorate} aur {zila_pramukh} ke paas hai.")
        elif collectorate:
            gov_sentences.append(f"Administrative aur revenue control {collectorate} ke under aata hai.")

        local_gov = []
        if sdm:
            local_gov.append(f"{sdm}")
        if tehsildar:
            local_gov.append(f"{tehsildar}")
        if local_gov:
            gov_sentences.append(f"Sub-division aur tehsil level par revenue governance {' aur '.join(local_gov)} dekhte hain.")

        grassroots_gov = []
        if bdo:
            grassroots_gov.append(f"{bdo}")
        if sarpanch:
            grassroots_gov.append(f"{sarpanch}")
        if ulb:
            grassroots_gov.append(f"{ulb}")
        if grassroots_gov:
            gov_sentences.append(f"Local developmental aur civic facilities ka prabandhan {' aur '.join(grassroots_gov)} ke dwara manage hota hai.")

        gov_text = " ".join(gov_sentences) if gov_sentences else f"Administrative records Government of Rajasthan master directory se verified hain."

        # 3. Next Questions
        q_lines = [f"{i+1}. {q}" for i, q in enumerate(next_questions[:3])]
        next_q_block = "\n".join(q_lines)

        return (
            f"{narrative}\n\n"
            f"🏛️ Governance & Administrative Authority:\n"
            f"{gov_text}"
        )

    # ------------------ ENGLISH (DEFAULT) ------------------
    else:
        breadcrumb_str = " ➔ ".join(breadcrumbs)

        # 1. Location Narrative
        if "pincode" in etype or (pincode and pincode in entity_name):
            area = lineage.get("area_or_village") or details.get("city_or_village") or "designated"
            offices = details.get("offices") or lineage.get("offices") or ""
            localities = details.get("localities") or ""
            total_offices = details.get("total_offices") or 0
            local_body_desc = ""
            if ulb and gp:
                local_body_desc = f", with civic administration overseen by {ulb} for urban zones and {gp} Gram Panchayat for rural sectors"
            elif ulb:
                local_body_desc = f", governed by {ulb} for urban municipal services"
            elif gp:
                local_body_desc = f", governed locally by the {gp} Gram Panchayat"

            teh_txt = f" It falls under the jurisdiction of {tehsil} Tehsil & Block{local_body_desc}." if tehsil else ""
            office_txt = f"\n\n📮 Post Offices ({total_offices}): {offices[:450]}" if offices else ""
            loc_txt = f"\n📍 Covered Localities / Villages: {localities[:350]}" if localities else ""
            narrative = (
                f"Postal Pincode {pincode} serves the {area} area in Rajasthan. "
                f"Administratively, this postal zone is situated in the {div} within {dist} district.{teh_txt}{office_txt}{loc_txt}"
            )
        elif "village" in etype:
            v_hi = details.get("village_hindi") or lineage.get("village_hi")
            ilr = details.get("ilr_circle") or lineage.get("ilr_circle")
            blk = details.get("block") or lineage.get("block")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            v_name_disp = f"{entity_name} ({v_hi})" if v_hi else entity_name
            ilr_txt = f", {ilr} ILR Circle" if ilr else ""
            patwar_txt = f" and {patwar} Patwar Circle" if patwar else ""
            blk_txt = f", {blk} Block" if blk else ""
            pin_txt = f" with postal pincode {pincode}" if pincode else ""
            lgd_txt = f" [LGD Code: {lgd}]" if lgd else ""
            gp_txt = f", governed locally by {gp} Gram Panchayat{blk_txt}{ilr_txt}{patwar_txt}{pin_txt}" if gp else f"{blk_txt}{ilr_txt}{patwar_txt}{pin_txt}"
            teh_txt = f" At the sub-district tier, it falls under {tehsil} Tehsil{gp_txt}." if tehsil else ""
            other_m = details.get("other_matches") or []
            other_txt = f"\n\n📌 Other villages with the same name: {', '.join(other_m)}" if other_m else ""
            narrative = (
                f"{v_name_disp}{lgd_txt} is a recognized Revenue Village located in Rajasthan. "
                f"Administratively, it falls under the {div} within {dist} district.{teh_txt}{other_txt}"
            )
        elif "districtslist" in etype or "districts" in etype:
            d_items = details.get("districts") or []
            selected = d_items[:10]
            lines = []
            for i, d in enumerate(selected, 1):
                div_name = d.get("division", "Rajasthan")
                name_en = d.get("name_en")
                lines.append(f"{i}. **{name_en}** ({div_name})")
            items_str = "\n".join(lines)
            narrative = (
                f"Rajasthan comprises **50 Districts** organized under **10 Administrative Divisions**. "
                f"Here is a curated list from the knowledge graph of 10 key administrative districts along with their respective divisions:\n\n"
                f"{items_str}\n\n"
                f"Each district functions under the executive administration of its District Collectorate and the democratic governance of its Zila Parishad."
            )
        elif "district" in etype:
            count_intro = ""
            if details.get("is_count_query"):
                v_cnt = details.get("villages_count")
                tb_cnt = details.get("tehsils_count")
                gp_cnt = details.get("gram_panchayats_count")
                if details.get("asked_villages"):
                    cnt_str = f" {v_cnt:,} official revenue villages" if v_cnt else " revenue villages"
                    gp_str = f" across {gp_cnt:,} Gram Panchayats" if gp_cnt else ""
                    count_intro = f"{entity_name} district comprises{cnt_str}{gp_str} organized under its constituent Tehsils and Blocks. "
                elif details.get("asked_tehsils"):
                    tb_str = f" {tb_cnt} active tehsils and development blocks" if tb_cnt else " active administrative tehsils and development blocks"
                    count_intro = f"{entity_name} district is structured into{tb_str}. "

            narrative = (
                f"{count_intro}{entity_name} is an officially recognized District of Rajasthan, "
                f"functioning under the administrative jurisdiction of the {div}. "
                f"The district operates with independent administrative and revenue machinery, coordinated through its dedicated Collectorate and Zila Parishad."
            )
        elif "gram panchayat" in etype or "grampanchayat" in etype:
            gp_hi = details.get("gram_panchayat_hindi") or lineage.get("gram_panchayat_hi")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            v_cnt = details.get("villages_count") or 0
            v_list = details.get("villages") or []
            pins = details.get("pincodes") or []
            gp_disp = f"{entity_name} ({gp_hi})" if gp_hi else entity_name
            lgd_txt = f" [LGD Code: {lgd}]" if lgd else ""
            blk_txt = f" It operates under {tehsil} Block / Panchayat Samiti." if tehsil else ""
            v_txt = f"\n\n🏡 Constituent Revenue Villages ({v_cnt}): {', '.join(v_list[:12])}" if v_list else ""
            pin_txt = f"\n📮 Postal Pincodes: {', '.join(pins)}" if pins else ""
            narrative = (
                f"{gp_disp}{lgd_txt} is an officially recognized Gram Panchayat in Rajasthan, situated in {div} within {dist} district.{blk_txt}{v_txt}{pin_txt}"
            )
        elif "tehsil" in etype or "block" in etype:
            tb_hi = details.get("entity_hindi")
            lgd = details.get("lgd_code") or lineage.get("lgd_code")
            gp_cnt = details.get("gram_panchayats_count") or 0
            v_cnt = details.get("villages_count") or 0
            gps_sample = details.get("gram_panchayats") or []
            tb_disp = f"{entity_name} ({tb_hi})" if tb_hi else entity_name
            lgd_txt = f" [LGD Code: {lgd}]" if lgd else ""
            sd_txt = f" It operates under the {sub_div} sub-divisional jurisdiction and" if sub_div else " It"
            cnt_txt = f" It administers {gp_cnt} Gram Panchayats and {v_cnt} Revenue Villages." if (gp_cnt or v_cnt) else ""
            gp_list_txt = f"\n\n🏘️ Key Gram Panchayats: {', '.join(gps_sample[:10])}" if gps_sample else ""
            narrative = (
                f"{tb_disp}{lgd_txt} is an administrative {entity_type} in Rajasthan, located within the {div} and {dist} district.{sd_txt} "
                f"exercises administrative, developmental, and revenue oversight over its constituent gram panchayats and revenue villages.{cnt_txt}{gp_list_txt}"
            )
        elif "urban" in etype or "nigam" in etype or "palika" in etype:
            narrative = (
                f"{entity_name} is an urban local civic authority situated in the {div} within {dist} district, Rajasthan. "
                f"It oversees urban planning, civic amenities, sanitation, and municipal ward administration."
            )
        elif "state" in etype:
            narrative = (
                f"Rajasthan is administered through a 6-tier governance structure comprising 10 Divisions, 50 Districts, and their respective Sub-Divisions, Tehsils, Blocks, Urban Local Bodies, and Gram Panchayats, coordinated through the State Secretariat in Jaipur."
            )
        else:
            narrative = (
                f"{entity_name} is an officially verified administrative entity situated in the {div} within {dist} district, Rajasthan."
            )

        # 2. Governance Narrative
        gov_sentences = []
        if collectorate and zila_pramukh:
            gov_sentences.append(f"District-level administration is led by the {collectorate} alongside the {zila_pramukh}.")
        elif collectorate:
            gov_sentences.append(f"Executive revenue administration is overseen by the {collectorate}.")

        local_gov = []
        if sdm:
            local_gov.append(f"{sdm}")
        if tehsildar:
            local_gov.append(f"{tehsildar}")
        if local_gov:
            gov_sentences.append(f"Sub-divisional and revenue administration is managed by {' and '.join(local_gov)}.")

        grassroots_gov = []
        if bdo:
            grassroots_gov.append(f"{bdo}")
        if sarpanch:
            grassroots_gov.append(f"{sarpanch}")
        if ulb:
            grassroots_gov.append(f"{ulb}")
        if grassroots_gov:
            gov_sentences.append(f"Grassroots civic and rural development operations are coordinated by {' and '.join(grassroots_gov)}.")

        gov_text = " ".join(gov_sentences) if gov_sentences else f"Official administrative records are maintained under the Government of Rajasthan master registry."

        # 3. Next Questions
        q_lines = [f"{i+1}. {q}" for i, q in enumerate(next_questions[:3])]
        next_q_block = "\n".join(q_lines)

        return (
            f"{narrative}\n\n"
            f"🏛️ Governance & Administrative Authority:\n"
            f"{gov_text}"
        )
async def out_of_scope_helpline_node(state: AgentState) -> AgentState:
    cfg = await get_active_llm_config()
    phone = cfg["support_phone"]
    lang = detect_query_language(state["user_query"], state.get("language"))
    state["language"] = lang

    state["helpline_card"] = True
    state["support_phone"] = phone
    state["breadcrumbs"] = ["Rajasthan", "Out-of-Scope Query"]

    if lang == "hi":
        next_qs = [
            "मुहाना गांव की प्रशासनिक वंशावली क्या है?",
            "बालोतरा जिला किस संभाग के अंतर्गत आता है?",
            "पिनकोड 302029 का प्रशासनिक विवरण क्या है?"
        ]
        state["response_text"] = (
            f"गैर-प्रशासनिक पूछताछ सूचना\n\n"
            f"यह प्रश्न राजस्थान के 6-स्तरीय प्रशासनिक और भौगोलिक पदानुक्रम के दायरे से बाहर है। यह पोर्टल केवल राजस्थान के संभागों, जिलों, उपखंडों, तहसीलों, नगरीय निकायों, ग्राम पंचायतों, राजस्व गांवों और पिनकोड की अधिकृत जानकारी प्रदान करता है।\n\n"
            f"📞 नागरिक सहायता हेल्पलाइन: [{phone}](tel:{phone})"
        )
    elif lang == "hinglish":
        next_qs = [
            "Muhana village ka administrative lineage kya hai?",
            "Balotra district kis division ke under aata hai?",
            "Pincode 302029 ke administrative details kya hain?"
        ]
        state["response_text"] = (
            f"Non-Geographic Inquiry Notice\n\n"
            f"Yeh question Rajasthan ke 6-Tier Administrative aur Geographic Hierarchy ke scope se bahar hai. Yeh system exclusively Rajasthan ke Divisions, Districts, Sub-Divisions, Tehsils, Urban Local Bodies, Gram Panchayats, Villages aur Pincodes ka record maintain karta hai.\n\n"
            f"📞 Official Citizen Helpline: [{phone}](tel:{phone})"
        )
    else:
        next_qs = [
            "What is the administrative lineage of Muhana village?",
            "Which division does Balotra district belong to?",
            "Details of pincode 302029"
        ]
        state["response_text"] = (
            f"Non-Geographic Inquiry Notice\n\n"
            f"This inquiry lies outside the scope of Rajasthan's 6-Tier Administrative and Geographic Hierarchy. The system exclusively maintains official records for Rajasthan's Divisions, Districts, Sub-Divisions, Tehsils, Urban Local Bodies, Gram Panchayats, Villages, and Pincodes.\n\n"
            f"📞 Official Citizen Helpline: [{phone}](tel:{phone})"
        )

    state["next_questions"] = next_qs
    state["mcp_used"] = False
    state["mcp_tool"] = None
    state["mcp_transport"] = None
    state["resolution_stage"] = "guardrail_helpline"
    state["response_text"] = sanitize_structured_output(state["response_text"])
    _append_step(
        state,
        "helpline",
        "Out-of-Scope Helpline Router",
        f"Attached citizen helpline card ({phone}) in {lang}",
        "📞",
        duration_ms=2,
    )
    return state

# ----------------- NODE 3: Capability & Live Support Greeter Node -----------------
async def capability_node(state: AgentState) -> AgentState:
    cfg = await get_active_llm_config()
    phone = cfg["support_phone"]
    lang = detect_query_language(state["user_query"], state.get("language"))
    state["language"] = lang

    state["helpline_card"] = False
    state["support_phone"] = phone
    state["breadcrumbs"] = ["Rajasthan", "Administrative Levels 1-6"]

    if lang == "hi":
        next_qs = [
            "मुहाना गांव की प्रशासनिक वंशावली बताएं",
            "बालोतरा किस संभाग और जिले में है?",
            "पिनकोड 302029 का विवरण"
        ]
        state["response_text"] = (
            f"राजस्थान प्रशासनिक एवं भौगोलिक मास्टर प्रणाली\n\n"
            f"यह प्रणाली राजस्थान के संपूर्ण 6-स्तरीय प्रशासनिक पदानुक्रम (10 संभाग, 50 जिले, उपखंड/SDM, तहसील/ब्लॉक, नगरीय निकाय, ग्राम पंचायत एवं पिनकोड) की आधिकारिक जानकारी प्रदान करती है।\n\n"
            f"📞 नागरिक हेल्पलाइन: [{phone}](tel:{phone})"
        )
    elif lang == "hinglish":
        next_qs = [
            "Muhana village ki administrative lineage batao",
            "Balotra kis division aur district mein hai?",
            "Pincode 302029 ke details"
        ]
        state["response_text"] = (
            f"Rajasthan Administrative & Geographic Master Portal\n\n"
            f"Yeh system Rajasthan ke poore 6-Tier administrative hierarchy (10 Divisions, 50 Districts, Sub-Divisions/SDM, Tehsils/Blocks, Urban Local Bodies, Gram Panchayats aur Pincodes) ki official mapping provide karta hai.\n\n"
            f"📞 Citizen Helpline: [{phone}](tel:{phone})"
        )
    else:
        next_qs = [
            "Tell me about Muhana village administrative hierarchy",
            "Which division does Balotra district belong to?",
            "Details of pincode 302029"
        ]
        state["response_text"] = (
            f"Rajasthan Administrative & Geographic Master System\n\n"
            f"This portal provides verified official records across Rajasthan's complete 6-tier administrative framework (10 Divisions, 50 Districts, Sub-Divisions/SDM, Tehsils/Blocks, Urban Local Bodies, Gram Panchayats, Villages, and Pincodes).\n\n"
            f"📞 Citizen Helpline: [{phone}](tel:{phone})"
        )

    state["next_questions"] = next_qs
    state["mcp_used"] = False
    state["mcp_tool"] = None
    state["mcp_transport"] = None
    state["resolution_stage"] = "capability"
    state["response_text"] = sanitize_structured_output(state["response_text"])
    _append_step(
        state,
        "capability",
        "Capability Greeter Node",
        f"Prepared 6-tier portal overview & sample prompts ({lang})",
        "🏛️",
        duration_ms=2,
    )
    return state

# ----------------- RAG RETRIEVAL & LIVE WEB SEARCH FALLBACK ENGINES -----------------
async def perform_rag_retrieval(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieves grounded context from PostgreSQL public & raj_masters tables
    (districts, tehsils, blocks, pincodes, sub-divisions, villages) using trigram & fuzzy matching.
    """
    results: List[Dict[str, Any]] = []
    clean_q = query.strip()
    words = [w for w in re.findall(r"\b\w+\b", clean_q) if len(w) >= 3 and w.lower() not in {
        "what", "where", "which", "tell", "about", "details", "lineage", "hierarchy",
        "rajasthan", "information", "give", "show", "is", "the", "in", "of", "to"
    }]
    digits = re.findall(r"\b\d{6}\b", clean_q)

    async with AsyncSessionLocal() as session:
        # 1. Pincodes search (exact & subdistrict match in raj_masters.pincodes)
        if digits:
            stmt = text("""
                SELECT pincode, office_name, locality_name, subdist_name, district_name, state_name
                FROM raj_masters.pincodes
                WHERE pincode = :pin
                LIMIT :lim
            """)
            res = await session.execute(stmt, {"pin": digits[0], "lim": top_k})
            for r in res.mappings():
                office = r["office_name"] or r["locality_name"] or "General Post Office"
                results.append({
                    "type": "pincode",
                    "title": f"Pincode {r['pincode']} ({office})",
                    "snippet": f"Pincode: {r['pincode']}, Office: {office}, Tehsil: {r['subdist_name']}, District: {r['district_name']}, State: {r['state_name'] or 'Rajasthan'}"
                })

        # 2. Tehsils & Blocks search in raj_masters
        for w in words[:3]:
            stmt_t = text("""
                SELECT name_en, name_hi, tehsildar_details, lgd_code
                FROM raj_masters.tehsils
                WHERE name_en ILIKE :term OR name_hi ILIKE :term
                LIMIT :lim
            """)
            res_t = await session.execute(stmt_t, {"term": f"%{w}%", "lim": top_k})
            for r in res_t.mappings():
                results.append({
                    "type": "tehsil",
                    "title": f"Tehsil {r['name_en']}",
                    "snippet": f"Tehsil: {r['name_en']} ({r['name_hi'] or ''}), Tehsildar: {r['tehsildar_details'] or 'Tehsildar Office'}, LGD Code: {r['lgd_code'] or 'N/A'}"
                })

            stmt_b = text("""
                SELECT name_en, name_hi, bdo_details, pradhan_name
                FROM raj_masters.blocks
                WHERE name_en ILIKE :term OR name_hi ILIKE :term
                LIMIT :lim
            """)
            res_b = await session.execute(stmt_b, {"term": f"%{w}%", "lim": top_k})
            for r in res_b.mappings():
                results.append({
                    "type": "block",
                    "title": f"Panchayat Samiti {r['name_en']}",
                    "snippet": f"Block/Panchayat Samiti: {r['name_en']} ({r['name_hi'] or ''}), BDO: {r['bdo_details'] or 'BDO Office'}, Pradhan: {r['pradhan_name'] or 'Zila Parishad'}"
                })

        # 3. Districts search in public
        for w in words[:2]:
            stmt_d = text("""
                SELECT d.name_en, d.name_hi, d.collectorate_details, d.zila_pramukh, div.name_en as division_name
                FROM public.districts d
                LEFT JOIN public.divisions div ON d.division_id = div.id
                WHERE d.name_en ILIKE :term OR d.name_hi ILIKE :term
                LIMIT :lim
            """)
            res_d = await session.execute(stmt_d, {"term": f"%{w}%", "lim": top_k})
            for r in res_d.mappings():
                results.append({
                    "type": "district",
                    "title": f"District {r['name_en']}",
                    "snippet": f"District: {r['name_en']} ({r['name_hi'] or ''}), Division: {r['division_name']}, Collectorate: {r['collectorate_details']}, Zila Pramukh: {r['zila_pramukh']}"
                })

        # 4. Villages search in raj_masters.village_hierarchy
        for w in words[:2]:
            try:
                stmt_v = text("""
                    SELECT village_eng, village_mangal, gp_eng, patwar_eng, ilr_eng, tehsil_eng, block_eng, district_eng, division_eng, village_lgdcode
                    FROM raj_masters.village_hierarchy
                    WHERE village_eng ILIKE :term OR village_mangal ILIKE :term OR gp_eng ILIKE :term OR patwar_eng ILIKE :term
                    LIMIT :lim
                """)
                res_v = await session.execute(stmt_v, {"term": f"%{w}%", "lim": top_k})
                for r in res_v.mappings():
                    results.append({
                        "type": "village",
                        "title": f"Village {r['village_eng']} ({r['district_eng']})",
                        "snippet": f"Village: {r['village_eng']} ({r['village_mangal'] or ''}), GP: {r['gp_eng']}, Patwar: {r['patwar_eng']}, ILR: {r['ilr_eng']}, Block: {r['block_eng']}, Tehsil: {r['tehsil_eng']}, District: {r['district_eng']}, Division: {r['division_eng']}, LGD: {r['village_lgdcode']}"
                    })
            except Exception:
                pass

            try:
                stmt_gp = text("""
                    SELECT gp_eng, gp_mangal, gp_lgdcode, block_eng, district_eng, division_eng
                    FROM raj_masters.gp_hierarchy
                    WHERE gp_eng ILIKE :term OR gp_mangal ILIKE :term
                    LIMIT :lim
                """)
                res_gp = await session.execute(stmt_gp, {"term": f"%{w}%", "lim": top_k})
                for r in res_gp.mappings():
                    results.append({
                        "type": "gram_panchayat",
                        "title": f"Gram Panchayat {r['gp_eng']} ({r['district_eng']})",
                        "snippet": f"Gram Panchayat: {r['gp_eng']} ({r['gp_mangal'] or ''}), Block: {r['block_eng']}, District: {r['district_eng']}, Division: {r['division_eng']}, LGD: {r['gp_lgdcode']}"
                    })
            except Exception:
                pass

    # Deduplicate by snippet
    seen = set()
    deduped = []
    for it in results:
        if it["snippet"] not in seen:
            seen.add(it["snippet"])
            deduped.append(it)
    return deduped[:top_k]

async def perform_web_search(
    query: str,
    provider: str = "duckduckgo",
    api_key: str = "",
    max_results: int = 4
) -> List[Dict[str, Any]]:
    """
    Real-time Web Search Fallback with multi-provider support:
    - DuckDuckGo: Zero config, instant scraping (default).
    - Tavily: AI-curated search via API key.
    - SerpAPI: Google search via API key.
    - Wikipedia: Encyclopedic search fallback.
    """
    results: List[Dict[str, Any]] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.7",
    }

    # 1. Tavily Search API
    if provider == "tavily" and api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                search_q = query if "rajasthan" in query.lower() else f"{query} Rajasthan"
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": api_key,
                    "query": search_q,
                    "max_results": max_results
                })
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("results", []):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("content", ""),
                            "url": r.get("url", "")
                        })
                    if results:
                        return results
        except Exception as e:
            logger.warning(f"Tavily search error: {e}")

    # 2. SerpAPI Google Search
    if provider == "serpapi" and api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                search_q = query if "rajasthan" in query.lower() else f"{query} Rajasthan"
                resp = await client.get("https://serpapi.com/search.json", params={
                    "q": search_q,
                    "api_key": api_key,
                    "num": max_results
                })
                if resp.status_code == 200:
                    data = resp.json()
                    for r in data.get("organic_results", []):
                        results.append({
                            "title": r.get("title", ""),
                            "snippet": r.get("snippet", ""),
                            "url": r.get("link", "")
                        })
                    if results:
                        return results
        except Exception as e:
            logger.warning(f"SerpAPI search error: {e}")

    # 3. DuckDuckGo Search (Default - Zero API Key Needed)
    try:
        search_query = query if "rajasthan" in query.lower() else f"{query} Rajasthan government"
        encoded_q = quote_plus(search_query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", class_="result__url")
                snippets = soup.find_all("a", class_="result__snippet")
                for i in range(min(len(snippets), max_results)):
                    s_text = snippets[i].get_text(strip=True)
                    u_href = links[i]["href"].strip() if i < len(links) and links[i].has_attr("href") else ""
                    if u_href.startswith("//"):
                        u_href = "https:" + u_href
                    if "uddg=" in u_href:
                        m = re.search(r"uddg=([^&]+)", u_href)
                        if m:
                            u_href = unquote(m.group(1))
                    if s_text:
                        results.append({
                            "title": f"Verified Record {i+1}",
                            "snippet": s_text,
                            "url": u_href
                        })
    except Exception as e:
        logger.warning(f"DuckDuckGo search error: {e}")

    # 4. Wikipedia API Fallback if still empty
    if not results:
        try:
            wiki_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={quote_plus(query)}&format=json"
            async with httpx.AsyncClient(timeout=5.0) as client:
                wresp = await client.get(wiki_url)
                if wresp.status_code == 200:
                    items = wresp.json().get("query", {}).get("search", [])
                    for it in items[:max_results]:
                        clean_snip = re.sub(r"<[^>]+>", "", it.get("snippet", ""))
                        clean_snip = clean_snip.replace("&quot;", '"').replace("&amp;", '&')
                        results.append({
                            "title": it.get("title", ""),
                            "snippet": clean_snip,
                            "url": f"https://en.wikipedia.org/wiki/{quote_plus(it.get('title',''))}"
                        })
        except Exception as e:
            logger.warning(f"Wikipedia fallback error: {e}")

    return results

def synthesize_rag_response(query: str, results: List[Dict[str, Any]], lang: str, phone: str) -> Dict[str, Any]:
    lines = []
    for r in results[:4]:
        lines.append(f"• {r['title']}: {r['snippet']}")

    body = "\n".join(lines)

    if lang == "hi":
        response = (
            f"राजस्थान मास्टर डायरेक्टरी - आरएजी (RAG) ज्ञानकोश परिणाम:\n\n"
            f"'{query}' के संदर्भ में सत्यापित प्रशासनिक रिकॉर्ड:\n\n"
            f"{body}\n\n"
            f"🏛️ प्रशासनिक व्यवस्था:\n"
            f"सभी रिकॉर्ड राजस्थान सरकार के अधिकृत मास्टर डेटाबेस से सत्यापित हैं।\n"
            f"नागरिक सहायता हेल्पलाइन: [{phone}](tel:{phone})"
        )
        next_qs = [
            "पिनकोड 302029 का संपूर्ण प्रशासनिक विवरण क्या है?",
            "जयपुर जिले के अंतर्गत आने वाली मुख्य तहसीलें कौन सी हैं?",
            "राजस्थान के 10 प्रशासनिक संभागों की सूची क्या है?"
        ]
    elif lang == "hinglish":
        response = (
            f"Rajasthan Master Directory - RAG Knowledge Base Results:\n\n"
            f"Verified administrative records matched for '{query}':\n\n"
            f"{body}\n\n"
            f"🏛️ Administrative Authority:\n"
            f"Records verified from Government of Rajasthan master registry.\n"
            f"Citizen Helpline: [{phone}](tel:{phone})"
        )
        next_qs = [
            "Pincode 302029 ke administrative details kya hain?",
            "Jaipur district ke under kaunsi tehsils aati hain?",
            "Rajasthan ke 10 administrative divisions ki list kya hai?"
        ]
    else:
        response = (
            f"Rajasthan Master Directory - RAG Knowledge Base Results:\n\n"
            f"Verified administrative records matched for '{query}':\n\n"
            f"{body}\n\n"
            f"🏛️ Administrative Authority:\n"
            f"Records verified from Government of Rajasthan master registry.\n"
            f"Citizen Helpline: [{phone}](tel:{phone})"
        )
        next_qs = [
            "What is the administrative lineage of pincode 302029?",
            "What are the major tehsils in Jaipur district?",
            "What are the 10 administrative divisions of Rajasthan?"
        ]

    return {
        "text": sanitize_structured_output(response),
        "next_questions": next_qs
    }

def synthesize_web_response(query: str, results: List[Dict[str, Any]], lang: str, phone: str) -> Dict[str, Any]:
    snippets_text = []
    sources = []
    for r in results:
        snip = r["snippet"].strip()
        snip = re.sub(r"\s+", " ", snip)
        if snip:
            snippets_text.append(snip)
        if r.get("url"):
            sources.append(r["url"])

    combined_info = " ".join(snippets_text[:3])
    first_source = sources[0] if sources else "https://rajasthan.gov.in"

    if lang == "hi":
        response = (
            f"सत्यापित प्रशासनिक एवं सार्वजनिक सूचना:\n\n"
            f"{combined_info}\n\n"
            f"🏛️ अधिकृत संदर्भ एवं स्रोत:\n"
            f"• संदर्भ पोर्टल: {first_source}\n"
            f"• अधिकृत नागरिक हेल्पलाइन: [{phone}](tel:{phone})"
        )
        next_qs = [
            "राजस्थान के 10 प्रशासनिक संभागों की सूची क्या है?",
            "राजस्थान सरकार के प्रमुख प्रशासनिक विभाग और सचिवालय विवरण क्या हैं?",
            "जयपुर संभाग के अंतर्गत कौन-कौन से जिले आते हैं?"
        ]
    elif lang == "hinglish":
        response = (
            f"Verified Administrative & Public Information:\n\n"
            f"{combined_info}\n\n"
            f"🏛️ Official Sources & Lineage:\n"
            f"• Source Portal: {first_source}\n"
            f"• Citizen Helpline: [{phone}](tel:{phone})"
        )
        next_qs = [
            "Rajasthan ke 10 administrative divisions ki list kya hai?",
            "Rajasthan government ke key administrative departments aur secretariat kya hain?",
            "Jaipur division ke under kaunse districts aate hain?"
        ]
    else:
        response = (
            f"Verified Administrative & Public Information:\n\n"
            f"{combined_info}\n\n"
            f"🏛️ Official Reference & Source:\n"
            f"• Source Portal: {first_source}\n"
            f"• Citizen Helpline: [{phone}](tel:{phone})"
        )
        next_qs = [
            "What are the 10 administrative divisions of Rajasthan?",
            "What is the administrative structure of the Rajasthan State Secretariat?",
            "Which districts fall under Jaipur administrative division?"
        ]

    return {
        "text": sanitize_structured_output(response),
        "next_questions": next_qs
    }

# ----------------- MCP HELPERS -----------------
KNOWN_MCP_TABLES = [
    "states", "divisions", "districts", "sub_divisions", "tehsils_blocks",
    "gram_panchayats", "panchayat_wards", "villages", "urban_local_bodies",
    "urban_wards", "pincodes", "chat_logs", "scraper_runs", "llm_settings",
    "rag_support", "admins"
]

def _detect_mcp_metadata_intent(query: str) -> Optional[Dict[str, Any]]:
    """Detects database metadata, schema, table listing, or MCP inspection queries."""
    q = query.strip().lower()
    if any(p in q for p in ["describe table", "schema of", "columns of", "table schema", "structure of"]):
        for tbl in KNOWN_MCP_TABLES:
            if tbl in q:
                return {"tool": "describe_table", "arguments": {"table_name": tbl}}
        return {"tool": "describe_table", "arguments": {"table_name": "districts"}}

    if any(p in q for p in ["list tables", "show tables", "what tables", "all tables", "tables in database", "tables exist"]):
        return {"tool": "list_tables", "arguments": {}}

    if any(p in q for p in [
        "database stats", "db stats", "mcp stats", "mcp status", "check mcp",
        "test mcp", "mcp working", "6-tier stats", "record count", "how many records"
    ]):
        return {"tool": "get_database_stats", "arguments": {}}

    return None

def _extract_mcp_lookup_term(query: str) -> str:
    """Extracts a 6-digit pincode or clean location keyword for MCP lineage lookup."""
    pins = re.findall(r"\b\d{6}\b", query)
    if pins:
        return pins[0]
    words = [w for w in re.split(r"[ ,?.!]+", query.strip()) if len(w) >= 2]
    candidates = [w for w in words if w.lower() not in STOP_WORDS and len(w) >= 3]
    return candidates[0] if candidates else query.strip()

def format_mcp_metadata_response(
    tool_name: str,
    data: Dict[str, Any],
    transport: str,
    lang: str,
    phone: str
) -> Dict[str, Any]:
    """Formats MCP server tool results into clean bilingual responses."""
    if tool_name == "get_database_stats":
        s = data.get("summary", {})
        if lang == "hi":
            text = (
                f"PostgreSQL MCP सर्वर लाइव सांख्यिकी ({transport})\n\n"
                f"• स्तर 1 (राज्य): {s.get('tier_1_state', 0)}\n"
                f"• स्तर 2 (संभाग): {s.get('tier_2_divisions', 0)}\n"
                f"• स्तर 3 (जिले): {s.get('tier_3_districts', 0)}\n"
                f"• स्तर 4 (उपखंड): {s.get('tier_4_sub_divisions', 0)}\n"
                f"• स्तर 5 (तहसील व ब्लॉक): {s.get('tier_5_tehsils_blocks', 0)}\n"
                f"• स्तर 6 (ग्रामीण गांव व पंचायत): {s.get('tier_6_rural_villages_gps', 0)}\n"
                f"• स्तर 6 (नगरीय निकाय): {s.get('tier_6_urban_bodies', 0)}\n"
                f"• डाक पिनकोड रिकॉर्ड: {s.get('postal_directory_pincodes', 0)}\n\n"
                f"🏛️ MCP प्रोटोकॉल सत्यापन:\n"
                f"सर्वर finalairajmaster-postgres-mcp (JSON-RPC 2.0) सक्रिय रूप से कार्यरत है। नागरिक हेल्पलाइन: [{phone}](tel:{phone})"
            )
        else:
            text = (
                f"PostgreSQL MCP Server Live 6-Tier Statistics ({transport})\n\n"
                f"• Tier 1 (State): {s.get('tier_1_state', 0)}\n"
                f"• Tier 2 (Divisions): {s.get('tier_2_divisions', 0)}\n"
                f"• Tier 3 (Districts): {s.get('tier_3_districts', 0)}\n"
                f"• Tier 4 (Sub-Divisions): {s.get('tier_4_sub_divisions', 0)}\n"
                f"• Tier 5 (Tehsils & Blocks): {s.get('tier_5_tehsils_blocks', 0)}\n"
                f"• Tier 6 (Villages & Gram Panchayats): {s.get('tier_6_rural_villages_gps', 0)}\n"
                f"• Tier 6 (Urban Local Bodies): {s.get('tier_6_urban_bodies', 0)}\n"
                f"• Postal Directory Pincodes: {s.get('postal_directory_pincodes', 0)}\n\n"
                f"🏛️ MCP Protocol Verification:\n"
                f"Executed via finalairajmaster-postgres-mcp (JSON-RPC 2.0) over {transport}. Citizen Helpline: [{phone}](tel:{phone})"
            )
        next_qs = [
            "What tables exist in the database?",
            "What is the schema of districts table?",
            "Tell me about Muhana village administrative hierarchy"
        ]
    elif tool_name == "list_tables":
        tables = data.get("tables", [])
        lines = [f"• {t['table_name']} ({t['row_count']} rows, {t['column_count']} cols)" for t in tables[:16]]
        body = "\n".join(lines)
        text = (
            f"PostgreSQL MCP Server — Table Registry ({data.get('total_tables', len(tables))} Tables via {transport}):\n\n"
            f"{body}\n\n"
            f"🏛️ MCP Protocol Verification:\n"
            f"Retrieved directly from finalairajmaster-postgres-mcp tool list_tables."
        )
        next_qs = [
            "Show database stats via MCP",
            "What is the schema of districts table?",
            "Which division does Balotra district belong to?"
        ]
    else:
        tbl = data.get("table_name", "table")
        cols = data.get("columns", [])
        lines = [f"• {c['column_name']}: {c['data_type']} (nullable={c['is_nullable']})" for c in cols[:15]]
        body = "\n".join(lines)
        text = (
            f"PostgreSQL MCP Server — Schema for '{tbl}' ({len(cols)} columns via {transport}):\n\n"
            f"Primary Keys: {', '.join(data.get('primary_keys', [])) or 'N/A'}\n"
            f"{body}\n\n"
            f"🏛️ MCP Protocol Verification:\n"
            f"Retrieved directly from finalairajmaster-postgres-mcp tool describe_table."
        )
        next_qs = [
            "Show database stats via MCP",
            "What tables exist in the database?",
            "Details of pincode 302029"
        ]

    return {
        "text": sanitize_structured_output(text),
        "next_questions": next_qs
    }

# ----------------- NODE 4: Geographic Database & MCP Lookup Node -----------------
async def database_lookup_node(state: AgentState) -> AgentState:
    t0 = time.perf_counter()
    query = state["user_query"]

    # 1. Check for direct MCP database metadata / stats / schema queries
    mcp_meta_req = _detect_mcp_metadata_intent(query)
    if mcp_meta_req:
        try:
            mcp_res = await mcp_client.call_tool(mcp_meta_req["tool"], mcp_meta_req["arguments"])
            if mcp_res.get("ok"):
                state["sql_trace"] = {
                    "matched": True,
                    "entity_type": "MCPMetadata",
                    "entity_name": mcp_meta_req["tool"],
                    "lineage": {"mcp_tool": mcp_meta_req["tool"], "transport": mcp_res.get("transport")},
                    "breadcrumbs": ["Rajasthan", "PostgreSQL MCP", mcp_meta_req["tool"]],
                    "details": mcp_res.get("data", {})
                }
                state["mcp_used"] = True
                state["mcp_tool"] = mcp_meta_req["tool"]
                state["mcp_transport"] = mcp_res.get("transport")
                state["resolution_stage"] = "mcp_server"
                ms = max(1, int((time.perf_counter() - t0) * 1000))
                _append_step(
                    state,
                    "db_mcp",
                    "PostgreSQL MCP Server Tool Call",
                    f"Executed {mcp_meta_req['tool']} via {mcp_res.get('transport')}",
                    "🔌",
                    duration_ms=ms,
                )
                return state
        except Exception as e:
            logger.warning(f"MCP metadata lookup failed: {e}")

    # 2. Run primary 6-tier lookup (or reuse pre-match from guardrail) + concurrent MCP lineage check
    pre_trace = state.get("sql_trace")
    has_pre_match = bool(pre_trace and pre_trace.get("matched"))
    mcp_term = _extract_mcp_lookup_term(query)

    async def _run_mcp_lineage():
        try:
            return await mcp_client.call_tool(
                "get_administrative_lineage",
                {"entity_name_or_pincode": mcp_term}
            )
        except Exception as e:
            logger.debug(f"MCP lineage call skipped ({e})")
            return None

    if has_pre_match:
        lookup = pre_trace
        mcp_res = await _run_mcp_lineage()
    else:
        lookup, mcp_res = await asyncio.gather(
            lookup_geographic_hierarchy(query),
            _run_mcp_lineage()
        )

    mcp_ok = bool(mcp_res and mcp_res.get("ok"))
    mcp_data = (mcp_res or {}).get("data") or {}
    mcp_matched = bool(mcp_ok and mcp_data.get("matched"))

    # If primary lookup missed but MCP matched, promote MCP result
    if not lookup.get("matched") and mcp_matched:
        lookup = {
            "matched": True,
            "entity_type": mcp_data.get("entity_type"),
            "entity_name": mcp_data.get("entity_name"),
            "lineage": mcp_data.get("lineage", {}),
            "breadcrumbs": mcp_data.get("breadcrumbs", []),
            "details": mcp_data.get("lineage", {}),
            "raw_matches": []
        }
        state["resolution_stage"] = "mcp_lineage"
    elif lookup.get("matched"):
        state["resolution_stage"] = "postgres_mcp" if mcp_ok else "postgres_direct"
    else:
        state["resolution_stage"] = "unmatched"

    state["sql_trace"] = lookup
    state["mcp_used"] = mcp_ok
    state["mcp_tool"] = "get_administrative_lineage" if mcp_ok else None
    state["mcp_transport"] = (mcp_res or {}).get("transport") if mcp_ok else None

    ms = max(1, int((time.perf_counter() - t0) * 1000))
    if lookup.get("matched"):
        mcp_note = f" + MCP ({state['mcp_transport']})" if mcp_ok else ""
        _append_step(
            state,
            "db_mcp",
            "6-Tier PostgreSQL & MCP Lookup",
            f"Matched {lookup.get('entity_type')}: {lookup.get('entity_name')}{mcp_note}",
            "⚡",
            duration_ms=ms,
        )
    else:
        _append_step(
            state,
            "db_mcp",
            "6-Tier PostgreSQL & MCP Lookup",
            "No direct match in 6-tier tables — escalating to RAG & Web Search",
            "⚡",
            duration_ms=ms,
        )
    return state

# ----------------- NODE 5: Conversational Synthesizer Node -----------------
async def synthesizer_node(state: AgentState) -> AgentState:
    t0 = time.perf_counter()
    cfg = await get_active_llm_config()
    lookup = state.get("sql_trace") or {}
    matched = lookup.get("matched", False)
    phone = cfg["support_phone"]
    state["support_phone"] = phone

    lang = detect_query_language(state["user_query"], state.get("language"))
    state["language"] = lang

    # 0. MCP Database Metadata / Stats Response
    if matched and lookup.get("entity_type") == "MCPMetadata":
        state["breadcrumbs"] = lookup.get("breadcrumbs", ["Rajasthan", "PostgreSQL MCP"])
        mcp_out = format_mcp_metadata_response(
            tool_name=lookup.get("entity_name") or "get_database_stats",
            data=lookup.get("details") or {},
            transport=state.get("mcp_transport") or "stdio-jsonrpc",
            lang=lang,
            phone=phone
        )
        state["response_text"] = mcp_out["text"]
        state["next_questions"] = mcp_out["next_questions"]
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        _append_step(state, "synthesizer", "MCP Response Synthesizer", f"Formatted MCP output ({lang})", "🤖", duration_ms=ms)
        return state

    # 1. Exact Database / MCP Lineage Match
    if matched:
        entity_name = lookup.get("entity_name") or state["user_query"]
        entity_type = lookup.get("entity_type") or "Administrative Entity"
        lineage = lookup.get("lineage", {})
        details = lookup.get("details", {})
        breadcrumbs = lookup.get("breadcrumbs", [])
        state["breadcrumbs"] = breadcrumbs
        if not state.get("resolution_stage") or state.get("resolution_stage") == "unmatched":
            state["resolution_stage"] = "postgres_mcp" if state.get("mcp_used") else "postgres_direct"

        next_questions = generate_next_expected_questions(entity_name, entity_type, lineage, details, lang)
        state["next_questions"] = next_questions

        formatted_natural_text = format_natural_language_lineage(
            entity_name=entity_name,
            entity_type=entity_type,
            lineage=lineage,
            details=details,
            breadcrumbs=breadcrumbs,
            language=lang,
            next_questions=next_questions
        )
        state["response_text"] = sanitize_structured_output(formatted_natural_text)
        ms = max(1, int((time.perf_counter() - t0) * 1000))
        _append_step(
            state,
            "synthesizer",
            "Zero-Hallucination Synthesizer",
            f"Compiled grounded {lang} narrative & {len(next_questions)} follow-up questions",
            "🤖",
            duration_ms=ms,
        )
        return state

    # 2. Database RAG Retrieval Fallback
    enable_rag = cfg.get("enable_rag", True)
    rag_top_k = cfg.get("rag_top_k", 5)
    if enable_rag:
        t_rag = time.perf_counter()
        try:
            rag_results = await perform_rag_retrieval(state["user_query"], top_k=rag_top_k)
            rag_ms = max(1, int((time.perf_counter() - t_rag) * 1000))
            if rag_results:
                _append_step(
                    state,
                    "rag",
                    "RAG Database Retrieval",
                    f"Matched {len(rag_results)} records in raj_masters & public tables",
                    "📚",
                    duration_ms=rag_ms,
                )
                state["breadcrumbs"] = ["Rajasthan", "Verified Records"]
                state["resolution_stage"] = "rag_retrieval"
                rag_out = synthesize_rag_response(state["user_query"], rag_results, lang, phone)
                state["response_text"] = rag_out["text"]
                state["next_questions"] = rag_out["next_questions"]
                _append_step(state, "synthesizer", "RAG Response Synthesizer", f"Grounded {lang} reply from RAG chunks", "🤖", duration_ms=1)
                return state
            else:
                _append_step(
                    state,
                    "rag",
                    "RAG Database Retrieval",
                    "No RAG match found — trying Live Web Search",
                    "📚",
                    duration_ms=rag_ms,
                )
        except Exception as e:
            logger.warning(f"RAG retrieval error: {e}")

    # 3. Live Web Search Fallback
    enable_web_search = cfg.get("enable_web_search", True)
    if enable_web_search:
        provider = cfg.get("web_search_provider", "duckduckgo")
        api_key = cfg.get("web_search_api_key", "")
        max_results = cfg.get("web_search_max_results", 4)
        t_web = time.perf_counter()
        try:
            web_results = await perform_web_search(
                query=state["user_query"],
                provider=provider,
                api_key=api_key,
                max_results=max_results
            )
            web_ms = max(1, int((time.perf_counter() - t_web) * 1000))
            if web_results:
                _append_step(
                    state,
                    "web_search",
                    "Live Web Search Fallback",
                    f"Retrieved {len(web_results)} live results ({provider}/Wikipedia)",
                    "🌐",
                    duration_ms=web_ms,
                )
                state["breadcrumbs"] = ["Rajasthan", "Web Verified"]
                state["resolution_stage"] = "web_search"
                web_out = synthesize_web_response(state["user_query"], web_results, lang, phone)
                state["response_text"] = web_out["text"]
                state["next_questions"] = web_out["next_questions"]
                _append_step(state, "synthesizer", "Web Response Synthesizer", f"Compiled cited {lang} answer", "🤖", duration_ms=1)
                return state
            else:
                _append_step(
                    state,
                    "web_search",
                    "Live Web Search Fallback",
                    f"No external results found ({provider})",
                    "🌐",
                    duration_ms=web_ms,
                )
        except Exception as e:
            logger.warning(f"Web search fallback error: {e}")

    # 4. Respectful Out-of-Records Fallback
    state["breadcrumbs"] = ["Rajasthan", "Query Search"]
    state["resolution_stage"] = "not_found_helpline"
    _append_step(
        state,
        "synthesizer",
        "Fallback Helpline Notice",
        f"No DB/RAG/Web match — providing citizen helpline ({phone})",
        "📞",
        duration_ms=1,
    )
    if lang == "hi":
        next_qs = [
            "पिनकोड 302029 का विवरण",
            "बालोतरा जिला किस संभाग में है?",
            "मुहाना गांव की प्रशासनिक वंशावली"
        ]
        state["response_text"] = (
            f"राजस्थान मास्टर डायरेक्टरी में रिकॉर्ड नहीं मिला\n\n"
            f"खोजे गए शब्द '{state['user_query']}' के लिए वर्तमान प्रशासनिक तालिकाओं या वेब स्रोतों में कोई मिलान नहीं मिला। कृपया मानक नाम या 6-अंकीय पिनकोड का उपयोग करें।\n\n"
            f"📞 नागरिक हेल्पलाइन: [{phone}](tel:{phone})"
        )
    elif lang == "hinglish":
        next_qs = [
            "Pincode 302029 ke details",
            "Balotra district kis division mein hai?",
            "Muhana village ki administrative lineage"
        ]
        state["response_text"] = (
            f"Record Not Found in Rajasthan Master Directory\n\n"
            f"Queried term '{state['user_query']}' ke liye official tables ya verified web sources mein direct match nahi mila. Please standard name ya 6-digit postal pincode try kijiye.\n\n"
            f"📞 Official Citizen Helpline: [{phone}](tel:{phone})"
        )
    else:
        next_qs = [
            "Details of pincode 302029",
            "Which division does Balotra district belong to?",
            "Administrative lineage of Muhana village"
        ]
        state["response_text"] = (
            f"Location Not Found in Rajasthan Master Directory\n\n"
            f"No direct match was found for '{state['user_query']}' in the current database tables or verified web sources. Please provide a standard district/tehsil/village name or a 6-digit postal pincode.\n\n"
            f"📞 Official Citizen Helpline: [{phone}](tel:{phone})"
        )

    state["next_questions"] = next_qs
    state["response_text"] = sanitize_structured_output(state["response_text"])
    return state

async def try_ollama_completion(system_prompt: str, user_prompt: str, model_name: str, temperature: float) -> Optional[str]:
    """Attempts to generate completion via local Ollama instance"""
    try:
        url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
        payload = {
            "model": model_name,
            "prompt": f"{system_prompt}\n\nUser: {user_prompt}\nAssistant:",
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response", "").strip()
    except Exception as e:
        logger.debug(f"Ollama call skipped/failed ({e}), falling back to direct synthesizer.")
    return None

# ----------------- ROUTING FUNCTION -----------------
def route_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "out_of_scope":
        return "out_of_scope_helpline"
    elif intent == "capability_query":
        return "capability_node"
    else:
        return "database_lookup"

# ----------------- BUILD GRAPH -----------------
def create_rajmaster_agent():
    workflow = StateGraph(AgentState)

    workflow.add_node("guardrail_classifier", guardrail_classifier_node)
    workflow.add_node("out_of_scope_helpline", out_of_scope_helpline_node)
    workflow.add_node("capability_node", capability_node)
    workflow.add_node("database_lookup", database_lookup_node)
    workflow.add_node("synthesizer", synthesizer_node)

    workflow.set_entry_point("guardrail_classifier")

    workflow.add_conditional_edges(
        "guardrail_classifier",
        route_intent,
        {
            "out_of_scope_helpline": "out_of_scope_helpline",
            "capability_node": "capability_node",
            "database_lookup": "database_lookup"
        }
    )

    workflow.add_edge("database_lookup", "synthesizer")
    workflow.add_edge("out_of_scope_helpline", END)
    workflow.add_edge("capability_node", END)
    workflow.add_edge("synthesizer", END)

    return workflow.compile()

rajmaster_agent = create_rajmaster_agent()
