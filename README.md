---
title: Finalairajmaster
emoji: 🏛️
colorFrom: orange
colorTo: amber
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 'Rajasthan Administrative & Geographic Master with pgvector RAG'
---

# finalairajmaster — Rajasthan Administrative & Geographic Master Portal

A production-ready full-stack web application featuring an ETL scraper pipeline directly extracting official Rajasthan administrative and geographic master data from `https://rajmasters.rajasthan.gov.in/` into PostgreSQL, a LangGraph + Ollama AI conversational support agent with strict geographic guardrails and emergency helpline routing, and a responsive Angular 18+ UI with Tailwind CSS.

---

## 🏛️ Administrative & Geographic Hierarchy Scope

The system models and navigates Rajasthan's complete **6-Tier Administrative Hierarchy** with official LGD codes and extensible JSONB attributes:

1. **State Level (`states`)**: Rajasthan State Secretariat & Chief Secretary governance.
2. **Divisional Level (`divisions`)**: 10 Divisions (Jaipur, Jodhpur, Ajmer, Udaipur, Bikaner, Kota, Bharatpur, Sikar, Pali, Banswara) & Divisional Commissioners.
3. **District Level (`districts`)**: 50 Districts, Collectorates, Zila Parishads & Zila Pramukhs.
4. **Sub-Division Level (`sub_divisions`)**: Sub-Divisional Magistrates (SDM/SDO).
5. **Tehsil & Block Level (`tehsils_blocks`)**: Tehsildars (Revenue) & BDOs (Panchayat Samitis/Blocks).
6. **Grassroot Panchayat & Urban Level**:
   - **Rural**: Gram Panchayats (`gram_panchayats`), Panchayat Wards (`panchayat_wards`), Revenue Villages & Patwar Circles (`villages`).
   - **Urban**: Urban Local Bodies (`urban_local_bodies` — Nagar Nigam, Nagar Parishad, Nagar Palika) & Urban Wards (`urban_wards`).
   - **Postal Directory**: Pincode to City/Village/Tehsil/District directory (`pincodes`).

---

## 🔑 Default Credentials & Helpline

- **Admin Login Mobile / Username**: `8946919241`
- **Admin Password**: `123456`
- **Citizen Support Helpline**: `89988555525` (`tel:89988555525`)
- **Portal URL**: `https://rajmasters.rajasthan.gov.in/`

---

## 🐳 Docker Deployment (Ports 3006 to 3010)

As requested, Docker containers are mapped in the **3006 to 3010 series**:

| Service | Container Port | Host Port | Description |
|---|---|---|---|
| **Frontend UI (Angular + Nginx)** | `80` | `3006` | Accessible at `http://localhost:3006` |
| **Backend API (FastAPI + LangGraph)** | `8000` | `3007` | Accessible at `http://localhost:3007` & Docs at `http://localhost:3007/docs` |

The containers connect to your host machine's local PostgreSQL and Ollama instances via `host.docker.internal`.

### Running with Docker Compose:
```bash
docker-compose up --build
```

---

## 🚀 Local Quickstart & Development

### 1. Database Setup (`PostgreSQL`)
Ensure PostgreSQL is running on `localhost:5432` with user `postgres` and password `Admin@123`:
```sql
CREATE DATABASE finalairajmaster;
```

### 2. Backend Setup (`uv` + FastAPI + LangGraph)
```bash
cd backend

# 1. Sync dependencies with uv
uv sync

# 2. Initialize database schema & default admin/settings seed
uv run python -m app.db.init_db

# 3. (Optional) Run the RajMaster real-data ETL scraper
uv run python -m app.scraper.rajmaster_scraper --all --limit 200

# 4. Start the FastAPI backend server
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Backend API Documentation: `http://localhost:8000/docs`

### 3. Frontend Setup (`Angular 18` + Tailwind CSS)
```bash
cd frontend

# 1. Install dependencies
npm install

# 2. Start Angular dev server
npm start
```
Frontend Web Application: `http://localhost:4200` (or `http://localhost:3006` when running Docker)

---

## 🤖 LangGraph Agentic Workflow & Guardrails

The conversational support agent (`backend/app/agent/graph.py`) executes through 5 dedicated graph nodes:

1. **Guardrail & Intent Classifier**: Permits ONLY queries related to Rajasthan's 6 administrative tiers, cities, villages, and pincodes. Out-of-scope queries (politics, weather, coding, etc.) are caught and routed to the helpline node.
2. **Out-of-Scope Helpline Node**: Delivers a polite redirection and displays the clickable `tel:89988555525` support card.
3. **Capability Greeter Node**: Welcomes citizens and presents sample exploration queries.
4. **PostgreSQL Lookup Tools Node**: Performs fuzzy and exact matching against PostgreSQL to reconstruct the entire lineage (e.g., `Village ➔ Patwar ➔ Gram Panchayat ➔ Block ➔ Tehsil ➔ SDM ➔ District ➔ Division ➔ State`).
5. **Conversational Synthesizer Node**: Synthesizes human-like natural language explanations streamed token-by-token via SSE (`POST /api/chat/stream`).

---

## 📡 Key API Endpoints

- `POST /api/chat` — Standard full response chat
- `POST /api/chat/stream` — Real-time Server-Sent Events (SSE) streaming chat
- `GET /api/capabilities` — Public administrative tiers summary & sample prompts
- `GET /api/geo/search?q=...` — Instant geographic hierarchy query
- `POST /api/admin/login` — Admin authentication (`8946919241` / `123456`)
- `GET /api/admin/llm-config` & `PUT /api/admin/llm-config` — Manage Ollama models, prompt, temperature, helpline
- `POST /api/admin/sync-rajmaster` — One-click trigger for live scraper ETL runs
- `GET /api/admin/scraper-runs` — Scraper execution logs and status
- `GET /api/admin/geo-stats` — Live entity counts across all 6 levels
- `POST /api/admin/geo-entry` — Manual entry insertion with JSONB metadata
- `GET /api/admin/chat-logs` — Searchable interaction and helpline redirection logs
