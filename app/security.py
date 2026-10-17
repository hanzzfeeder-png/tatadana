import hashlib
import os
import hmac
import time
from typing import Optional, Dict, Any
import jwt
from fastapi import Request, HTTPException, status
from app.config import settings

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{pwd_hash}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt, pwd_hash = hashed_password.split(":")
        check = hashlib.sha256((salt + plain_password).encode()).hexdigest()
        return hmac.compare_digest(check, pwd_hash)
    except Exception:
        return False

def create_access_token(data: dict, expires_delta_hours: int = 72) -> str:
    to_encode = data.copy()
    expire = int(time.time()) + (expires_delta_hours * 3600)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except Exception:
        return None

def generate_otp() -> str:
    import random
    return f"{random.randint(100000, 999999)}"

def get_current_user_optional(request: Request) -> Optional[Dict[str, Any]]:
    # Check Authorization Header first, then Cookie fallback
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    if not token:
        token = request.cookies.get("tatadana_token")

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    from app.database import get_db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, full_name, phone_number, phone_verified, plan, role, avatar_url, default_currency FROM profiles WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return dict(row)

def get_current_user(request: Request) -> Dict[str, Any]:
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Silakan login terlebih dahulu untuk mengakses layanan ini"
        )
    return user

def require_admin(request: Request) -> Dict[str, Any]:
    user = get_current_user(request)
    is_admin_user = (user.get("role") in ("superadmin", "admin")) or bool(user.get("is_admin"))
    if not is_admin_user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses khusus Administrator TataDana"
        )
    return user
