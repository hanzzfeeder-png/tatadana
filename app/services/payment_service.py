import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.database import get_db
from app.config import settings, get_wib_str

class PaymentService:
    @staticmethod
    def create_subscription_order(user_id: str, plan: str, payment_type: str = "midtrans") -> Dict[str, Any]:
        if plan not in ["starter", "pro"]:
            raise ValueError("Paket langganan tidak valid.")

        amount = 49000.0 if plan == "starter" else 99000.0
        order_id = f"TD-{plan.upper()}-{uuid.uuid4().hex[:8].upper()}"
        now = get_wib_str()

        conn = get_db()
        cursor = conn.cursor()
        sub_id = str(uuid.uuid4())

        cursor.execute("""
        INSERT INTO subscriptions (id, user_id, plan, status, payment_type, order_id, gross_amount, is_approved, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?, ?, 0, ?, ?)
        """, (sub_id, user_id, plan, payment_type, order_id, amount, now, now))
        conn.commit()
        conn.close()

        # Simulated Midtrans Snap Token or Manual Payment details
        snap_token = f"SNAP-TOKEN-DEMO-{order_id}"
        return {
            "subscription_id": sub_id,
            "order_id": order_id,
            "plan": plan,
            "amount": amount,
            "payment_type": payment_type,
            "snap_token": snap_token,
            "redirect_url": f"/dashboard/payment/mock-finish?order_id={order_id}"
        }

    @staticmethod
    def approve_payment(subscription_id: str, admin_id: str, notes: Optional[str] = None) -> bool:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, plan, status FROM subscriptions WHERE id = ?", (subscription_id,))
        sub = cursor.fetchone()
        if not sub:
            conn.close()
            raise ValueError("Data pembayaran tidak ditemukan.")

        now = get_wib_str()
        user_id = sub["user_id"]
        plan = sub["plan"]

        cursor.execute("""
        UPDATE subscriptions
        SET status = 'active', is_approved = 1, admin_notes = ?, updated_at = ?
        WHERE id = ?
        """, (notes or "Approved by admin", now, subscription_id))

        # Upgrade User Profile Plan
        cursor.execute("""
        UPDATE profiles
        SET plan = ?, updated_at = ?
        WHERE id = ?
        """, (plan, now, user_id))

        # Record admin audit log
        cursor.execute("""
        INSERT INTO admin_audit_logs (id, admin_id, action, target_user_id, details, created_at)
        VALUES (?, ?, 'approve_subscription', ?, ?, ?)
        """, (str(uuid.uuid4()), admin_id, user_id, f"Approved subscription {subscription_id} to {plan}", now))

        conn.commit()
        conn.close()
        return True

    @staticmethod
    def reject_payment(subscription_id: str, admin_id: str, reason: Optional[str] = None) -> bool:
        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()
        cursor.execute("""
        UPDATE subscriptions
        SET status = 'rejected', is_approved = 0, admin_notes = ?, updated_at = ?
        WHERE id = ?
        """, (reason or "Ditolak oleh admin", now, subscription_id))

        cursor.execute("""
        INSERT INTO admin_audit_logs (id, admin_id, action, target_user_id, details, created_at)
        VALUES (?, ?, 'reject_subscription', NULL, ?, ?)
        """, (str(uuid.uuid4()), admin_id, f"Rejected subscription {subscription_id}: {reason}", now))

        conn.commit()
        conn.close()
        return True

    @staticmethod
    def get_all_subscriptions() -> List[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT s.*, p.full_name, p.email, p.phone_number
        FROM subscriptions s
        JOIN profiles p ON p.id = s.user_id
        ORDER BY s.created_at DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
