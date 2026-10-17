import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import get_db
from app.config import get_wib_now, get_wib_str

class BudgetService:
    @staticmethod
    def get_categories(user_id: str, cat_type: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        query = "SELECT id, name, type, icon, color, monthly_budget, is_system, created_at FROM categories WHERE user_id = ?"
        params = [user_id]
        if cat_type:
            query += " AND type = ?"
            params.append(cat_type)
        query += " ORDER BY type DESC, name ASC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def create_category(user_id: str, name: str, cat_type: str, icon: str = '🏷️',
                        color: str = '#FF6B00', monthly_budget: float = 0.0) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()

        # Check budget limits if setting budget > 0
        if monthly_budget > 0:
            cursor.execute("SELECT plan FROM profiles WHERE id = ?", (user_id,))
            p = cursor.fetchone()
            plan = p["plan"] if p else "free"
            if plan in ["free", "none", "inactive"]:
                cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ? AND monthly_budget > 0 AND is_system = 0", (user_id,))
                budget_count = cursor.fetchone()[0]
                if budget_count >= 2:
                    conn.close()
                    raise ValueError("Akun Free dibatasi maksimal 2 budget kategori kustom. Beli Paket Starter (maks 5) atau Pro (unlimited) di menu Pengaturan/Billing!")
            elif plan == "starter":
                cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ? AND monthly_budget > 0 AND is_system = 0", (user_id,))
                budget_count = cursor.fetchone()[0]
                if budget_count >= 5:
                    conn.close()
                    raise ValueError("Paket Starter dibatasi maksimal 5 budget kategori. Upgrade ke Pro untuk budget tak terbatas!")

        cat_id = str(uuid.uuid4())
        now = get_wib_str()
        cursor.execute("""
        INSERT INTO categories (id, user_id, name, type, icon, color, monthly_budget, is_system, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (cat_id, user_id, name.strip(), cat_type, icon, color, float(monthly_budget), now))
        conn.commit()
        conn.close()
        return {
            "id": cat_id,
            "name": name,
            "type": cat_type,
            "icon": icon,
            "color": color,
            "monthly_budget": monthly_budget
        }

    @staticmethod
    def update_category(category_id: str, user_id: str, name: Optional[str] = None,
                        icon: Optional[str] = None, color: Optional[str] = None,
                        monthly_budget: Optional[float] = None) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()

        if monthly_budget is not None and monthly_budget > 0:
            cursor.execute("SELECT plan FROM profiles WHERE id = ?", (user_id,))
            p = cursor.fetchone()
            plan = p["plan"] if p else "free"
            if plan in ["free", "none", "inactive"]:
                cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ? AND monthly_budget > 0 AND is_system = 0 AND id != ?", (user_id, category_id))
                budget_count = cursor.fetchone()[0]
                if budget_count >= 2:
                    conn.close()
                    raise ValueError("Akun Free dibatasi maksimal 2 budget kategori kustom. Silakan upgrade ke Paket Starter atau Pro!")
            elif plan == "starter":
                cursor.execute("SELECT COUNT(*) FROM categories WHERE user_id = ? AND monthly_budget > 0 AND is_system = 0 AND id != ?", (user_id, category_id))
                budget_count = cursor.fetchone()[0]
                if budget_count >= 5:
                    conn.close()
                    raise ValueError("Paket Starter dibatasi maksimal 5 budget kategori.")

        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())
        if icon is not None:
            updates.append("icon = ?")
            params.append(icon)
        if color is not None:
            updates.append("color = ?")
            params.append(color)
        if monthly_budget is not None:
            updates.append("monthly_budget = ?")
            params.append(float(monthly_budget))

        if updates:
            params.extend([category_id, user_id])
            cursor.execute(f"UPDATE categories SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
            conn.commit()

        cursor.execute("SELECT * FROM categories WHERE id = ? AND user_id = ?", (category_id, user_id))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}

    @staticmethod
    def get_budget_statuses(user_id: str, year: int = None, month: int = None) -> List[Dict[str, Any]]:
        now = get_wib_now()
        year = year or now.year
        month = month or now.month
        month_str = f"{year}-{month:02d}"

        conn = get_db()
        cursor = conn.cursor()

        # Get categories with their monthly budget
        cursor.execute("""
        SELECT c.id, c.name, c.icon, c.color, c.monthly_budget,
               COALESCE(SUM(t.amount), 0.0) as total_spent
        FROM categories c
        LEFT JOIN transactions t ON t.category_id = c.id 
             AND t.user_id = c.user_id 
             AND t.type = 'expense'
             AND t.transaction_date LIKE ?
        WHERE c.user_id = ? AND c.type = 'expense'
        GROUP BY c.id
        ORDER BY c.monthly_budget DESC, total_spent DESC
        """, (f"{month_str}%", user_id))

        results = []
        for row in cursor.fetchall():
            budget = float(row["monthly_budget"])
            spent = float(row["total_spent"])
            remaining = max(0.0, budget - spent)
            percent = (spent / budget * 100.0) if budget > 0 else 0.0

            # Generate visual progress bar (10 blocks)
            blocks_filled = min(10, int(round((percent / 100.0) * 10)))
            progress_bar = "█" * blocks_filled + "░" * (10 - blocks_filled)

            results.append({
                "category_id": row["id"],
                "name": row["name"],
                "icon": row["icon"],
                "color": row["color"],
                "monthly_budget": budget,
                "spent": spent,
                "remaining": remaining,
                "percent": round(percent, 1),
                "progress_bar": progress_bar,
                "is_over_80": percent >= 80.0,
                "is_exceeded": percent >= 100.0
            })

        conn.close()
        return results

    @staticmethod
    def get_single_category_budget_status(user_id: str, category_id: str) -> Optional[Dict[str, Any]]:
        statuses = BudgetService.get_budget_statuses(user_id)
        for s in statuses:
            if s["category_id"] == category_id:
                return s
        return None
