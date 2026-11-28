from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Float, Boolean, func, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.db.session import Base

# 1. State Level
class State(Base):
    __tablename__ = "states"

    id = Column(Integer, primary_key=True, index=True)
    name_en = Column(String(100), nullable=False, default="Rajasthan")
    name_hi = Column(String(100), nullable=False, default="राजस्थान")
    code = Column(String(20), default="RJ")
    lgd_code = Column(Integer, nullable=True, default=8)
    chief_secretary = Column(String(150), default="Chief Secretary, Government of Rajasthan")
    governance_details = Column(Text, default="Government Secretariat, Jaipur, Rajasthan")
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    divisions = relationship("Division", back_populates="state", cascade="all, delete-orphan")

# 2. Division Level
class Division(Base):
    __tablename__ = "divisions"

    id = Column(Integer, primary_key=True, index=True)
    state_id = Column(Integer, ForeignKey("states.id"), nullable=False, default=1)
    rajmaster_id = Column(Integer, unique=True, index=True, nullable=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True)
    divisional_commissioner = Column(String(150), nullable=True)
    lgd_code = Column(Integer, nullable=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    state = relationship("State", back_populates="divisions")
    districts = relationship("District", back_populates="division")
    pincodes = relationship("Pincode", back_populates="division")

# 3. District Level
class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True, index=True)
    division_id = Column(Integer, ForeignKey("divisions.id"), nullable=True)
    rajmaster_id = Column(Integer, unique=True, index=True, nullable=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True, index=True)
    collectorate_details = Column(String(255), nullable=True)
    zila_parishad_details = Column(String(255), nullable=True)
    zila_pramukh = Column(String(150), nullable=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    division = relationship("Division", back_populates="districts")
    sub_divisions = relationship("SubDivision", back_populates="district")
    tehsils_blocks = relationship("TehsilBlock", back_populates="district")
    urban_local_bodies = relationship("UrbanLocalBody", back_populates="district")
    pincodes = relationship("Pincode", back_populates="district")

# 4. Sub-Division Level
class SubDivision(Base):
    __tablename__ = "sub_divisions"

    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False)
    rajmaster_id = Column(Integer, unique=True, index=True, nullable=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True, index=True)
    sdm_jurisdiction = Column(String(255), nullable=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    district = relationship("District", back_populates="sub_divisions")
    tehsils_blocks = relationship("TehsilBlock", back_populates="sub_division")

# 5. Tehsil & Block Level
class TehsilBlock(Base):
    __tablename__ = "tehsils_blocks"

    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=True)
    sub_division_id = Column(Integer, ForeignKey("sub_divisions.id"), nullable=True)
    rajmaster_id = Column(Integer, nullable=True, index=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True, index=True)
    entity_type = Column(String(50), nullable=False, default="Tehsil", index=True) # 'Tehsil', 'Sub-Tehsil', 'Panchayat Samiti / Block'
    tehsildar_details = Column(String(255), nullable=True)
    bdo_details = Column(String(255), nullable=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    district = relationship("District", back_populates="tehsils_blocks")
    sub_division = relationship("SubDivision", back_populates="tehsils_blocks")
    gram_panchayats = relationship("GramPanchayat", back_populates="tehsil_block")
    villages = relationship("Village", back_populates="tehsil_block")
    pincodes = relationship("Pincode", back_populates="tehsil_block")

# 6. Gram Panchayat & Village Level
class GramPanchayat(Base):
    __tablename__ = "gram_panchayats"

    id = Column(Integer, primary_key=True, index=True)
    tehsil_block_id = Column(Integer, ForeignKey("tehsils_blocks.id"), nullable=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=True)
    rajmaster_id = Column(Integer, unique=True, index=True, nullable=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True, index=True)
    sarpanch = Column(String(150), nullable=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    tehsil_block = relationship("TehsilBlock", back_populates="gram_panchayats")
    panchayat_wards = relationship("PanchayatWard", back_populates="gram_panchayat")
    villages = relationship("Village", back_populates="gram_panchayat")
    pincodes = relationship("Pincode", back_populates="gram_panchayat")

class PanchayatWard(Base):
    __tablename__ = "panchayat_wards"

    id = Column(Integer, primary_key=True, index=True)
    gram_panchayat_id = Column(Integer, ForeignKey("gram_panchayats.id"), nullable=False)
    ward_number = Column(String(50), nullable=False)
    ward_panch = Column(String(150), nullable=True)
    lgd_code = Column(Integer, nullable=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    gram_panchayat = relationship("GramPanchayat", back_populates="panchayat_wards")

class Village(Base):
    __tablename__ = "villages"

    id = Column(Integer, primary_key=True, index=True)
    gram_panchayat_id = Column(Integer, ForeignKey("gram_panchayats.id"), nullable=True)
    tehsil_block_id = Column(Integer, ForeignKey("tehsils_blocks.id"), nullable=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=True)
    rajmaster_id = Column(Integer, unique=True, index=True, nullable=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True, index=True)
    patwar_circle = Column(String(150), nullable=True, index=True)
    patwari = Column(String(150), nullable=True)
    pincode = Column(String(20), nullable=True, index=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    gram_panchayat = relationship("GramPanchayat", back_populates="villages")
    tehsil_block = relationship("TehsilBlock", back_populates="villages")

# 7. Urban Local Body & Ward Level
class UrbanLocalBody(Base):
    __tablename__ = "urban_local_bodies"

    id = Column(Integer, primary_key=True, index=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=False)
    rajmaster_id = Column(Integer, unique=True, index=True, nullable=True)
    code = Column(String(50), nullable=True)
    name_en = Column(String(150), nullable=False, index=True)
    name_hi = Column(String(150), nullable=True, index=True)
    ulb_type = Column(String(50), nullable=False, index=True) # 'Nagar Nigam', 'Nagar Parishad', 'Nagar Palika'
    city_name = Column(String(150), nullable=True, index=True)
    pincode = Column(String(20), nullable=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    district = relationship("District", back_populates="urban_local_bodies")
    urban_wards = relationship("UrbanWard", back_populates="ulb")
    pincodes = relationship("Pincode", back_populates="ulb")

class UrbanWard(Base):
    __tablename__ = "urban_wards"

    id = Column(Integer, primary_key=True, index=True)
    ulb_id = Column(Integer, ForeignKey("urban_local_bodies.id"), nullable=False)
    rajmaster_id = Column(Integer, nullable=True, index=True)
    ward_number = Column(String(50), nullable=False, index=True)
    name_en = Column(String(150), nullable=True)
    name_hi = Column(String(150), nullable=True)
    councillor_parshad = Column(String(150), nullable=True)
    pincode = Column(String(20), nullable=True)
    lgd_code = Column(Integer, nullable=True, index=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    ulb = relationship("UrbanLocalBody", back_populates="urban_wards")

# 8. Pincode Directory
class Pincode(Base):
    __tablename__ = "pincodes"

    id = Column(Integer, primary_key=True, index=True)
    pincode = Column(String(20), nullable=False, unique=True, index=True)
    city_or_village = Column(String(150), nullable=False, index=True)
    gram_panchayat_id = Column(Integer, ForeignKey("gram_panchayats.id"), nullable=True)
    ulb_id = Column(Integer, ForeignKey("urban_local_bodies.id"), nullable=True)
    tehsil_block_id = Column(Integer, ForeignKey("tehsils_blocks.id"), nullable=True)
    district_id = Column(Integer, ForeignKey("districts.id"), nullable=True)
    division_id = Column(Integer, ForeignKey("divisions.id"), nullable=True)
    metadata_json = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    gram_panchayat = relationship("GramPanchayat", back_populates="pincodes")
    ulb = relationship("UrbanLocalBody", back_populates="pincodes")
    tehsil_block = relationship("TehsilBlock", back_populates="pincodes")
    district = relationship("District", back_populates="pincodes")
    division = relationship("Division", back_populates="pincodes")

# 9. Admin, LLM & Scraper Tables
class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False) # e.g. 8946919241
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="admin")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class PortalUser(Base):
    __tablename__ = "portal_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(150), nullable=False)
    phone = Column(String(50), nullable=True, default="")
    email = Column(String(150), nullable=True, default="")
    password_hash = Column(String(255), nullable=False)
    preferred_language = Column(String(20), default="en")
    role = Column(String(50), default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class LLMSetting(Base):
    __tablename__ = "llm_settings"

    id = Column(Integer, primary_key=True, index=True)
    active_model = Column(String(100), default="llama3.2:3b")
    temperature = Column(Float, default=0.2)
    max_tokens = Column(Integer, default=1024)
    system_prompt = Column(Text, nullable=False)
    greeting_message = Column(Text, nullable=False)
    support_phone = Column(String(50), default="89988555525")
    enable_rag = Column(Boolean, default=True)
    rag_top_k = Column(Integer, default=5)
    enable_web_search = Column(Boolean, default=True)
    web_search_provider = Column(String(50), default="duckduckgo")
    web_search_api_key = Column(String(255), nullable=True, default="")
    web_search_max_results = Column(Integer, default=4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True)
    user_query = Column(Text, nullable=False)
    detected_intent = Column(String(50), nullable=False) # 'geographic_query', 'capability_query', 'out_of_scope'
    sql_lookup_trace = Column(JSONB, default=dict)
    ai_response = Column(Text, nullable=False)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id = Column(Integer, primary_key=True, index=True)
    master_name = Column(String(100), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="running") # 'running', 'completed', 'failed'
    rows_fetched = Column(Integer, default=0)
    rows_upserted = Column(Integer, default=0)
    error_logs = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

# ----------------- SINGLE-TABLE RAG SUPPORT MODEL -----------------
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except Exception:
    HAS_PGVECTOR = False

class RAGSupport(Base):
    __tablename__ = "rag_support"

    id = Column(Integer, primary_key=True, index=True)
    record_type = Column(String(10), nullable=False, index=True) # 'doc' or 'chat'
    session_id = Column(String(100), nullable=True, index=True)
    role = Column(String(20), nullable=True) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    embedding = Column(Vector(384) if HAS_PGVECTOR else JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
