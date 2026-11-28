import io
import os
import re
import time
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from app.agent.graph import rajmaster_agent
from app.agent.tools import lookup_geographic_hierarchy
from app.db.session import AsyncSessionLocal
from app.db.models import ChatLog, LLMSetting
from app.config import settings
from app.api.example_questions import EXAMPLE_QUESTIONS
from app.llm_client import IS_HUGGINGFACE, get_embedding, generate_chat_reply
from app.mcp.client import mcp_client
from app.export_utils import build_chat_excel, build_chat_pdf

logger = logging.getLogger("api.chat")
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
    mcp_used: bool = False
    mcp_tool: Optional[str] = None
    mcp_transport: Optional[str] = None
    resolution_stage: Optional[str] = None
    pipeline_steps: List[Dict[str, Any]] = []

@router.get("/mcp/status")
async def get_mcp_status():
    """Returns live PostgreSQL MCP server health, transport mode, tools, and 6-tier summary"""
    return await mcp_client.health_check()

@router.get("/docs/architecture-guide")
async def download_architecture_guide():
    """Downloads the complete Full-Stack, LLM, MCP & PostgreSQL Word guide (.docx) for NotebookLM"""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = [
        os.path.join(base_dir, "..", "RajMaster_AI_Complete_FullStack_LLM_Postgres_Guide.docx"),
        os.path.join(base_dir, "..", "frontend", "public", "RajMaster_AI_Complete_FullStack_LLM_Postgres_Guide.docx"),
        os.path.join(base_dir, "RajMaster_AI_Complete_FullStack_LLM_Postgres_Guide.docx"),
    ]
    for path in candidates:
        norm = os.path.abspath(path)
        if os.path.isfile(norm):
            return FileResponse(
                norm,
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename="RajMaster_AI_Complete_FullStack_LLM_Postgres_Guide.docx"
            )
    raise HTTPException(status_code=404, detail="Architecture guide Word document not found.")

@router.get("/llm/status")
async def get_llm_status():
    """Returns the active LLM engine status, provider, and cloud readiness"""
    from app.llm_client import get_active_llm_info
    mcp_health = await mcp_client.health_check()
    return {
        "status": "online",
        "llm_engine": get_active_llm_info(),
        "mcp_server": mcp_health,
        "supported_cloud_providers": [
            {"provider": "google_gemini", "env_key": "GEMINI_API_KEY", "model": "gemini-1.5-flash"},
            {"provider": "groq", "env_key": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile"},
            {"provider": "huggingface", "env_key": "HF_TOKEN", "model": "meta-llama/Llama-3.2-3B-Instruct"},
            {"provider": "openai", "env_key": "OPENAI_API_KEY", "model": "gpt-4o-mini"}
        ],
        "zero_hallucination_engine": "Rajasthan LangGraph Deterministic 6-Tier Master Synthesizer"
    }

@router.get("/capabilities")
async def get_capabilities():
    """Returns official information on the 6 Rajasthan administrative levels and sample questions"""
    phone = settings.SUPPORT_PHONE
    greeting = "Welcome here chat with Jain's only"
    try:
        async with AsyncSessionLocal() as session:
            cfg = (await session.execute(select(LLMSetting).where(LLMSetting.id == 1))).scalar_one_or_none()
            if cfg:
                phone = cfg.support_phone or phone
                greeting = cfg.greeting_message or greeting
    except Exception as e:
        pass

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
        "next_questions": [],
        "mcp_used": False,
        "mcp_tool": None,
        "mcp_transport": None,
        "resolution_stage": None,
        "pipeline_steps": []
    }

    try:
        agent_result = await rajmaster_agent.ainvoke(initial_state)
    except Exception as e:
        logger.warning(f"Agent execution error: {e}")
        agent_result = {
            "intent": "geographic_query",
            "response_text": f"Rajasthan Administrative Master Directory:\n\nRegarding your query about '{req.query}': The system is currently operating in resilience mode. For authoritative governance lineage and contacts across Rajasthan's 10 Divisions and 50 Districts, please call the official citizen helpline: {settings.SUPPORT_PHONE}.",
            "breadcrumbs": ["Rajasthan", "Governance Support"],
            "next_questions": ["List all 10 divisions of Rajasthan", "Which division does Balotra belong to?", "Details of pincode 302001"],
            "helpline_card": True,
            "support_phone": settings.SUPPORT_PHONE
        }
    response_text = agent_result.get("response_text", "").strip()

    # If in Hugging Face mode and agent had no response, use generate_chat_reply
    if not response_text and IS_HUGGINGFACE:
        llm_messages = [{"role": "system", "content": "You are RajMaster AI, an educational portfolio showcase demonstrating LangGraph, multi-cloud LLM failover, and geographic hierarchy graphs."}]
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
        latency_ms=latency_ms,
        mcp_used=bool(agent_result.get("mcp_used", False)),
        mcp_tool=agent_result.get("mcp_tool"),
        mcp_transport=agent_result.get("mcp_transport"),
        resolution_stage=agent_result.get("resolution_stage"),
        pipeline_steps=agent_result.get("pipeline_steps") or []
    )

