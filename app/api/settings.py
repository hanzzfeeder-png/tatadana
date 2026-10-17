from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.security import get_current_user
from app.services.reminder_service import ReminderService
from app.database import get_db
from app.config import get_wib_str

router = APIRouter(prefix="/api/settings", tags=["Settings"])

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    default_currency: Optional[str] = "IDR"

class UpdateReminderRequest(BaseModel):
    is_active: bool
    frequency: int
    time_1: str
    time_2: Optional[str] = "20:00"

@router.get("/profile")
def get_profile(user: dict = Depends(get_current_user)):
    return {"success": True, "data": user}

@router.put("/profile")
def update_profile(req: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    now = get_wib_str()
    cursor.execute("""
    UPDATE profiles
    SET full_name = COALESCE(?, full_name),
        avatar_url = COALESCE(?, avatar_url),
        default_currency = COALESCE(?, default_currency),
        updated_at = ?
    WHERE id = ?
    """, (req.full_name, req.avatar_url, req.default_currency, now, user["id"]))
    conn.commit()

    cursor.execute("SELECT id, email, full_name, phone_number, phone_verified, plan, role, avatar_url, default_currency FROM profiles WHERE id = ?", (user["id"],))
    updated = cursor.fetchone()
    conn.close()
    return {"success": True, "data": dict(updated)}

@router.get("/reminder")
def get_reminder(user: dict = Depends(get_current_user)):
    return {"success": True, "data": ReminderService.get_reminder_settings(user["id"])}

@router.put("/reminder")
def update_reminder(req: UpdateReminderRequest, user: dict = Depends(get_current_user)):
    try:
        res = ReminderService.update_reminder_settings(
            user["id"], req.is_active, req.frequency, req.time_1, req.time_2
        )
        return {"success": True, "data": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
