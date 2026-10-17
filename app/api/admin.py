import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app.security import require_admin, create_access_token
from app.database import get_db
from app.config import settings, get_wib_str, get_wib_now
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/api/admin", tags=["Admin"])

class CreateAIProviderRequest(BaseModel):
    name: str
    provider_type: str # 'gemini', 'openai', 'deepseek'
    model_name: str
    api_key: str
    is_active: bool = True
    priority: int = 1
    mode: str = "single"

class UpdateAIProviderRequest(BaseModel):
    name: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None
    mode: Optional[str] = None

class ApproveRejectPaymentRequest(BaseModel):
    notes: Optional[str] = None

class PaymentActionRequest(BaseModel):
    action: str # 'approve' or 'reject'
    notes: Optional[str] = None

# =============================================================================
# 1. OVERVIEW & RINGKASAN METRIK SISTEM
# =============================================================================

@router.get("/overview")
def get_admin_overview(admin: dict = Depends(require_admin)):
    """
    Mengembalikan ringkasan ekosistem TataDana:
    - Total pengguna (Starter vs Pro)
    - Total transaksi sistem & volume perputaran uang
    - Estimasi biaya & panggilan AI bulan berjalan
    - Jumlah pembayaran upgrade yang pending verifikasi
    - Riwayat audit log terbaru
    """
    conn = get_db()
    cursor = conn.cursor()
    now_wib = get_wib_now()
    month_str = now_wib.strftime("%Y-%m")

    # 1. Total User & Rincian Paket
    cursor.execute("SELECT COUNT(*) FROM profiles")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM profiles WHERE plan = 'starter'")
    starter_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM profiles WHERE plan = 'pro'")
    pro_users = cursor.fetchone()[0]

    # 2. Total Transaksi Sistem & Volume
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0.0) FROM transactions")
    tx_row = cursor.fetchone()
    total_transactions = tx_row[0]
    total_transaction_amount = float(tx_row[1])

    # 3. Panggilan AI & Estimasi Biaya Bulan Berjalan
    cursor.execute("""
    SELECT 
        COUNT(*) as total_calls,
        COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
        COALESCE(SUM(completion_tokens), 0) as total_completion_tokens
    FROM ai_logs
    WHERE created_at LIKE ?
    """, (f"{month_str}%",))
    ai_row = cursor.fetchone()
    ai_calls_month = ai_row["total_calls"]
    p_tokens = ai_row["total_prompt_tokens"]
    c_tokens = ai_row["total_completion_tokens"]
    total_tokens = p_tokens + c_tokens
    # Estimasi biaya blended: ~$0.001 per 1k tokens (sekitar Rp 16 per 1k tokens)
    estimated_cost_idr = (total_tokens / 1000.0) * 16.0

    # 4. Pembayaran Menunggu Verifikasi
    cursor.execute("SELECT COUNT(*) FROM subscriptions WHERE status = 'pending'")
    pending_payments_count = cursor.fetchone()[0]

    # 5. Riwayat Audit Log Terbaru
    cursor.execute("""
    SELECT a.*, p.full_name as target_user_name, adm.full_name as admin_name
    FROM admin_audit_logs a
    LEFT JOIN profiles p ON p.id = a.target_user_id
    LEFT JOIN profiles adm ON adm.id = a.admin_id
    ORDER BY a.created_at DESC
    LIMIT 5
    """)
    recent_logs = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "success": True,
        "data": {
            "total_users": total_users,
            "starter_users": starter_users,
            "pro_users": pro_users,
            "total_transactions": total_transactions,
            "total_transaction_amount": total_transaction_amount,
            "ai_calls_month": ai_calls_month,
            "ai_tokens_month": total_tokens,
            "ai_estimated_cost_idr": round(estimated_cost_idr, 2),
            "pending_payments_count": pending_payments_count,
            "recent_audit_logs": recent_logs
        }
    }

# =============================================================================
# 2. PENGELOLAAN PENGGUNA & IMPERSONASI
# =============================================================================

@router.get("/users")
def list_users(q: Optional[str] = None, admin: dict = Depends(require_admin)):
    """
    Daftar seluruh pengguna dengan filter pencarian real-time (nama, email, no HP).
    """
    conn = get_db()
    cursor = conn.cursor()
    
    query = """
    SELECT p.id, p.email, p.full_name, p.phone_number, p.phone_verified, p.plan, p.role, p.created_at,
           (SELECT COUNT(*) FROM telegram_links WHERE user_id = p.id AND is_active = 1) > 0 as is_tg_connected,
           (SELECT telegram_username FROM telegram_links WHERE user_id = p.id AND is_active = 1 LIMIT 1) as telegram_username,
           (SELECT COUNT(*) FROM transactions WHERE user_id = p.id) as total_txs
    FROM profiles p
    """
    params = []
    if q and q.strip():
        search = f"%{q.strip()}%"
        query += " WHERE p.full_name LIKE ? OR p.email LIKE ? OR p.phone_number LIKE ? "
        params.extend([search, search, search])

    query += " ORDER BY p.created_at DESC LIMIT 100"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return {"success": True, "data": [dict(r) for r in rows]}