@router.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest):
    """Real-time SSE streaming response emitting live pipeline thinking steps and natural typing tokens."""
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
        "next_questions": [],
        "mcp_used": False,
        "mcp_tool": None,
        "mcp_transport": None,
        "resolution_stage": None,
        "pipeline_steps": []
    }

    async def event_generator():
        final_state: Dict[str, Any] = dict(initial_state)
        emitted_step_ids = set()

        init_step = {
            "id": "input",
            "title": "Analyzing User Query & Language",
            "detail": f"Received query ({req.language or 'auto'}): \"{req.query[:60]}\"",
            "icon": "📱",
            "status": "done",
            "duration_ms": 1
        }
        emitted_step_ids.add("input")
        yield f"data: {json.dumps({'type': 'step', 'step': init_step, 'done': False})}\n\n"

        running_guardrail = {
            "id": "guardrail",
            "title": "Guardrail & Intent Classifier",
            "detail": "Checking intent, scope & Rajasthan entities...",
            "icon": "🛡️",
            "status": "running"
        }
        yield f"data: {json.dumps({'type': 'step', 'step': running_guardrail, 'done': False})}\n\n"

        try:
            async for chunk in rajmaster_agent.astream(initial_state, stream_mode="updates"):
                for node_name, node_update in chunk.items():
                    if not isinstance(node_update, dict):
                        continue
                    final_state.update(node_update)
                    for step in (node_update.get("pipeline_steps") or []):
                        sid = step.get("id")
                        if sid and sid not in emitted_step_ids:
                            emitted_step_ids.add(sid)
                            yield f"data: {json.dumps({'type': 'step', 'step': step, 'done': False})}\n\n"

                    if node_name == "guardrail_classifier":
                        if node_update.get("intent") == "geographic_query":
                            next_step = {
                                "id": "db_mcp",
                                "title": "6-Tier PostgreSQL & MCP Lookup",
                                "detail": "Querying 6-tier tables & postgres-mcp JSON-RPC...",
                                "icon": "⚡",
                                "status": "running"
                            }
                            yield f"data: {json.dumps({'type': 'step', 'step': next_step, 'done': False})}\n\n"
                    elif node_name == "database_lookup":
                        next_step = {
                            "id": "synthesizer",
                            "title": "Synthesizing Verified Answer",
                            "detail": "Grounding data or running RAG/Web fallback...",
                            "icon": "🤖",
                            "status": "running"
                        }
                        yield f"data: {json.dumps({'type': 'step', 'step': next_step, 'done': False})}\n\n"
        except Exception as e:
            logger.warning(f"Stream execution fallback ({e})")
            final_state = await rajmaster_agent.ainvoke(initial_state)

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        try:
            async with AsyncSessionLocal() as session:
                log_entry = ChatLog(
                    session_id=req.session_id,
                    user_query=req.query,
                    detected_intent=final_state.get("intent") or "unknown",
                    sql_lookup_trace=final_state.get("sql_trace") or {},
                    ai_response=final_state.get("response_text") or "",
                    latency_ms=latency_ms
                )
                session.add(log_entry)
                await session.commit()
        except Exception:
            pass

        typing_step = {
            "id": "typing",
            "title": "Typing Final Response",
            "detail": "Streaming verified structured answer...",
            "icon": "💬",
            "status": "running"
        }
        yield f"data: {json.dumps({'type': 'step', 'step': typing_step, 'done': False})}\n\n"

        full_text = final_state.get("response_text", "")
        parts = re.findall(r"\S+\s*|\n+", full_text)
        for part in parts:
            if len(part) > 5 and "\n" not in part:
                for idx in range(0, len(part), 4):
                    sub = part[idx:idx + 4]
                    yield f"data: {json.dumps({'type': 'token', 'token': sub, 'done': False})}\n\n"
                    await asyncio.sleep(0.014)
            else:
                yield f"data: {json.dumps({'type': 'token', 'token': part, 'done': False})}\n\n"
                await asyncio.sleep(0.018)

        typing_done_step = {
            "id": "typing",
            "title": "Response Delivered",
            "detail": f"Completed in {latency_ms} ms",
            "icon": "💬",
            "status": "done",
            "duration_ms": latency_ms
        }
        yield f"data: {json.dumps({'type': 'step', 'step': typing_done_step, 'done': False})}\n\n"

        all_steps = [init_step] + list(final_state.get("pipeline_steps") or []) + [typing_done_step]
        sql_trace = final_state.get("sql_trace") or {}

        final_meta = json.dumps({
            "type": "done",
            "token": "",
            "done": True,
            "session_id": req.session_id,
            "intent": final_state.get("intent", "geographic_query"),
            "language": final_state.get("language", req.language or "en"),
            "next_questions": final_state.get("next_questions") or [],
            "breadcrumbs": final_state.get("breadcrumbs") or [],
            "entity_name": sql_trace.get("entity_name"),
            "entity_type": sql_trace.get("entity_type"),
            "lineage": sql_trace.get("lineage"),
            "details": sql_trace.get("details"),
            "helpline_card": final_state.get("helpline_card", False),
            "support_phone": final_state.get("support_phone") or settings.SUPPORT_PHONE,
            "latency_ms": latency_ms,
            "mcp_used": bool(final_state.get("mcp_used", False)),
            "mcp_tool": final_state.get("mcp_tool"),
            "mcp_transport": final_state.get("mcp_transport"),
            "resolution_stage": final_state.get("resolution_stage"),
            "pipeline_steps": all_steps
        })
        yield f"data: {final_meta}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


