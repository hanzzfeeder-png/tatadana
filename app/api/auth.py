from fastapi import APIRouter, Response, Request, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from app.services.auth_service import AuthService
from app.security import get_current_user, get_current_user_optional

router = APIRouter(prefix="/api/auth", tags=["Auth"])

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone_number: str

class LoginRequest(BaseModel):
    identifier: str # email or phone
    password: str

class VerifyOtpRequest(BaseModel):
    user_id: str
    otp_code: str

class ResendOtpRequest(BaseModel):
    user_id: str

class OnboardingRequest(BaseModel):
    user_id: Optional[str] = None
    persona: Optional[str] = None
    financial_goal: Optional[str] = None
    wallet_name: Optional[str] = "Dompet Tunai"
    selected_categories: Optional[List[Dict[str, Any]]] = None

@router.post("/register")
def register(req: RegisterRequest, response: Response):
    try:
        res = AuthService.register_user(req.email, req.password, req.full_name, req.phone_number)
        response.set_cookie(
            key="tatadana_token",
            value=res["token"],
            httponly=True,
            max_age=72 * 3600,
            samesite="lax"
        )
        return {"success": True, "data": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/verify-otp")
def verify_otp(req: VerifyOtpRequest):
    try:
        AuthService.verify_phone_otp(req.user_id, req.otp_code)
        return {"success": True, "message": "Nomor HP berhasil diverifikasi!"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/resend-otp")
def resend_otp(req: ResendOtpRequest):
    try:
        otp = AuthService.resend_otp(req.user_id)
        return {"success": True, "message": "Kode OTP baru telah dikirimkan", "otp_preview": otp}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/login")
def login(req: LoginRequest, response: Response):
    try:
        res = AuthService.login_user(req.identifier, req.password)
        response.set_cookie(
            key="tatadana_token",
            value=res["token"],
            httponly=True,
            max_age=72 * 3600,
            samesite="lax"
        )
        return {"success": True, "data": res}
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="tatadana_token")
    return {"success": True, "message": "Berhasil logout."}

@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"success": True, "user": user}

@router.post("/onboarding")
def complete_onboarding(req: OnboardingRequest, request: Request):
    user = get_current_user_optional(request)
    user_id = req.user_id or (user.get("id") if user else None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sesi pengguna tidak valid. Silakan login terlebih dahulu.")
    try:
        res = AuthService.complete_onboarding(user_id, req.selected_categories, req.wallet_name)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