@router.get("/users/{user_id}/transactions")
@router.get("/user-transactions/{user_id}")
def view_user_transactions(user_id: str, request: Request, admin: dict = Depends(require_admin)):
    """
    Inspeksi transaksi pengguna untuk troubleshooting dukungan pelanggan.
    Akses otomatis dicatat ke tabel admin_audit_logs demi kepatuhan privasi.
    """
    conn = get_db()
    cursor = conn.cursor()

    now = get_wib_str()
    client_ip = request.client.host if request.client else "unknown"
    cursor.execute("""
    INSERT INTO admin_audit_logs (id, admin_id, action, target_user_id, details, ip_address, created_at)
    VALUES (?, ?, 'view_user_transactions', ?, 'Admin memeriksa transaksi user untuk troubleshooting', ?, ?)
    """, (str(uuid.uuid4()), admin["id"], user_id, client_ip, now))

    cursor.execute("""
    SELECT t.*, w.name as wallet_name, c.name as category_name
    FROM transactions t
    LEFT JOIN wallets w ON w.id = t.wallet_id
    LEFT JOIN categories c ON c.id = t.category_id
    WHERE t.user_id = ?
    ORDER BY t.transaction_date DESC
    LIMIT 100
    """, (user_id,))
    rows = cursor.fetchall()
    conn.commit()
    conn.close()

    return {"success": True, "data": [dict(r) for r in rows]}

