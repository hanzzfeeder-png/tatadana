import calendar
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.database import get_db
from app.config import get_wib_now, get_wib_str

class CalendarService:
    @staticmethod
    def get_month_calendar_data(user_id: str, year: int, month: int) -> Dict[str, Any]:
        """
        Mengambil agregasi transaksi dan catatan harian untuk satu bulan kalender.
        """
        if month < 1 or month > 12:
            raise ValueError("Bulan tidak valid (harus antara 1 dan 12).")

        _, num_days = calendar.monthrange(year, month)
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{year:04d}-{month:02d}-{num_days:02d}"

        conn = get_db()
        cursor = conn.cursor()

        # 1. Fetch transactions aggregated by day
        cursor.execute("""
        SELECT substr(transaction_date, 1, 10) as tx_day,
               type,
               SUM(amount) as total_amt,
               COUNT(id) as count_tx
        FROM transactions
        WHERE user_id = ? AND transaction_date >= ? AND transaction_date <= ?
        GROUP BY tx_day, type
        """, (user_id, f"{start_date} 00:00:00", f"{end_date} 23:59:59"))
        tx_rows = cursor.fetchall()

        daily_agg: Dict[str, Dict[str, Any]] = {}
        total_income_month = 0.0
        total_expense_month = 0.0

        for r in tx_rows:
            day_str = r["tx_day"]
            if day_str not in daily_agg:
                daily_agg[day_str] = {"income": 0.0, "expense": 0.0, "count": 0}
            amt = float(r["total_amt"])
            if r["type"] == "income":
                daily_agg[day_str]["income"] += amt
                total_income_month += amt
            elif r["type"] == "expense":
                daily_agg[day_str]["expense"] += amt
                total_expense_month += amt
            daily_agg[day_str]["count"] += int(r["count_tx"])

        # 2. Fetch daily notes for the month
        cursor.execute("""
        SELECT id, note_date, note_text, mood, created_at, updated_at
        FROM calendar_daily_notes
        WHERE user_id = ? AND note_date >= ? AND note_date <= ?
        """, (user_id, start_date, end_date))
        note_rows = cursor.fetchall()
        daily_notes: Dict[str, Dict[str, Any]] = {}
        for nr in note_rows:
            daily_notes[nr["note_date"]] = {
                "id": nr["id"],
                "note_text": nr["note_text"],
                "mood": nr["mood"] or "neutral",
                "created_at": nr["created_at"],
                "updated_at": nr["updated_at"]
            }

        conn.close()

        # 3. Assemble full month days mapping
        days_data: Dict[str, Any] = {}
        first_weekday = calendar.weekday(year, month, 1) # 0=Monday..6=Sunday
        # Convert to Sunday-based (0=Sunday..6=Saturday)
        first_day_of_week = (first_weekday + 1) % 7

        for d in range(1, num_days + 1):
            d_str = f"{year:04d}-{month:02d}-{d:02d}"
            agg = daily_agg.get(d_str, {"income": 0.0, "expense": 0.0, "count": 0})
            days_data[d_str] = {
                "day": d,
                "date": d_str,
                "income": agg["income"],
                "expense": agg["expense"],
                "net": agg["income"] - agg["expense"],
                "tx_count": agg["count"],
                "note": daily_notes.get(d_str)
            }

        return {
            "year": year,
            "month": month,
            "num_days": num_days,
            "first_day_of_week": first_day_of_week,
            "total_income": total_income_month,
            "total_expense": total_expense_month,
            "net_cashflow": total_income_month - total_expense_month,
            "days": days_data
        }

    @staticmethod
    def get_day_details(user_id: str, date_str: str) -> Dict[str, Any]:
        """
        Mengambil rincian transaksi dan catatan harian untuk tanggal tertentu.
        """
        conn = get_db()
        cursor = conn.cursor()

        # Fetch transactions
        cursor.execute("""
        SELECT t.id, t.type, t.amount, t.note, t.transaction_date, t.source,
               w.name as wallet_name, c.name as category_name, c.icon as category_icon
        FROM transactions t
        LEFT JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.user_id = ? AND t.transaction_date >= ? AND t.transaction_date <= ?
        ORDER BY t.transaction_date ASC
        """, (user_id, f"{date_str} 00:00:00", f"{date_str} 23:59:59"))
        tx_rows = cursor.fetchall()
        tx_list = [dict(r) for r in tx_rows]

        # Fetch note
        cursor.execute("""
        SELECT id, note_date, note_text, mood, created_at, updated_at
        FROM calendar_daily_notes
        WHERE user_id = ? AND note_date = ?
        """, (user_id, date_str))
        note_row = cursor.fetchone()
        note_data = dict(note_row) if note_row else None

        conn.close()

        total_income = sum(float(r["amount"]) for r in tx_list if r["type"] == "income")
        total_expense = sum(float(r["amount"]) for r in tx_list if r["type"] == "expense")

        return {
            "date": date_str,
            "transactions": tx_list,
            "note": note_data,
            "total_income": total_income,
            "total_expense": total_expense,
            "net": total_income - total_expense
        }

    @staticmethod
    def save_daily_note(user_id: str, date_str: str, note_text: str, mood: str = "neutral") -> Dict[str, Any]:
        """
        Menyimpan atau memperbarui catatan harian untuk satu tanggal.
        """
        clean_note = (note_text or "").strip()
        if not clean_note:
            raise ValueError("Teks catatan harian tidak boleh kosong.")

        allowed_moods = {"happy", "neutral", "sad", "saving", "splurge"}
        clean_mood = mood if mood in allowed_moods else "neutral"

        now = get_wib_str()
        note_id = str(uuid.uuid4())

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO calendar_daily_notes (id, user_id, note_date, note_text, mood, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, note_date) DO UPDATE SET
            note_text = excluded.note_text,
            mood = excluded.mood,
            updated_at = excluded.updated_at
        """, (note_id, user_id, date_str, clean_note, clean_mood, now, now))
        conn.commit()

        cursor.execute("SELECT * FROM calendar_daily_notes WHERE user_id = ? AND note_date = ?", (user_id, date_str))
        saved = cursor.fetchone()
        conn.close()

        return dict(saved)

    @staticmethod
    def delete_daily_note(user_id: str, date_str: str) -> bool:
        """
        Menghapus catatan harian pada tanggal tertentu.
        """
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM calendar_daily_notes WHERE user_id = ? AND note_date = ?", (user_id, date_str))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted
