import time
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from app.agent.graph import rajmaster_agent
from app.agent.tools import lookup_geographic_hierarchy
from app.db.session import AsyncSessionLocal
from app.db.models import ChatLog, LLMSetting
from app.config import settings
from app.api.example_questions import EXAMPLE_QUESTIONS
from app.llm_client import IS_HUGGINGFACE, get_embedding, generate_chat_reply

router = APIRouter(prefix="/api", tags=["Chat & Geo"])

class IngestRequest(BaseModel):
    content: Optional[str] = Field(default=None, description="Document content chunk to ingest")
    text: Optional[str] = Field(default=None, description="Alternative field for document content")
    doc: Optional[str] = Field(default=None, description="Alternative field for document content")
    session_id: Optional[str] = Field(default=None, description="Optional association with session")

class ChatRequest(BaseModel):
    session_id: str = Field(default="guest-session")
    query: str = Field(..., description="User question or place name")
    language: Optional[str] = Field(default="en", description="Preferred response language: en, hi, or hinglish")

class ChatResponse(BaseModel):
    session_id: str
    response: str
    intent: str
    language: str = "en"
    next_questions: List[str] = []
    breadcrumbs: List[str] = []
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    lineage: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None
    helpline_card: bool = False
    support_phone: str
    latency_ms: int

@router.get("/capabilities")
async def get_capabilities():
    """Returns official information on the 6 Rajasthan administrative levels and sample questions"""
    phone = settings.SUPPORT_PHONE
    greeting = "Welcome here chat with Jain's only"
    async with AsyncSessionLocal() as session:
        cfg = (await session.execute(select(LLMSetting).where(LLMSetting.id == 1))).scalar_one_or_none()
        if cfg:
            phone = cfg.support_phone or phone
            greeting = cfg.greeting_message or greeting

    return {
        "title": "Rajasthan Administrative & Geographic Master Support System",
        "greeting": greeting,
        "support_phone": phone,
        "administrative_levels": [
            {
                "level": 1,
                "name": "State Level",
                "authority": "State Secretariat, Chief Secretary",
                "scope": "Rajasthan State, 10 Divisions, 50 Districts"
            },
            {
                "level": 2,
                "name": "Divisional Level",
                "authority": "Divisional Commissioner",
                "scope": "10 Divisions: Jaipur, Jodhpur, Ajmer, Udaipur, Bikaner, Kota, Bharatpur, Sikar, Pali, Banswara"
            },
            {
                "level": 3,
                "name": "District Level",
                "authority": "District Collectorate & Zila Parishad",
                "scope": "50 Districts & Zila Pramukhs"
            },
            {
                "level": 4,
                "name": "Sub-Division Level",
                "authority": "Sub-Divisional Magistrate (SDM/SDO)",
                "scope": "Administrative Revenue Sub-Divisions"
            },
            {
                "level": 5,
                "name": "Tehsil & Block Level",
                "authority": "Tehsildar (Revenue) & BDO (Development)",
                "scope": "Tehsils, Sub-Tehsils & Panchayat Samitis (Blocks)"
            },
            {
                "level": 6,
                "name": "Gram Panchayat, Village & Urban Body Level",
                "authority": "Sarpanch / Patwari / Mayor / Councillor",
                "scope": "Gram Panchayats, Revenue Villages, Patwar Circles, Nagar Nigam, Nagar Parishad, Nagar Palika & Wards"
            }
        ],
        "sample_prompts": [
            "Tell me about Muhana village administrative hierarchy",
            "What is the division and district of Balotra?",
            "Details of pincode 302029",
            "Who heads Sanganer tehsil and panchayat samiti?",
            "List all 10 divisions of Rajasthan",
            "What urban local body covers Malviya Nagar, Jaipur?"
        ]
    }

@router.get("/example-questions")
async def get_example_questions(category: Optional[str] = None):
    """Returns 100+ categorized example questions across all 6 administrative tiers"""
    if category and category.lower() != "all":
        filtered = [q for q in EXAMPLE_QUESTIONS if q["category"].lower() == category.lower()]
        return {"total": len(filtered), "questions": filtered}
    return {
        "total": len(EXAMPLE_QUESTIONS),
        "categories": ["All"] + list(dict.fromkeys(q["category"] for q in EXAMPLE_QUESTIONS)),
        "questions": EXAMPLE_QUESTIONS
    }

@router.get("/geo/search")
async def geo_search(q: str = Query(..., min_length=2)):
    """Direct instant lookup across all 6 Rajasthan geographic levels"""
    result = await lookup_geographic_hierarchy(q)
    return result