@router.get("/users/{user_id}/detail")
def get_user_detail(user_id: str, admin: dict = Depends(require_admin)):
    """
    Rangkuman profil lengkap pengguna untuk Superadmin:
    - Informasi profil: nama, email, nomor HP, status verifikasi WA, avatar, tier, dll.
    - Status integrasi bot Telegram
    - Daftar dompet & rincian saldo masing-masing
    - Daftar kategori & alokasi budget bulanan
    - Ringkasan transaksi sistem (total pemasukan, pengeluaran, saldo bersih)
    - Riwayat transaksi terbaru (5)
    - Status paket / langganan aktif
    """
    conn = get_db()
    cursor = conn.cursor()

    # 1. Profile
    cursor.execute("""
    SELECT id, email, full_name, phone_number, phone_verified, plan, role, avatar_url, default_currency, created_at, updated_at
    FROM profiles
    WHERE id = ?
    """, (user_id,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    profile = dict(p)

    # 2. Telegram Link
    cursor.execute("""
    SELECT telegram_user_id, telegram_chat_id, telegram_username, is_active, created_at
    FROM telegram_links
    WHERE user_id = ?
    ORDER BY created_at DESC LIMIT 1
    """, (user_id,))
    tg = cursor.fetchone()
    telegram_info = dict(tg) if tg else {
        "is_active": 0,
        "telegram_username": None,
        "telegram_chat_id": None,
        "created_at": None
    }

    # 3. Wallets
    cursor.execute("""
    SELECT id, name, type, balance, is_default, icon, color
    FROM wallets
    WHERE user_id = ?
    ORDER BY is_default DESC, balance DESC
    """, (user_id,))
    wallets = [dict(w) for w in cursor.fetchall()]
    total_balance = sum(float(w["balance"]) for w in wallets)

    # 4. Categories & Budgets
    cursor.execute("""
    SELECT id, name, type, icon, color, monthly_budget
    FROM categories
    WHERE user_id = ?
    ORDER BY monthly_budget DESC, name ASC
    """, (user_id,))
    categories = [dict(c) for c in cursor.fetchall()]

    # 5. Financial Summary
    cursor.execute("""
    SELECT 
        COUNT(*) as total_count,
        COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0.0) as total_income,
        COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0.0) as total_expense
    FROM transactions
    WHERE user_id = ?
    """, (user_id,))
    s_row = cursor.fetchone()
    total_tx = s_row["total_count"]
    total_inc = float(s_row["total_income"])
    total_exp = float(s_row["total_expense"])
    net_flow = total_inc - total_exp

    # 6. Latest Subscription
    cursor.execute("""
    SELECT id, plan, status, payment_type, order_id, gross_amount, is_approved, created_at
    FROM subscriptions
    WHERE user_id = ?
    ORDER BY created_at DESC LIMIT 1
    """, (user_id,))
    sub_row = cursor.fetchone()
    subscription_info = dict(sub_row) if sub_row else None

    # 7. Recent Transactions (5)
    cursor.execute("""
    SELECT t.id, t.type, t.amount, t.transaction_date, t.note, w.name as wallet_name, c.name as category_name
    FROM transactions t
    LEFT JOIN wallets w ON w.id = t.wallet_id
    LEFT JOIN categories c ON c.id = t.category_id
    WHERE t.user_id = ?
    ORDER BY t.transaction_date DESC, t.created_at DESC
    LIMIT 5
    """, (user_id,))
    recent_transactions = [dict(t) for t in cursor.fetchall()]

    conn.close()

    payload = {
        "profile": profile,
        "telegram": telegram_info,
        "wallets": wallets,
        "total_balance": total_balance,
        "categories": categories,
        "financial_summary": {
            "total_transactions": total_tx,
            "total_count": total_tx,
            "total_income": total_inc,
            "total_expense": total_exp,
            "net_cashflow": net_flow
        },
        "subscription": subscription_info,
        "recent_transactions": recent_transactions
    }

    return {
        "success": True,
        "data": payload,
        **payload
    }

@router.post("/impersonate/{user_id}")
def impersonate_user(user_id: str, response: Response, admin: dict = Depends(require_admin)):
    """
    Impersonasi aman: admin masuk ke dashboard tampilan pengguna tanpa password.
    Aktivitas dicatat secara permanen di audit log.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM profiles WHERE id = ?", (user_id,))
    target = cursor.fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    now = get_wib_str()
    cursor.execute("""
    INSERT INTO admin_audit_logs (id, admin_id, action, target_user_id, details, created_at)
    VALUES (?, ?, 'impersonate_user', ?, 'Admin melakukan impersonation ke akun pengguna', ?)
    """, (str(uuid.uuid4()), admin["id"], user_id, now))
    conn.commit()
    conn.close()

    token = create_access_token({
        "sub": target["id"],
        "email": target["email"],
        "role": target["role"],
        "plan": target["plan"],
        "impersonated_by": admin["id"]
    })

    response.set_cookie(
        key="tatadana_token",
        value=token,
        httponly=True,
        max_age=72 * 3600,
        samesite="lax"
    )

    return {"success": True, "redirect_url": "/dashboard"}

# =============================================================================
# 3. KELOLA PROVIDER AI & ENKRIPSI KEY
# =============================================================================

@router.get("/ai-providers")
def list_ai_providers(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ai_providers ORDER BY priority ASC")
    rows = cursor.fetchall()
    conn.close()
    
    res = []
    for r in rows:
        d = dict(r)
        decrypted = settings.decrypt(d["api_key_encrypted"]) if d.get("api_key_encrypted") else ""
        d["api_key_masked"] = (decrypted[:6] + "••••••••") if decrypted else ""
        del d["api_key_encrypted"]
        res.append(d)
    return {"success": True, "data": res}

@router.post("/ai-providers")
def create_ai_provider(req: CreateAIProviderRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    now = get_wib_str()
    p_id = str(uuid.uuid4())
    enc_key = settings.encrypt(req.api_key)

    cursor.execute("""
    INSERT INTO ai_providers (id, name, provider_type, model_name, api_key_encrypted, is_active, priority, mode, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (p_id, req.name, req.provider_type, req.model_name, enc_key, 1 if req.is_active else 0, req.priority, req.mode, now, now))
    conn.commit()
    conn.close()
    return {"success": True, "message": "AI Provider berhasil ditambahkan."}

@router.put("/ai-providers/{provider_id}")
def update_ai_provider(provider_id: str, req: UpdateAIProviderRequest, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    now = get_wib_str()

    updates = []
    params = []
    if req.name is not None:
        updates.append("name = ?")
        params.append(req.name)
    if req.model_name is not None:
        updates.append("model_name = ?")
        params.append(req.model_name)
    if req.api_key is not None and req.api_key.strip():
        updates.append("api_key_encrypted = ?")
        params.append(settings.encrypt(req.api_key.strip()))
    if req.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if req.is_active else 0)
    if req.priority is not None:
        updates.append("priority = ?")
        params.append(req.priority)
    if req.mode is not None:
        updates.append("mode = ?")
        params.append(req.mode)

    if updates:
        updates.append("updated_at = ?")
        params.append(now)
        params.append(provider_id)
        cursor.execute(f"UPDATE ai_providers SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return {"success": True, "message": "Provider AI berhasil diperbarui."}

@router.delete("/ai-providers/{provider_id}")
def delete_ai_provider(provider_id: str, admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Provider AI berhasil dihapus."}

# =============================================================================
# 4. LOG & MONITORING AI
# =============================================================================

@router.get("/ai-logs")
def list_ai_logs(page: int = 1, limit: int = 20, provider: Optional[str] = None, status: Optional[str] = None, admin: dict = Depends(require_admin)):
    """
    Pagination riwayat panggilan model AI (Gemini, OpenAI, DeepSeek).
    """
    conn = get_db()
    cursor = conn.cursor()
    offset = max(0, (page - 1) * limit)

    where_clauses = []
    params = []
    if provider:
        where_clauses.append("l.provider = ?")
        params.append(provider)
    if status:
        where_clauses.append("l.status = ?")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    cursor.execute(f"SELECT COUNT(*) FROM ai_logs l {where_sql}", params)
    total_count = cursor.fetchone()[0]

    query = f"""
    SELECT l.id, l.user_id, l.provider, l.model, l.source as endpoint_type,
           (COALESCE(l.prompt_tokens, 0) + COALESCE(l.completion_tokens, 0)) as tokens_used,
           l.prompt_tokens, l.completion_tokens,
           l.latency_ms, l.status, l.error_message as error,
           l.created_at, p.full_name as user_name
    FROM ai_logs l
    LEFT JOIN profiles p ON p.id = l.user_id
    {where_sql}
    ORDER BY l.created_at DESC
    LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [limit, offset])
    rows = cursor.fetchall()
    conn.close()

    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "total_pages": max(1, (total_count + limit - 1) // limit)
        }
    }

# =============================================================================
# 5. VERIFIKASI PEMBAYARAN & UPGRADE PRO
# =============================================================================

@router.get("/payments")
def list_payments(admin: dict = Depends(require_admin)):
    return {"success": True, "data": PaymentService.get_all_subscriptions()}

@router.post("/payments/{subscription_id}/action")
def take_payment_action(subscription_id: str, req: PaymentActionRequest, admin: dict = Depends(require_admin)):
    """
    Aksi verifikasi pembayaran:
    - approve -> Otomatis mengubah status ke 'active' dan upgrade user ke 'pro'.
    - reject -> Mengubah status pesanan ke 'rejected'.
    """
    act = req.action.lower().strip()
    if act == "approve":
        PaymentService.approve_payment(subscription_id, admin["id"], req.notes)
        return {"success": True, "message": "Pembayaran berhasil di-approve! User di-upgrade ke Pro."}
    elif act == "reject":
        PaymentService.reject_payment(subscription_id, admin["id"], req.notes)
        return {"success": True, "message": "Pembayaran berhasil ditolak."}
    else:
        raise HTTPException(status_code=400, detail="Action tidak valid. Gunakan 'approve' atau 'reject'.")

@router.post("/payments/{subscription_id}/approve")
def approve_payment(subscription_id: str, req: ApproveRejectPaymentRequest, admin: dict = Depends(require_admin)):
    PaymentService.approve_payment(subscription_id, admin["id"], req.notes)
    return {"success": True, "message": "Pembayaran berhasil di-approve! User di-upgrade ke Pro."}

@router.post("/payments/{subscription_id}/reject")
def reject_payment(subscription_id: str, req: ApproveRejectPaymentRequest, admin: dict = Depends(require_admin)):
    PaymentService.reject_payment(subscription_id, admin["id"], req.notes)
    return {"success": True, "message": "Pembayaran ditolak."}

# =============================================================================
# 6. AUDIT LOG & EXPORT
# =============================================================================

@router.get("/audit-logs")
def list_audit_logs(page: int = 1, limit: int = 30, admin: dict = Depends(require_admin)):
    """
    Catatan aktivitas Superadmin demi akuntabilitas privasi pengguna.
    """
    conn = get_db()
    cursor = conn.cursor()
    offset = max(0, (page - 1) * limit)

    cursor.execute("SELECT COUNT(*) FROM admin_audit_logs")
    total_count = cursor.fetchone()[0]

    cursor.execute("""
    SELECT a.*, p.full_name as target_user_name, p.email as target_user_email,
           adm.full_name as admin_name
    FROM admin_audit_logs a
    LEFT JOIN profiles p ON p.id = a.target_user_id
    LEFT JOIN profiles adm ON adm.id = a.admin_id
    ORDER BY a.created_at DESC
    LIMIT ? OFFSET ?
    """, (limit, offset))
    rows = cursor.fetchall()
    conn.close()

    return {
        "success": True,
        "data": [dict(r) for r in rows],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_count,
            "total_pages": max(1, (total_count + limit - 1) // limit)
        }
    }

@router.get("/export-all-users")
def export_all_users(admin: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT p.id, p.email, p.full_name, p.phone_number, p.plan, p.role, p.created_at,
           COALESCE(SUM(t.amount), 0.0) as total_transaction_volume
    FROM profiles p
    LEFT JOIN transactions t ON t.user_id = p.id
    GROUP BY p.id
    ORDER BY p.created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return {"success": True, "data": [dict(r) for r in rows]}
