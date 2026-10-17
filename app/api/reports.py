import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from app.security import get_current_user
from app.services.report_service import ReportService, STORAGE_DIR

router = APIRouter(prefix="/api/reports", tags=["Reports"])

class ExportRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category_id: Optional[str] = None
    wallet_id: Optional[str] = None
    type: Optional[str] = None

@router.get("/summary")
def get_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: dict = Depends(get_current_user)
):
    return {"success": True, "data": ReportService.get_report_summary(user["id"], start_date, end_date)}

@router.get("/table")
def get_table(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category_id: Optional[str] = None,
    wallet_id: Optional[str] = None,
    type: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "transaction_date",
    sort_order: str = "DESC",
    page: int = 1,
    page_size: int = 15,
    user: dict = Depends(get_current_user)
):
    data = ReportService.get_filtered_transactions(
        user_id=user["id"],
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        wallet_id=wallet_id,
        tx_type=type,
        search_query=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size
    )
    return {"success": True, "data": data}

@router.post("/export/excel")
def export_excel(req: ExportRequest, user: dict = Depends(get_current_user)):
    try:
        file_name = ReportService.generate_excel_report(
            user["id"],
            start_date=req.start_date,
            end_date=req.end_date,
            category_id=req.category_id,
            wallet_id=req.wallet_id,
            tx_type=req.type
        )
        return {
            "success": True,
            "file_name": file_name,
            "download_url": f"/api/reports/download/{file_name}"
        }
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/export/pdf")
def export_pdf(req: ExportRequest, user: dict = Depends(get_current_user)):
    try:
        file_name = ReportService.generate_pdf_report(
            user["id"],
            start_date=req.start_date,
            end_date=req.end_date,
            category_id=req.category_id,
            wallet_id=req.wallet_id,
            tx_type=req.type
        )
        return {
            "success": True,
            "file_name": file_name,
            "download_url": f"/api/reports/download/{file_name}"
        }
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/export/history")
def get_export_history(user: dict = Depends(get_current_user)):
    return {"success": True, "data": ReportService.get_export_history(user["id"])}

@router.get("/download/{file_name}")
def download_export_file(file_name: str):
    file_path = os.path.join(STORAGE_DIR, file_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File laporan tidak ditemukan atau telah kedaluwarsa.")
    
    media_type = "application/pdf" if file_name.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    headers = {
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Cache-Control": "no-cache, no-store, must-revalidate"
    }
    return FileResponse(file_path, media_type=media_type, filename=file_name, headers=headers)