@router.post("/ingest")
async def ingest_document(req: IngestRequest):
    """
    Ingests a knowledge chunk or document into the rag_support table with a 384-dim vector embedding.
    Works seamlessly with Hugging Face (BAAI/bge-small-en-v1.5) and local Ollama.
    """
    content = (req.content or req.text or req.doc or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Missing document content to ingest")

    embedding = get_embedding(content)
    vec_str = f"[{','.join(str(round(x, 6)) for x in embedding)}]"

    async with AsyncSessionLocal() as session:
        try:
            async with session.begin_nested():
                stmt = text("""
                    INSERT INTO rag_support (record_type, session_id, role, content, embedding)
                    VALUES ('doc', :sid, NULL, :content, CAST(:vec AS vector))
                    RETURNING id;
                """)
                res = await session.execute(stmt, {
                    "sid": req.session_id,
                    "content": content,
                    "vec": vec_str
                })
                new_id = res.scalar()
        except Exception:
            try:
                async with session.begin_nested():
                    stmt = text("""
                        INSERT INTO rag_support (record_type, session_id, role, content, embedding)
                        VALUES ('doc', :sid, NULL, :content, CAST(:json_vec AS jsonb))
                        RETURNING id;
                    """)
                    res = await session.execute(stmt, {
                        "sid": req.session_id,
                        "content": content,
                        "json_vec": json.dumps(embedding)
                    })
                    new_id = res.scalar()
            except Exception:
                stmt = text("""
                    INSERT INTO rag_support (record_type, session_id, role, content)
                    VALUES ('doc', :sid, NULL, :content)
                    RETURNING id;
                """)
                res = await session.execute(stmt, {
                    "sid": req.session_id,
                    "content": content
                })
                new_id = res.scalar()
        await session.commit()

    return {
        "status": "success",
        "id": new_id,
        "record_type": "doc",
        "content_length": len(content),
        "embedding_dim": len(embedding)
    }

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """
    Processes user query through:
    1. pgvector (<=>) cosine search across rag_support knowledge chunks ('doc')
    2. Retrieval of the last 6 conversation messages ('chat') for session_id
    3. LangGraph Rajasthan 6-Tier administrative & governance synthesis / LLM wrapper
    4. Saving both user query and assistant reply to rag_support and chat_logs
    """
    start_time = time.perf_counter()

    query_emb = get_embedding(req.query)
    vec_str = f"[{','.join(str(round(x, 6)) for x in query_emb)}]"
    doc_context = ""

    # 1. Vector Search across rag_support doc chunks
    try:
        async with AsyncSessionLocal() as session:
            v_stmt = text("""
                SELECT content, (embedding <=> CAST(:vec AS vector)) AS distance
                FROM rag_support
                WHERE record_type = 'doc' AND embedding IS NOT NULL
                ORDER BY distance ASC
                LIMIT 3;
            """)
            v_res = await session.execute(v_stmt, {"vec": vec_str})
            matched_chunks = [row[0] for row in v_res.fetchall()]
            if matched_chunks:
                doc_context = "\n---\n".join(matched_chunks)
    except Exception:
        # Fallback to ILIKE if pgvector is not installed on local host
        try:
            async with AsyncSessionLocal() as session:
                t_stmt = text("""
                    SELECT content
                    FROM rag_support
                    WHERE record_type = 'doc' AND content ILIKE :term
                    LIMIT 3;
                """)
                t_res = await session.execute(t_stmt, {"term": f"%{req.query[:40]}%"})
                matched_chunks = [row[0] for row in t_res.fetchall()]
                if matched_chunks:
                    doc_context = "\n---\n".join(matched_chunks)
        except Exception:
            pass

    # 2. Retrieve last 6 chat history messages for session_id
    history_messages: List[Dict[str, str]] = []
    try:
        async with AsyncSessionLocal() as session:
            h_stmt = text("""
                SELECT role, content
                FROM rag_support
                WHERE record_type = 'chat' AND session_id = :sid
                ORDER BY id DESC
                LIMIT 6;
            """)
            h_res = await session.execute(h_stmt, {"sid": req.session_id})
            rows = h_res.fetchall()
            for r in reversed(rows):
                if r[0] and r[1]:
                    history_messages.append({"role": r[0], "content": r[1]})
    except Exception:
        pass

    # 3. Store user query into rag_support
    try:
        async with AsyncSessionLocal() as session:
            try:
                async with session.begin_nested():
                    u_stmt = text("""
                        INSERT INTO rag_support (record_type, session_id, role, content, embedding)
                        VALUES ('chat', :sid, 'user', :content, CAST(:vec AS vector));
                    """)
                    await session.execute(u_stmt, {
                        "sid": req.session_id,
                        "content": req.query,
                        "vec": vec_str
                    })
            except Exception:
                try:
                    async with session.begin_nested():
                        u_stmt = text("""
                            INSERT INTO rag_support (record_type, session_id, role, content, embedding)
                            VALUES ('chat', :sid, 'user', :content, CAST(:json_vec AS jsonb));
                        """)
                        await session.execute(u_stmt, {
                            "sid": req.session_id,
                            "content": req.query,
                            "json_vec": json.dumps(query_emb)
                        })
                except Exception:
                    u_stmt = text("""
                        INSERT INTO rag_support (record_type, session_id, role, content)
                        VALUES ('chat', :sid, 'user', :content);
                    """)
                    await session.execute(u_stmt, {
                        "sid": req.session_id,
                        "content": req.query
                    })
            await session.commit()
    except Exception:
        pass

    # 4. Invoke LangGraph agent pipeline
    initial_state = {
        "session_id": req.session_id,
        "user_query": req.query,
        "language": req.language or "en",
        "intent": None,
        "sql_trace": None,
        "breadcrumbs": None,
        "helpline_card": False,
        "support_phone": settings.SUPPORT_PHONE,
        "response_text": "",
        "streaming_tokens": [],
        "next_questions": []
    }

    agent_result = await rajmaster_agent.ainvoke(initial_state)
    response_text = agent_result.get("response_text", "").strip()

    # If in Hugging Face mode and agent had no response, use generate_chat_reply
    if not response_text and IS_HUGGINGFACE:
        llm_messages = [{"role": "system", "content": "You are the official Rajasthan Geographic Master Assistant."}]
        if doc_context:
            llm_messages.append({"role": "system", "content": f"Relevant Knowledge:\n{doc_context}"})
        llm_messages.extend(history_messages)
        llm_messages.append({"role": "user", "content": req.query})
        response_text = generate_chat_reply(llm_messages, max_tokens=350)

    latency_ms = int((time.perf_counter() - start_time) * 1000)

    # 5. Store assistant response into rag_support
    try:
        async with AsyncSessionLocal() as session:
            a_stmt = text("""
                INSERT INTO rag_support (record_type, session_id, role, content)
                VALUES ('chat', :sid, 'assistant', :content);
            """)
            await session.execute(a_stmt, {
                "sid": req.session_id,
                "content": response_text
            })
            await session.commit()
    except Exception:
        pass

    # 6. Save to chat_logs
    try:
        async with AsyncSessionLocal() as session:
            log_entry = ChatLog(
                session_id=req.session_id,
                user_query=req.query,
                detected_intent=agent_result.get("intent") or "geographic_query",
                sql_lookup_trace=agent_result.get("sql_trace") or {},
                ai_response=response_text,
                latency_ms=latency_ms
            )
            session.add(log_entry)
            await session.commit()
    except Exception:
        pass

    sql_trace = agent_result.get("sql_trace") or {}

    return ChatResponse(
        session_id=req.session_id,
        response=response_text,
        intent=agent_result.get("intent", "geographic_query"),
        language=agent_result.get("language", req.language or "en"),
        next_questions=agent_result.get("next_questions") or [],
        breadcrumbs=agent_result.get("breadcrumbs") or [],
        entity_name=sql_trace.get("entity_name"),
        entity_type=sql_trace.get("entity_type"),
        lineage=sql_trace.get("lineage"),
        details=sql_trace.get("details"),
        helpline_card=agent_result.get("helpline_card", False),
        support_phone=agent_result.get("support_phone") or settings.SUPPORT_PHONE,
        latency_ms=latency_ms
    )

@router.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    """SSE streaming response for real-time token rendering in chat UI"""
    start_time = time.perf_counter()

    initial_state = {
        "session_id": req.session_id,
        "user_query": req.query,
        "language": req.language or "en",
        "intent": None,
        "sql_trace": None,
        "breadcrumbs": None,
        "helpline_card": False,
        "support_phone": settings.SUPPORT_PHONE,
        "response_text": "",
        "streaming_tokens": [],
        "next_questions": []
    }

    agent_result = await rajmaster_agent.ainvoke(initial_state)
    latency_ms = int((time.perf_counter() - start_time) * 1000)

    # Log to database asynchronously
    try:
        async with AsyncSessionLocal() as session:
            log_entry = ChatLog(
                session_id=req.session_id,
                user_query=req.query,
                detected_intent=agent_result.get("intent") or "unknown",
                sql_lookup_trace=agent_result.get("sql_trace") or {},
                ai_response=agent_result.get("response_text") or "",
                latency_ms=latency_ms
            )
            session.add(log_entry)
            await session.commit()
    except Exception:
        pass

    full_text = agent_result.get("response_text", "")

    async def event_generator():
        # Stream word-by-word with realistic live support typing cadence
        words = full_text.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            payload = json.dumps({"token": chunk, "done": False})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0.015)

        sql_trace = agent_result.get("sql_trace") or {}

        # Final message with metadata
        final_meta = json.dumps({
            "token": "",
            "done": True,
            "session_id": req.session_id,
            "intent": agent_result.get("intent", "geographic_query"),
            "language": agent_result.get("language", req.language or "en"),
            "next_questions": agent_result.get("next_questions") or [],
            "breadcrumbs": agent_result.get("breadcrumbs") or [],
            "entity_name": sql_trace.get("entity_name"),
            "entity_type": sql_trace.get("entity_type"),
            "lineage": sql_trace.get("lineage"),
            "details": sql_trace.get("details"),
            "helpline_card": agent_result.get("helpline_card", False),
            "support_phone": agent_result.get("support_phone") or settings.SUPPORT_PHONE,
            "latency_ms": latency_ms
        })
        yield f"data: {final_meta}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
