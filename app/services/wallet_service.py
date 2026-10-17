import uuid
from typing import List, Dict, Any, Optional
from app.database import get_db
from app.config import get_wib_str

class WalletService:
    @staticmethod
    def get_wallets(user_id: str) -> List[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, name, type, balance, is_default, icon, color, created_at, updated_at
        FROM wallets
        WHERE user_id = ?
        ORDER BY is_default DESC, name ASC
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_wallet_by_id(wallet_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallets WHERE id = ? AND user_id = ?", (wallet_id, user_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_default_wallet(user_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM wallets WHERE user_id = ? AND is_default = 1", (user_id,))
        row = cursor.fetchone()
        if not row:
            # Fallback to first wallet
            cursor.execute("SELECT * FROM wallets WHERE user_id = ? ORDER BY created_at ASC LIMIT 1", (user_id,))
            row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def create_wallet(user_id: str, name: str, wallet_type: str, initial_balance: float = 0.0,
                      icon: str = '👛', color: str = '#FF6B00', is_default: bool = False) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()

        # Check Plan limit: Starter max 3 wallets
        cursor.execute("SELECT plan FROM profiles WHERE id = ?", (user_id,))
        p = cursor.fetchone()
        plan = p["plan"] if p else "starter"

        cursor.execute("SELECT COUNT(*) FROM wallets WHERE user_id = ?", (user_id,))
        current_count = cursor.fetchone()[0]

        if plan == "starter" and current_count >= 3:
            conn.close()
            raise ValueError("Paket Starter dibatasi maksimal 3 dompet. Upgrade ke paket Pro untuk membuat dompet tanpa batas!")

        wallet_id = str(uuid.uuid4())
        now = get_wib_str()

        if is_default or current_count == 0:
            cursor.execute("UPDATE wallets SET is_default = 0 WHERE user_id = ?", (user_id,))
            is_default = True

        cursor.execute("""
        INSERT INTO wallets (id, user_id, name, type, balance, is_default, icon, color, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (wallet_id, user_id, name, wallet_type, float(initial_balance), 1 if is_default else 0, icon, color, now, now))

        conn.commit()
        conn.close()
        return WalletService.get_wallet_by_id(wallet_id, user_id)

    @staticmethod
    def update_wallet(wallet_id: str, user_id: str, name: Optional[str] = None,
                      wallet_type: Optional[str] = None, icon: Optional[str] = None,
                      color: Optional[str] = None, is_default: Optional[bool] = None) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()

        if is_default:
            cursor.execute("UPDATE wallets SET is_default = 0 WHERE user_id = ?", (user_id,))

        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if wallet_type is not None:
            updates.append("type = ?")
            params.append(wallet_type)
        if icon is not None:
            updates.append("icon = ?")
            params.append(icon)
        if color is not None:
            updates.append("color = ?")
            params.append(color)
        if is_default is not None:
            updates.append("is_default = ?")
            params.append(1 if is_default else 0)

        updates.append("updated_at = ?")
        params.append(now)
        params.extend([wallet_id, user_id])

        cursor.execute(f"UPDATE wallets SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
        conn.commit()
        conn.close()
        return WalletService.get_wallet_by_id(wallet_id, user_id)

    @staticmethod
    def transfer(user_id: str, source_wallet_id: str, target_wallet_id: str,
                 amount: float, note: Optional[str] = None) -> Dict[str, Any]:
        if source_wallet_id == target_wallet_id:
            raise ValueError("Dompet asal dan tujuan tidak boleh sama.")
        if amount <= 0:
            raise ValueError("Nominal transfer harus lebih besar dari 0.")

        conn = get_db()
        cursor = conn.cursor()
        now = get_wib_str()

        # Check balances
        cursor.execute("SELECT balance, name FROM wallets WHERE id = ? AND user_id = ?", (source_wallet_id, user_id))
        source = cursor.fetchone()
        cursor.execute("SELECT balance, name FROM wallets WHERE id = ? AND user_id = ?", (target_wallet_id, user_id))
        target = cursor.fetchone()

        if not source or not target:
            conn.close()
            raise ValueError("Dompet asal atau tujuan tidak ditemukan.")

        if source["balance"] < amount:
            conn.close()
            raise ValueError(f"Saldo {source['name']} tidak mencukupi (Rp {source['balance']:,.0f}).")

        # Deduct source, Add target
        cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE id = ?", (amount, now, source_wallet_id))
        cursor.execute("UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE id = ?", (amount, now, target_wallet_id))

        # Record transaction
        tx_id = str(uuid.uuid4())
        desc = note or f"Transfer dari {source['name']} ke {target['name']}"
        cursor.execute("""
        INSERT INTO transactions (id, user_id, wallet_id, target_wallet_id, category_id, type, amount, note, transaction_date, source, created_at)
        VALUES (?, ?, ?, ?, NULL, 'transfer', ?, ?, ?, 'web', ?)
        """, (tx_id, user_id, source_wallet_id, target_wallet_id, amount, desc, now, now))

        conn.commit()
        conn.close()
        return {
            "transaction_id": tx_id,
            "source_wallet": source["name"],
            "target_wallet": target["name"],
            "amount": amount,
            "note": desc
        }
