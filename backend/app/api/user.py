import logging
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends, status, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import Admin
from app.auth import create_access_token, ALGORITHM
from jose import jwt, JWTError

logger = logging.getLogger("api.user")
router = APIRouter(prefix="/api/user", tags=["User Portal"])

# In-memory session store fallback for serverless/offline DB
_IN_MEMORY_USERS: Dict[str, Dict[str, Any]] = {
    "demo_user": {
        "id": 1,
        "username": "guest_user",
        "name": "Guest Explorer",
        "phone": "9876543210",
        "email": "explorer@ai-showcase.dev",
        "preferred_language": "hi",
        "role": "user",
        "created_at": "2026-11-20T10:00:00Z"
    }
}

class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, example="Rohit Jain")
    username: str = Field(..., min_length=3, example="rohit987")
    phone: Optional[str] = Field(None, example="8946919241")
    email: Optional[str] = Field(None, example="rohit@example.com")
    password: Optional[str] = Field(default="123456")
    preferred_language: Optional[str] = Field(default="hi")

class UserLoginRequest(BaseModel):
    username: str = Field(..., example="rohit987")
    password: Optional[str] = Field(default="123456")

class UserProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    preferred_language: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    preferred_language: str = "hi"
    role: str = "user"
    created_at: str

class UserAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

def get_current_user_from_header(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        # Return default guest session
        return _IN_MEMORY_USERS.get("demo_user")

    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username in _IN_MEMORY_USERS:
            return _IN_MEMORY_USERS[username]
        return {
            "id": 99,
            "username": username or "guest_user",
            "name": payload.get("name") or username or "User",
            "phone": payload.get("phone") or "",
            "email": payload.get("email") or "",
            "preferred_language": payload.get("lang") or "hi",
            "role": "user",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception:
        return _IN_MEMORY_USERS.get("demo_user")

@router.post("/register", response_model=UserAuthResponse)
async def register_user(req: UserRegisterRequest):
    u_clean = req.username.strip().lower()
    name_clean = req.name.strip()

    user_data = {
        "id": int(time.time() * 1000) % 1000000,
        "username": u_clean,
        "name": name_clean,
        "phone": (req.phone or "").strip(),
        "email": (req.email or "").strip(),
        "preferred_language": req.preferred_language or "hi",
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    _IN_MEMORY_USERS[u_clean] = user_data

    token = create_access_token(data={
        "sub": u_clean,
        "name": name_clean,
        "phone": user_data["phone"],
        "email": user_data["email"],
        "lang": user_data["preferred_language"],
        "role": "user"
    }, expires_delta=timedelta(days=30))

    return UserAuthResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(**user_data)
    )

@router.post("/login", response_model=UserAuthResponse)
async def login_user(req: UserLoginRequest):
    u_clean = req.username.strip().lower()

    if u_clean in _IN_MEMORY_USERS:
        user_data = _IN_MEMORY_USERS[u_clean]
    else:
        # Create user session dynamically
        user_data = {
            "id": int(time.time() * 1000) % 1000000,
            "username": u_clean,
            "name": u_clean.capitalize(),
            "phone": u_clean if u_clean.isdigit() else "",
            "email": f"{u_clean}@showcase.user",
            "preferred_language": "hi",
            "role": "user",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        _IN_MEMORY_USERS[u_clean] = user_data

    token = create_access_token(data={
        "sub": u_clean,
        "name": user_data["name"],
        "phone": user_data["phone"],
        "email": user_data["email"],
        "lang": user_data["preferred_language"],
        "role": "user"
    }, expires_delta=timedelta(days=30))

    return UserAuthResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(**user_data)
    )

@router.get("/profile", response_model=UserResponse)
async def get_user_profile(user: Dict[str, Any] = Depends(get_current_user_from_header)):
    return UserResponse(**user)

@router.put("/profile", response_model=UserResponse)
async def update_user_profile(
    req: UserProfileUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user_from_header)
):
    username = user["username"]
    target = _IN_MEMORY_USERS.get(username, user)

    if req.name is not None and req.name.strip():
        target["name"] = req.name.strip()
    if req.phone is not None:
        target["phone"] = req.phone.strip()
    if req.email is not None:
        target["email"] = req.email.strip()
    if req.preferred_language is not None:
        target["preferred_language"] = req.preferred_language.strip()

    _IN_MEMORY_USERS[username] = target
    return UserResponse(**target)
