from typing import Dict, Any, Optional
from app.database import get_db
from app.config import get_wib_str

class ReminderService:
    @staticmethod
    def get_reminder_settings(user_id: str) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {
                "is_active": True,
                "frequency": 1,
                "time_1": "20:00",
                "time_2": "08:00",
                "preview": ReminderService.get_preview_text()
            }
        d = dict(row)
        d["is_active"] = bool(d["is_active"])
        d["preview"] = ReminderService.get_preview_text()
        return d

    @staticmethod
    def update_reminder_settings(user_id: str, is_active: bool, frequency: int, time_1: str, time_2: Optional[str] = "20:00") -> Dict[str, Any]:
        if frequency not in [1, 2]:
            raise ValueError("Frekuensi reminder hanya boleh 1x atau 2x sehari sesuai kebijakan produk TataDana.")

        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()

        cursor.execute("""
        UPDATE reminders
        SET is_active = ?, frequency = ?, time_1 = ?, time_2 = ?, updated_at = ?
        WHERE user_id = ?
        """, (1 if is_active else 0, frequency, time_1, time_2 or "20:00", now, user_id))

        conn.commit()
        conn.close()
        return ReminderService.get_reminder_settings(user_id)

    @staticmethod
    def get_preview_text() -> str:
        return (
            "⏰ Reminder Keuangan!\n"
            "Jangan lupa catat pengeluaran hari ini ya 📝\n"
            "Pencatatan rutin = keuangan lebih terkontrol 💪\n"
            "Ketik transaksimu sekarang!"
        )
