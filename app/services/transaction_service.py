import uuid
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import get_db
from app.config import get_wib_now, get_wib_str

def validate_transaction_date(date_str: Optional[str]) -> str:
    """
    Validasi format dan kewajaran tanggal transaksi.
    Mendukung format 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS', atau ISO-8601.
    """
    if not date_str:
        return get_wib_str()
    clean_str = date_str.strip()
    try:
        if len(clean_str) == 10:  # Format 'YYYY-MM-DD'
            dt = datetime.strptime(clean_str, "%Y-%m-%d")
            now_wib = get_wib_now()
            dt = dt.replace(hour=now_wib.hour, minute=now_wib.minute, second=now_wib.second)
            res = dt.strftime("%Y-%m-%d %H:%M:%S")
        elif "T" in clean_str:
            dt = datetime.fromisoformat(clean_str.replace("Z", "+00:00"))
            res = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
            res = clean_str

        if dt.year < 2000 or dt.year > 2100:
            raise ValueError("Tahun tanggal transaksi tidak wajar (harus antara tahun 2000 s/d 2100).")
        return res
    except Exception as e:
        if isinstance(e, ValueError) and "Tahun tanggal transaksi tidak wajar" in str(e):
            raise
        raise ValueError(f"Format tanggal tidak valid ('{date_str}'). Gunakan format 'YYYY-MM-DD' atau 'YYYY-MM-DD HH:MM:SS'.")

