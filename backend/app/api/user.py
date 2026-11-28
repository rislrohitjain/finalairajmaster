import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends, status, Header
from pydantic import BaseModel, Field
from sqlalchemy import select, or_, func
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.db.models import PortalUser
from app.auth import create_access_token, get_password_hash, verify_password, ALGORITHM
from jose import jwt

logger = logging.getLogger("api.user")
router = APIRouter(prefix="/api/user", tags=["User Portal"])

# In-memory fallback store synced with DB registrations (used if DB is temporarily unreachable)
_IN_MEMORY_USERS: Dict[str, Dict[str, Any]] = {
    "guest_user": {
        "id": 1,
        "username": "guest_user",
        "name": "Guest Explorer",
        "phone": "9876543210",
        "email": "explorer@ai-showcase.dev",
        "password_hash": get_password_hash("123456"),
        "preferred_language": "hi",
        "role": "user",
        "created_at": "2026-11-20T10:00:00Z",
    },
    "8946919241": {
        "id": 2,
        "username": "8946919241",
        "name": "Rohit Jain",
        "phone": "8946919241",
        "email": "rohit@ai-showcase.dev",
        "password_hash": get_password_hash("123456"),
        "preferred_language": "en",
        "role": "user",
        "created_at": "2026-11-20T10:00:00Z",
    },
}


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, example="Rohit Jain")
    username: str = Field(..., min_length=3, example="rohit987")
    phone: Optional[str] = Field(None, example="8946919241")
    email: Optional[str] = Field(None, example="rohit@example.com")
    password: str = Field(..., min_length=4, example="123456")
    preferred_language: Optional[str] = Field(default="en")


class UserLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, example="rohit987")
    password: str = Field(..., min_length=1, example="123456")


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
    preferred_language: str = "en"
    role: str = "user"
    created_at: str


class UserAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


