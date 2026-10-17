from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.security import get_current_user
from app.services.calendar_service import CalendarService
from app.config import get_wib_now

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])

class SaveDailyNoteRequest(BaseModel):
    date: str # YYYY-MM-DD
    note: str
    mood: Optional[str] = "neutral"

@router.get("/month")
def get_month_calendar(
    year: Optional[int] = None,
    month: Optional[int] = None,
    user: dict = Depends(get_current_user)
):
    now = get_wib_now()
    cur_year = year or now.year
    cur_month = month or now.month

    try:
        data = CalendarService.get_month_calendar_data(user["id"], cur_year, cur_month)
        return {"success": True, "data": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/day")
def get_day_details(
    date: str = Query(..., description="Format YYYY-MM-DD"),
    user: dict = Depends(get_current_user)
):
    try:
        data = CalendarService.get_day_details(user["id"], date)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/note")
def save_daily_note(
    req: SaveDailyNoteRequest,
    user: dict = Depends(get_current_user)
):
    try:
        saved = CalendarService.save_daily_note(user["id"], req.date, req.note, req.mood or "neutral")
        return {"success": True, "message": "Catatan harian berhasil disimpan.", "data": saved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/note")
def delete_daily_note(
    date: str = Query(..., description="Format YYYY-MM-DD"),
    user: dict = Depends(get_current_user)
):
    try:
        deleted = CalendarService.delete_daily_note(user["id"], date)
        if not deleted:
            raise HTTPException(status_code=404, detail="Tidak ada catatan harian pada tanggal ini.")
        return {"success": True, "message": "Catatan harian berhasil dihapus."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