class ChatExportRequest(BaseModel):
    session_id: str = Field(default="guest-session")
    language: str = Field(default="en")
    support_phone: Optional[str] = None
    messages: List[Dict[str, Any]] = []


async def _resolve_chat_export_messages(req: ChatExportRequest) -> List[Dict[str, Any]]:
    if req.messages:
        return req.messages
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(ChatLog).where(ChatLog.session_id == req.session_id).order_by(ChatLog.id.asc())
            logs = (await session.execute(stmt)).scalars().all()
            resolved: List[Dict[str, Any]] = []
            for l in logs:
                ts = l.created_at.strftime("%I:%M %p") if l.created_at else ""
                resolved.append({"sender": "user", "text": l.user_query, "timestamp": ts})
                resolved.append({"sender": "assistant", "text": l.ai_response, "timestamp": ts, "intent": l.detected_intent})
            return resolved
    except Exception:
        return []


@router.post("/chat/export/excel")
async def export_chat_excel(req: ChatExportRequest):
    """Exports the citizen chat session into a multi-sheet styled Excel (.xlsx) workbook with summary chart."""
    msgs = await _resolve_chat_export_messages(req)
    xlsx_bytes = build_chat_excel(
        session_id=req.session_id,
        messages=msgs,
        language=req.language or "en",
        support_phone=req.support_phone or settings.SUPPORT_PHONE,
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"rajmaster_chat_{req.session_id}_{ts}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/chat/export/pdf")
async def export_chat_pdf(req: ChatExportRequest):
    """Exports the citizen chat session into a branded Unicode PDF (supports English + Devanagari Hindi)."""
    msgs = await _resolve_chat_export_messages(req)
    pdf_bytes = build_chat_pdf(
        session_id=req.session_id,
        messages=msgs,
        language=req.language or "en",
        support_phone=req.support_phone or settings.SUPPORT_PHONE,
    )
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"rajmaster_chat_{req.session_id}_{ts}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