def _decode_active_bearer(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """Returns decoded JWT payload if a valid Bearer user token is present, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("sub"):
            return payload
    except Exception:
        return None
    return None


def _ensure_no_active_session(authorization: Optional[str]) -> None:
    """Prevents logging in or registering another user while a user session is already active."""
    active = _decode_active_bearer(authorization)
    if active:
        active_user = active.get("sub")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{active_user}' is already logged in. Please sign out first before logging in another user."
        )


def _to_user_dict(u: PortalUser) -> Dict[str, Any]:
    return {
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "phone": u.phone or "",
        "email": u.email or "",
        "password_hash": u.password_hash,
        "preferred_language": u.preferred_language or "en",
        "role": u.role or "user",
        "created_at": u.created_at.isoformat() if u.created_at else datetime.now(timezone.utc).isoformat(),
    }


def _public_user(user_data: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in user_data.items() if k != "password_hash"}


async def get_current_user_from_header(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    payload = _decode_active_bearer(authorization)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in."
        )

    username = payload.get("sub")
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(PortalUser).where(PortalUser.username == username))
            db_user = res.scalar_one_or_none()
            if db_user:
                return _public_user(_to_user_dict(db_user))
    except Exception as e:
        logger.warning(f"DB lookup error in get_current_user_from_header: {e}")

    if username in _IN_MEMORY_USERS:
        return _public_user(_IN_MEMORY_USERS[username])

    return {
        "id": 99,
        "username": username,
        "name": payload.get("name") or username,
        "phone": payload.get("phone") or "",
        "email": payload.get("email") or "",
        "preferred_language": payload.get("lang") or "en",
        "role": payload.get("role") or "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/register", response_model=UserAuthResponse)
async def register_user(
    req: UserRegisterRequest,
    authorization: Optional[str] = Header(None)
):
    _ensure_no_active_session(authorization)

    u_clean = req.username.strip().lower()
    name_clean = req.name.strip()
    pwd_clean = req.password.strip()
    if len(pwd_clean) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 4 characters long."
        )

    pwd_hash = get_password_hash(pwd_clean)
    phone_clean = (req.phone or "").strip()
    email_clean = (req.email or "").strip().lower()
    lang_clean = (req.preferred_language or "en").strip()

    user_data: Optional[Dict[str, Any]] = None
    try:
        async with AsyncSessionLocal() as session:
            existing = (
                await session.execute(select(PortalUser).where(func.lower(PortalUser.username) == u_clean))
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already exists. Please sign in with your password."
                )

            db_user = PortalUser(
                username=u_clean,
                name=name_clean,
                phone=phone_clean,
                email=email_clean,
                password_hash=pwd_hash,
                preferred_language=lang_clean,
                role="user",
            )
            session.add(db_user)
            await session.commit()
            await session.refresh(db_user)
            user_data = _to_user_dict(db_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Database unavailable during register ({e}), checking in-memory store.")
        if u_clean in _IN_MEMORY_USERS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists. Please sign in with your password."
            )

    if user_data is None:
        user_data = {
            "id": int(time.time() * 1000) % 1000000,
            "username": u_clean,
            "name": name_clean,
            "phone": phone_clean,
            "email": email_clean,
            "password_hash": pwd_hash,
            "preferred_language": lang_clean,
            "role": "user",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    _IN_MEMORY_USERS[u_clean] = user_data

    token = create_access_token(
        data={
            "sub": u_clean,
            "name": user_data["name"],
            "phone": user_data["phone"],
            "email": user_data["email"],
            "lang": user_data["preferred_language"],
            "role": "user",
        },
        expires_delta=timedelta(days=30),
    )

    return UserAuthResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(**_public_user(user_data)),
    )


@router.post("/login", response_model=UserAuthResponse)
async def login_user(
    req: UserLoginRequest,
    authorization: Optional[str] = Header(None)
):
    _ensure_no_active_session(authorization)

    u_clean = req.username.strip().lower()
    pwd_clean = (req.password or "").strip()
    if not u_clean or not pwd_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required."
        )

    user_data: Optional[Dict[str, Any]] = None

    # 1. Check PostgreSQL portal_users first
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(PortalUser).where(
                or_(
                    func.lower(PortalUser.username) == u_clean,
                    PortalUser.phone == u_clean,
                    func.lower(PortalUser.email) == u_clean,
                )
            )
            db_user = (await session.execute(stmt)).scalar_one_or_none()
            if db_user:
                user_data = _to_user_dict(db_user)
    except Exception as e:
        logger.warning(f"Database lookup error during user login: {e}")

    # 2. Fallback to in-memory store (e.g. demo user or offline DB mode)
    if user_data is None and u_clean in _IN_MEMORY_USERS:
        user_data = _IN_MEMORY_USERS[u_clean]

    # 3. Strict validation: Reject unknown users or wrong passwords
    if not user_data or not verify_password(pwd_clean, user_data.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password. Wrong password login is not allowed."
        )

    _IN_MEMORY_USERS[user_data["username"]] = user_data

    token = create_access_token(
        data={
            "sub": user_data["username"],
            "name": user_data["name"],
            "phone": user_data["phone"],
            "email": user_data["email"],
            "lang": user_data["preferred_language"],
            "role": user_data.get("role", "user"),
        },
        expires_delta=timedelta(days=30),
    )

    return UserAuthResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(**_public_user(user_data)),
    )


@router.post("/logout")
async def logout_user():
    return {"status": "logged_out"}


@router.get("/profile", response_model=UserResponse)
async def get_user_profile(user: Dict[str, Any] = Depends(get_current_user_from_header)):
    return UserResponse(**user)


@router.put("/profile", response_model=UserResponse)
async def update_user_profile(
    req: UserProfileUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_user_from_header),
):
    username = user["username"]
    target = dict(_IN_MEMORY_USERS.get(username, user))

    if req.name is not None and req.name.strip():
        target["name"] = req.name.strip()
    if req.phone is not None:
        target["phone"] = req.phone.strip()
    if req.email is not None:
        target["email"] = req.email.strip()
    if req.preferred_language is not None:
        target["preferred_language"] = req.preferred_language.strip()

    try:
        async with AsyncSessionLocal() as session:
            db_user = (
                await session.execute(select(PortalUser).where(PortalUser.username == username))
            ).scalar_one_or_none()
            if db_user:
                db_user.name = target["name"]
                db_user.phone = target["phone"]
                db_user.email = target["email"]
                db_user.preferred_language = target["preferred_language"]
                await session.commit()
    except Exception as e:
        logger.warning(f"Database update notice in update_user_profile: {e}")

    _IN_MEMORY_USERS[username] = target
    return UserResponse(**_public_user(target))
