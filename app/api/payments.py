from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.security import get_current_user
from app.services.payment_service import PaymentService
from app.database import get_db

router = APIRouter(prefix="/api/payments", tags=["Payments"])

class CreateOrderRequest(BaseModel):
    plan: str # 'starter', 'pro'
    payment_type: str = "midtrans" # 'midtrans' or 'manual_transfer'

class ManualConfirmRequest(BaseModel):
    order_id: str
    proof_url: Optional[str] = "https://tatadana.id/uploads/proof_demo.jpg"

@router.post("/create-order")
def create_order(req: CreateOrderRequest, user: dict = Depends(get_current_user)):
    try:
        res = PaymentService.create_subscription_order(user["id"], req.plan, req.payment_type)
        return {"success": True, "data": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/my-subscription")
def get_my_subscription(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM subscriptions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
    """, (user["id"],))
    sub = cursor.fetchone()
    conn.close()
    return {
        "success": True,
        "plan": user["plan"],
        "subscription": dict(sub) if sub else None
    }

@router.post("/manual-confirm")
def confirm_manual_payment(req: ManualConfirmRequest, user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM subscriptions WHERE order_id = ? AND user_id = ?", (req.order_id, user["id"]))
    sub = cursor.fetchone()
    if not sub:
        conn.close()
        raise HTTPException(status_code=404, detail="Order ID tidak ditemukan.")

    cursor.execute("""
    UPDATE subscriptions
    SET payment_proof_url = ?, status = 'pending'
    WHERE order_id = ?
    """, (req.proof_url, req.order_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Konfirmasi transfer manual berhasil dikirim. Menunggu verifikasi admin."}
