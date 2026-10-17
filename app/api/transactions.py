from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from app.security import get_current_user
from app.services.transaction_service import TransactionService
from app.services.wallet_service import WalletService
from app.services.budget_service import BudgetService
from app.database import get_db
from app.config import get_wib_now

router = APIRouter(prefix="/api/transactions", tags=["Transactions"])

class CreateTxRequest(BaseModel):
    wallet_id: str
    type: str # 'expense', 'income', 'transfer'
    amount: float
    category_id: Optional[str] = None
    target_wallet_id: Optional[str] = None
    note: Optional[str] = None
    transaction_date: Optional[str] = None
    receipt_items: Optional[List[Dict[str, Any]]] = None

@router.get("")
def list_transactions(limit: int = 20, user: dict = Depends(get_current_user)):
    return {"success": True, "data": TransactionService.get_recent_transactions(user["id"], limit)}

@router.post("")
def create_transaction(req: CreateTxRequest, user: dict = Depends(get_current_user)):
    try:
        tx = TransactionService.create_transaction(
            user_id=user["id"],
            wallet_id=req.wallet_id,
            tx_type=req.type,
            amount=req.amount,
            category_id=req.category_id,
            note=req.note,
            transaction_date=req.transaction_date,
            source="web",
            receipt_items=req.receipt_items,
            target_wallet_id=req.target_wallet_id
        )
        return {"success": True, "data": tx}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

class UpdateTxRequest(BaseModel):
    wallet_id: Optional[str] = None
    type: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[str] = None
    target_wallet_id: Optional[str] = None
    note: Optional[str] = None
    transaction_date: Optional[str] = None

@router.put("/{tx_id}")
def update_transaction(tx_id: str, req: UpdateTxRequest, user: dict = Depends(get_current_user)):
    try:
        updated = TransactionService.update_transaction(
            tx_id=tx_id,
            user_id=user["id"],
            wallet_id=req.wallet_id,
            tx_type=req.type,
            amount=req.amount,
            category_id=req.category_id,
            note=req.note,
            target_wallet_id=req.target_wallet_id,
            transaction_date=req.transaction_date
        )
        return {"success": True, "data": updated}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/stats")