class TransactionService:
    @staticmethod
    def get_monthly_transaction_count(user_id: str, year: int = None, month: int = None) -> int:
        now = get_wib_now()
        year = year or now.year
        month = month or now.month
        month_str = f"{year}-{month:02d}"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE user_id = ? AND transaction_date LIKE ?
        """, (user_id, f"{month_str}%"))
        count = cursor.fetchone()[0]
        conn.close()
        return count

    @staticmethod
    def create_transaction(
        user_id: str,
        wallet_id: str,
        tx_type: str,  # 'expense', 'income', 'transfer'
        amount: float,
        category_id: Optional[str] = None,
        note: Optional[str] = None,
        transaction_date: Optional[str] = None,
        source: str = 'web',
        receipt_url: Optional[str] = None,
        receipt_items: Optional[List[Dict[str, Any]]] = None,
        target_wallet_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if tx_type not in ("expense", "income", "transfer"):
            raise ValueError(f"Jenis transaksi '{tx_type}' tidak valid. Pilihan yang tersedia: 'expense', 'income', 'transfer'.")

        if amount <= 0:
            raise ValueError("Nominal transaksi harus lebih besar dari Rp 0.")

        valid_date_str = validate_transaction_date(transaction_date)

        conn = get_db()
        cursor = conn.cursor()
        try:
            # 1. Enforce Plan Limits: Starter max 50 transactions / month
            cursor.execute("SELECT plan FROM profiles WHERE id = ?", (user_id,))
            p = cursor.fetchone()
            plan = p["plan"] if p else "starter"

            now_wib = get_wib_now()
            month_str = now_wib.strftime("%Y-%m")

            cursor.execute("""
            SELECT COUNT(*) FROM transactions
            WHERE user_id = ? AND transaction_date LIKE ?
            """, (user_id, f"{month_str}%"))
            monthly_count = cursor.fetchone()[0]

            if plan == "starter" and monthly_count >= 50:
                raise ValueError("Batas transaksi bulanan tercapai (50/50 transaksi). Upgrade ke TataDana Pro untuk pencatatan tanpa batas!")

            # 2. Verify Wallet Ownership (Dompet Asal)
            cursor.execute("SELECT id, name, balance FROM wallets WHERE id = ? AND user_id = ?", (wallet_id, user_id))
            wallet = cursor.fetchone()
            if not wallet:
                raise ValueError("Dompet asal tidak ditemukan atau bukan milik Anda.")

            # 3. Verify Target Wallet Ownership if Transfer (Dompet Tujuan)
            if tx_type == "transfer":
                if not target_wallet_id:
                    raise ValueError("Target dompet tujuan wajib dipilih untuk jenis transfer.")
                if target_wallet_id == wallet_id:
                    raise ValueError("Dompet asal dan target dompet tujuan transfer tidak boleh sama.")
                cursor.execute("SELECT id, name, balance FROM wallets WHERE id = ? AND user_id = ?", (target_wallet_id, user_id))
                target_wallet = cursor.fetchone()
                if not target_wallet:
                    raise ValueError("Dompet tujuan tidak ditemukan atau bukan milik Anda.")
            else:
                target_wallet_id = None

            # 4. Verify Category Ownership & Type Matching
            if category_id:
                cursor.execute("SELECT id, name, type FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id))
                category = cursor.fetchone()
                if not category:
                    raise ValueError("Kategori tidak ditemukan atau bukan milik Anda.")
                if tx_type in ("expense", "income") and category["type"] != tx_type:
                    jenis_target = "pengeluaran" if tx_type == "expense" else "pemasukan"
                    jenis_kat = "pengeluaran" if category["type"] == "expense" else "pemasukan"
                    raise ValueError(f"Kategori '{category['name']}' adalah pos {jenis_kat}, tidak cocok untuk transaksi bertipe {jenis_target}.")

            tx_id = str(uuid.uuid4())
            items_json = json.dumps(receipt_items or [])

            # 5. Update Balance Atomically
            if tx_type == "expense":
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, valid_date_str, wallet_id))
            elif tx_type == "income":
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, valid_date_str, wallet_id))
            elif tx_type == "transfer":
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, valid_date_str, wallet_id))
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, valid_date_str, target_wallet_id))

            # 6. Insert Transaction
            cursor.execute("""
            INSERT INTO transactions (
                id, user_id, wallet_id, target_wallet_id, category_id, type, amount, note,
                transaction_date, source, receipt_url, receipt_items, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tx_id, user_id, wallet_id, target_wallet_id, category_id, tx_type,
                amount, note or "", valid_date_str, source, receipt_url, items_json, valid_date_str
            ))

            conn.commit()

            cursor.execute("""
            SELECT t.*, w.name as wallet_name, c.name as category_name, c.icon as category_icon, c.color as category_color,
                   tw.name as target_wallet_name
            FROM transactions t
            LEFT JOIN wallets w ON w.id = t.wallet_id
            LEFT JOIN wallets tw ON tw.id = t.target_wallet_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = ?
            """, (tx_id,))
            result = dict(cursor.fetchone())
            result["receipt_items"] = json.loads(result.get("receipt_items") or "[]")
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def update_transaction(
        tx_id: str,
        user_id: str,
        wallet_id: Optional[str] = None,
        tx_type: Optional[str] = None,
        amount: Optional[float] = None,
        category_id: Optional[str] = None,
        note: Optional[str] = None,
        target_wallet_id: Optional[str] = None,
        transaction_date: Optional[str] = None
    ) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()
        try:
            # 1. Pastikan transaksi ada dan milik user
            cursor.execute("SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
            old_tx = cursor.fetchone()
            if not old_tx:
                raise ValueError("Transaksi tidak ditemukan atau bukan milik Anda.")

            old_wallet_id = old_tx["wallet_id"]
            old_target_wallet_id = old_tx["target_wallet_id"]
            old_type = old_tx["type"]
            old_amount = float(old_tx["amount"])

            new_wallet_id = wallet_id or old_wallet_id
            new_type = tx_type or old_type
            new_amount = float(amount) if amount is not None else old_amount
            new_target_wallet_id = target_wallet_id if target_wallet_id is not None else old_target_wallet_id
            new_category_id = category_id if category_id is not None else old_tx["category_id"]

            if new_type not in ("expense", "income", "transfer"):
                raise ValueError(f"Jenis transaksi '{new_type}' tidak valid.")

            if new_amount <= 0:
                raise ValueError("Nominal transaksi harus lebih besar dari Rp 0.")

            new_date = validate_transaction_date(transaction_date) if transaction_date else old_tx["transaction_date"]

            # 2. Validasi kepemilikan dompet asal baru
            cursor.execute("SELECT id FROM wallets WHERE id = ? AND user_id = ?", (new_wallet_id, user_id))
            if not cursor.fetchone():
                raise ValueError("Dompet asal tidak ditemukan atau bukan milik Anda.")

            # 3. Validasi kepemilikan dompet tujuan jika transfer
            if new_type == "transfer":
                if not new_target_wallet_id:
                    raise ValueError("Target dompet tujuan wajib dipilih untuk jenis transfer.")
                if new_target_wallet_id == new_wallet_id:
                    raise ValueError("Dompet asal dan target dompet tujuan transfer tidak boleh sama.")
                cursor.execute("SELECT id FROM wallets WHERE id = ? AND user_id = ?", (new_target_wallet_id, user_id))
                if not cursor.fetchone():
                    raise ValueError("Dompet tujuan tidak ditemukan atau bukan milik Anda.")
            else:
                new_target_wallet_id = None

            # 4. Validasi kepemilikan kategori dan kecocokan jenis
            if new_category_id:
                cursor.execute("SELECT id, name, type FROM categories WHERE id = ? AND user_id = ?", (new_category_id, user_id))
                cat = cursor.fetchone()
                if not cat:
                    raise ValueError("Kategori tidak ditemukan atau bukan milik Anda.")
                if new_type in ("expense", "income") and cat["type"] != new_type:
                    jenis_target = "pengeluaran" if new_type == "expense" else "pemasukan"
                    jenis_kat = "pengeluaran" if cat["type"] == "expense" else "pemasukan"
                    raise ValueError(f"Kategori '{cat['name']}' adalah pos {jenis_kat}, tidak cocok untuk transaksi bertipe {jenis_target}.")

            now_str = get_wib_str()

            # 5. Batalkan efek saldo lama
            if old_type == "expense":
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (old_amount, now_str, old_wallet_id))
            elif old_type == "income":
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (old_amount, now_str, old_wallet_id))
            elif old_type == "transfer" and old_target_wallet_id:
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (old_amount, now_str, old_wallet_id))
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (old_amount, now_str, old_target_wallet_id))

            # 6. Terapkan efek saldo baru
            if new_type == "expense":
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (new_amount, now_str, new_wallet_id))
            elif new_type == "income":
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (new_amount, now_str, new_wallet_id))
            elif new_type == "transfer":
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (new_amount, now_str, new_wallet_id))
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (new_amount, now_str, new_target_wallet_id))

            # 7. Update data transaksi
            new_note = note if note is not None else old_tx["note"]

            cursor.execute("""
            UPDATE transactions
            SET wallet_id = ?, target_wallet_id = ?, category_id = ?, type = ?, amount = ?, note = ?, transaction_date = ?
            WHERE id = ? AND user_id = ?
            """, (new_wallet_id, new_target_wallet_id, new_category_id, new_type, new_amount, new_note, new_date, tx_id, user_id))

            conn.commit()

            cursor.execute("""
            SELECT t.*, w.name as wallet_name, c.name as category_name, c.icon as category_icon, c.color as category_color,
                   tw.name as target_wallet_name
            FROM transactions t
            LEFT JOIN wallets w ON w.id = t.wallet_id
            LEFT JOIN wallets tw ON tw.id = t.target_wallet_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = ?
            """, (tx_id,))
            result = dict(cursor.fetchone())
            result["receipt_items"] = json.loads(result.get("receipt_items") or "[]")
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_transaction(tx_id: str, user_id: str) -> Dict[str, Any]:
        """
        Menghapus transaksi dan membatalkan mutasi saldo secara atomik.
        """
        conn = get_db()
        cursor = conn.cursor()
        try:
            # 1. Pastikan transaksi ada dan milik user
            cursor.execute("SELECT * FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
            tx = cursor.fetchone()
            if not tx:
                raise ValueError("Transaksi tidak ditemukan atau bukan milik Anda.")

            wallet_id = tx["wallet_id"]
            target_wallet_id = tx["target_wallet_id"]
            tx_type = tx["type"]
            amount = float(tx["amount"])
            now_str = get_wib_str()

            # 2. Kembalikan efek saldo lama secara atomik
            if tx_type == "expense":
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, now_str, wallet_id))
            elif tx_type == "income":
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, now_str, wallet_id))
            elif tx_type == "transfer" and target_wallet_id:
                cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, now_str, wallet_id))
                cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, now_str, target_wallet_id))

            # 3. Hapus baris transaksi
            cursor.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
            conn.commit()

            return {
                "id": tx_id,
                "deleted": True,
                "reverted_amount": amount,
                "type": tx_type
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def get_transaction_by_id(tx_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT t.*, w.name as wallet_name, c.name as category_name, c.icon as category_icon, c.color as category_color,
               tw.name as target_wallet_name
        FROM transactions t
        LEFT JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN wallets tw ON tw.id = t.target_wallet_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.id = ? AND t.user_id = ?
        """, (tx_id, user_id))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        res = dict(row)
        res["receipt_items"] = json.loads(res.get("receipt_items") or "[]")
        return res

    @staticmethod
    def get_recent_transactions(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT t.*, w.name as wallet_name, c.name as category_name, c.icon as category_icon, c.color as category_color,
               tw.name as target_wallet_name
        FROM transactions t
        LEFT JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN wallets tw ON tw.id = t.target_wallet_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.user_id = ?
        ORDER BY t.transaction_date DESC
        LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()
        conn.close()

        res = []
        for r in rows:
            d = dict(r)
            d["receipt_items"] = json.loads(d.get("receipt_items") or "[]")
            res.append(d)
        return res
