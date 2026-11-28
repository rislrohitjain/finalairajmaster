import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.db.init_db import init_models, seed_initial_data
from app.api.chat import router as chat_router, chat_endpoint, ingest_document
from app.api.admin import router as admin_router, admin_login, AdminLoginRequest
from app.api.user import router as user_router
from app.db.session import async_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist", "frontend", "browser"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Rajasthan Administrative & Geographic Master system...")
    try:
        await init_models()
        await seed_initial_data()
        logger.info("Database and seeds ready.")
    except Exception as e:
        logger.warning(f"Startup DB check notice: {e}")
    yield
    logger.info("Shutting down database connection engine...")
    try:
        await async_engine.dispose()
    except Exception as e:
        logger.warning(f"Engine dispose notice: {e}")

app = FastAPI(
    title="Rajasthan Administrative & Geographic Master (finalairajmaster)",
    description="Full-stack AI-powered geographic and administrative master portal for Rajasthan",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(user_router)

# Mount direct root endpoints for /ingest, /chat, and /admin/login
app.post("/chat")(chat_endpoint)
app.post("/ingest")(ingest_document)
app.post("/admin/login")(admin_login)

@app.middleware("http")
async def spa_and_assets_middleware(request: Request, call_next):
    path = request.url.path.lstrip("/")
    # Never intercept backend routes
    if path.startswith("api/") or path in ("docs", "openapi.json", "health", "redoc", "chat", "ingest", "admin/login"):
        return await call_next(request)

    # Check if this is an asset file in the built frontend
    if os.path.exists(frontend_dist):
        asset_file = os.path.join(frontend_dist, path)
        if path and os.path.isfile(asset_file):
            return FileResponse(asset_file)

        # Serve index.html for browser navigation (only when text/html is explicitly in Accept)
        accept = request.headers.get("accept", "")
        if "text/html" in accept and (path == "" or path.startswith("admin") or path.startswith("voice")):
            index_path = os.path.join(frontend_dist, "index.html")
            if os.path.isfile(index_path):
                return FileResponse(index_path)

    return await call_next(request)

@app.get("/")
async def root():
    return {
        "portal": "Rajasthan Administrative & Geographic Master (finalairajmaster)",
        "status": "online",
        "endpoints": {
            "chat": "/api/chat",
            "chat_stream": "/api/chat/stream",
            "capabilities": "/api/capabilities",
            "geo_search": "/api/geo/search",
            "admin_login": "/api/admin/login",
            "admin_llm_config": "/api/admin/llm-config",
            "admin_geo_stats": "/api/admin/geo-stats",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "database": settings.DB_NAME,
        "ollama_url": settings.OLLAMA_BASE_URL,
        "support_phone": settings.SUPPORT_PHONE
    }