def get_dashboard_stats(period: str = "monthly", user: dict = Depends(get_current_user)):
    """
    Returns 4 stats cards + Charts data (Pie, 6-Month Bar, Trend Line) + 10 recent transactions
    + Onboarding checklist for new users.
    """
    user_id = user["id"]
    now = get_wib_now()
    month_str = now.strftime("%Y-%m")

    conn = get_db()
    cursor = conn.cursor()

    # 1. Saldo Total (Sum of all user wallets)
    cursor.execute("SELECT COALESCE(SUM(balance), 0.0) FROM wallets WHERE user_id = ?", (user_id,))
    total_balance = float(cursor.fetchone()[0])

    # 2. Pemasukan & Pengeluaran Bulan Ini
    cursor.execute("""
    SELECT 
        COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0.0) as income,
        COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0.0) as expense
    FROM transactions
    WHERE user_id = ? AND transaction_date LIKE ?
    """, (user_id, f"{month_str}%"))
    row = cursor.fetchone()
    income_month = float(row["income"])
    expense_month = float(row["expense"])

    # 3. Budget Tersisa
    cursor.execute("SELECT COALESCE(SUM(monthly_budget), 0.0) FROM categories WHERE user_id = ? AND type = 'expense'", (user_id,))
    total_budget = float(cursor.fetchone()[0])
    budget_remaining = max(0.0, total_budget - expense_month)

    # 4. Pie Chart: Pengeluaran per Kategori Bulan Ini
    cursor.execute("""
    SELECT c.name, c.icon, c.color, COALESCE(SUM(t.amount), 0.0) as total
    FROM categories c
    JOIN transactions t ON t.category_id = c.id AND t.user_id = c.user_id AND t.type = 'expense'
    WHERE c.user_id = ? AND t.transaction_date LIKE ?
    GROUP BY c.id
    ORDER BY total DESC
    """, (user_id, f"{month_str}%"))
    pie_rows = cursor.fetchall()
    pie_data = {
        "labels": [f"{r['icon']} {r['name']}" for r in pie_rows],
        "values": [float(r["total"]) for r in pie_rows],
        "colors": [r["color"] or "#FF6B00" for r in pie_rows]
    }

    # 5. Bar Chart: 6 Bulan Terakhir (Pemasukan vs Pengeluaran)
    bar_labels = []
    bar_income = []
    bar_expense = []

    for i in range(5, -1, -1):
        target_month_date = now - timedelta(days=i * 30)
        m_label = target_month_date.strftime("%b %Y")
        m_filter = target_month_date.strftime("%Y-%m")
        bar_labels.append(m_label)

        cursor.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0.0) as inc,
            COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0.0) as exp
        FROM transactions
        WHERE user_id = ? AND transaction_date LIKE ?
        """, (user_id, f"{m_filter}%"))
        m_row = cursor.fetchone()
        bar_income.append(float(m_row["inc"]))
        bar_expense.append(float(m_row["exp"]))

    bar_data = {
        "labels": bar_labels,
        "income": bar_income,
        "expense": bar_expense
    }

    # 6. Trend Line: Pengeluaran Harian Bulan Ini (Daily Trend)
    # Generate days from 1st to today
    days_in_month = now.day
    line_labels = [f"Tgl {d}" for d in range(1, days_in_month + 1)]
    line_values = []

    for d in range(1, days_in_month + 1):
        day_str = f"{now.year}-{now.month:02d}-{d:02d}"
        cursor.execute("""
        SELECT COALESCE(SUM(amount), 0.0) FROM transactions
        WHERE user_id = ? AND type = 'expense' AND transaction_date LIKE ?
        """, (user_id, f"{day_str}%"))
        line_values.append(float(cursor.fetchone()[0]))

    trend_data = {
        "labels": line_labels,
        "values": line_values
    }

    # 7. Check Onboarding Checklist
    cursor.execute("SELECT COUNT(*) FROM telegram_links WHERE user_id = ? AND is_active = 1", (user_id,))
    is_tg_linked = cursor.fetchone()[0] > 0

    cursor.execute("SELECT COUNT(*) FROM wallets WHERE user_id = ?", (user_id,))
    wallet_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ? AND monthly_budget > 0", (user_id,))
    budget_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (user_id,))
    has_transactions = cursor.fetchone()[0] > 0

    conn.close()

    recent_txs = TransactionService.get_recent_transactions(user_id, 10)

    return {
        "success": True,
        "cards": {
            "total_balance": total_balance,
            "monthly_income": income_month,
            "monthly_expense": expense_month,
            "budget_remaining": budget_remaining,
            "total_budget": total_budget
        },
        "charts": {
            "pie": pie_data,
            "bar": bar_data,
            "trend": trend_data
        },
        "recent_transactions": recent_txs,
        "onboarding": {
            "is_telegram_linked": is_tg_linked,
            "has_wallet": wallet_count > 0,
            "has_budget": budget_count > 0,
            "has_transactions": has_transactions,
            "is_complete": is_tg_linked and wallet_count > 0 and budget_count > 0 and has_transactions
        }
    }

@router.get("/{tx_id}")
def get_transaction(tx_id: str, user: dict = Depends(get_current_user)):
    tx = TransactionService.get_transaction_by_id(tx_id, user["id"])
    if not tx:
        raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan atau bukan milik Anda.")
    return {"success": True, "data": tx}

@router.delete("/{tx_id}")
def delete_transaction(tx_id: str, user: dict = Depends(get_current_user)):
    try:
        res = TransactionService.delete_transaction(tx_id, user["id"])
        return {"success": True, "message": "Transaksi berhasil dihapus dan saldo dompet telah dipulihkan.", "data": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

