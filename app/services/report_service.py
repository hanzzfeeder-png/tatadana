import os
import uuid
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

from app.database import get_db
from app.config import settings, get_wib_now, get_wib_str, format_wib_display

STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage", "exports")
os.makedirs(STORAGE_DIR, exist_ok=True)

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Bottom divider line
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(30, 36, 565, 36)
        
        # Footer text & page numbering
        self.drawString(30, 24, "TataDana — Smart Personal Finance SaaS | Laporan Keuangan Resmi (WIB)")
        page_text = f"Halaman {self._pageNumber} dari {page_count}"
        self.drawRightString(565, 24, page_text)
        self.restoreState()

class ReportService:
    @staticmethod
    def get_report_summary(user_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        # Validasi Rentang Tanggal
        if start_date and end_date:
            if start_date > end_date:
                raise ValueError("Tanggal mulai laporan tidak boleh lebih besar dari tanggal akhir.")

        conn = get_db()
        cursor = conn.cursor()

        query_income = "SELECT COALESCE(SUM(amount), 0.0) FROM transactions WHERE user_id = ? AND type = 'income'"
        query_expense = "SELECT COALESCE(SUM(amount), 0.0) FROM transactions WHERE user_id = ? AND type = 'expense'"
        query_transfer = "SELECT COALESCE(SUM(amount), 0.0), COUNT(id) FROM transactions WHERE user_id = ? AND type = 'transfer'"

        params_inc = [user_id]
        params_exp = [user_id]
        params_trf = [user_id]

        if start_date:
            query_income += " AND transaction_date >= ?"
            query_expense += " AND transaction_date >= ?"
            query_transfer += " AND transaction_date >= ?"
            params_inc.append(f"{start_date} 00:00:00")
            params_exp.append(f"{start_date} 00:00:00")
            params_trf.append(f"{start_date} 00:00:00")
        if end_date:
            query_income += " AND transaction_date <= ?"
            query_expense += " AND transaction_date <= ?"
            query_transfer += " AND transaction_date <= ?"
            params_inc.append(f"{end_date} 23:59:59")
            params_exp.append(f"{end_date} 23:59:59")
            params_trf.append(f"{end_date} 23:59:59")

        cursor.execute(query_income, params_inc)
        total_income = float(cursor.fetchone()[0])

        cursor.execute(query_expense, params_exp)
        total_expense = float(cursor.fetchone()[0])

        cursor.execute(query_transfer, params_trf)
        row_trf = cursor.fetchone()
        total_transfer_volume = float(row_trf[0])
        total_transfer_count = int(row_trf[1])

        net_cashflow = total_income - total_expense

        # Breakdown Seluruh Kategori Pengeluaran beserta Persentase
        query_cat = """
        SELECT c.id, c.name, c.icon, c.color, COALESCE(SUM(t.amount), 0.0) as total_spent, COUNT(t.id) as transaction_count
        FROM categories c
        JOIN transactions t ON t.category_id = c.id AND t.user_id = c.user_id AND t.type = 'expense'
        WHERE c.user_id = ?
        """
        params_cat = [user_id]
        if start_date:
            query_cat += " AND t.transaction_date >= ?"
            params_cat.append(f"{start_date} 00:00:00")
        if end_date:
            query_cat += " AND t.transaction_date <= ?"
            params_cat.append(f"{end_date} 23:59:59")

        query_cat += " GROUP BY c.id ORDER BY total_spent DESC"
        cursor.execute(query_cat, params_cat)
        cat_rows = cursor.fetchall()

        category_breakdown = []
        for r in cat_rows:
            spent = float(r["total_spent"])
            pct = round((spent / total_expense * 100), 2) if total_expense > 0 else 0.0
            category_breakdown.append({
                "category_id": r["id"],
                "name": r["name"],
                "icon": r["icon"],
                "color": r["color"] or "#FF6B00",
                "total_spent": spent,
                "percentage": pct,
                "transaction_count": int(r["transaction_count"])
            })

        top_categories = category_breakdown[:5]

        conn.close()
        return {
            "total_income": total_income,
            "total_expense": total_expense,
            "net_cashflow": net_cashflow,
            "savings_rate": round((net_cashflow / total_income * 100), 1) if total_income > 0 else 0.0,
            "category_breakdown": category_breakdown,
            "top_categories": top_categories,
            "transfer_summary": {
                "total_volume": total_transfer_volume,
                "count": total_transfer_count,
                "note": "Transfer internal tidak dihitung sebagai pemasukan atau pengeluaran kas."
            }
        }


    @staticmethod
    def get_filtered_transactions(
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        tx_type: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: str = "transaction_date",
        sort_order: str = "DESC",
        page: int = 1,
        page_size: int = 15
    ) -> Dict[str, Any]:
        conn = get_db()
        cursor = conn.cursor()

        # Check plan
        cursor.execute("SELECT plan FROM profiles WHERE id = ?", (user_id,))
        p = cursor.fetchone()
        plan = p["plan"] if p else "starter"

        # Starter plan limitation: only monthly summary, no advanced filtering
        if plan == "starter":
            # For Starter, enforce current month only and no category/search filter
            now = get_wib_now()
            start_date = now.strftime("%Y-%m-01")
            category_id = None
            wallet_id = None
            search_query = None

        where_clauses = ["t.user_id = ?"]
        params = [user_id]

        if start_date:
            where_clauses.append("t.transaction_date >= ?")
            params.append(f"{start_date} 00:00:00")
        if end_date:
            where_clauses.append("t.transaction_date <= ?")
            params.append(f"{end_date} 23:59:59")
        if category_id:
            where_clauses.append("t.category_id = ?")
            params.append(category_id)
        if wallet_id:
            where_clauses.append("t.wallet_id = ?")
            params.append(wallet_id)
        if tx_type:
            where_clauses.append("t.type = ?")
            params.append(tx_type)
        if search_query:
            where_clauses.append("t.note LIKE ?")
            params.append(f"%{search_query.strip()}%")

        where_sql = " AND ".join(where_clauses)

        # Count total
        cursor.execute(f"SELECT COUNT(*) FROM transactions t WHERE {where_sql}", params)
        total_records = cursor.fetchone()[0]

        # Valid columns for sorting
        allowed_sorts = {
            "transaction_date": "t.transaction_date",
            "amount": "t.amount",
            "category": "c.name",
            "wallet": "w.name"
        }
        order_col = allowed_sorts.get(sort_by, "t.transaction_date")
        order_dir = "ASC" if sort_order.upper() == "ASC" else "DESC"

        offset = (page - 1) * page_size
        query = f"""
        SELECT t.*, w.name as wallet_name, c.name as category_name, c.icon as category_icon, c.color as category_color
        FROM transactions t
        LEFT JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE {where_sql}
        ORDER BY {order_col} {order_dir}
        LIMIT ? OFFSET ?
        """
        cursor.execute(query, params + [page_size, offset])
        rows = cursor.fetchall()
        conn.close()

        items = []
        for r in rows:
            d = dict(r)
            d["receipt_items"] = json.loads(d.get("receipt_items") or "[]")
            items.append(d)

        return {
            "transactions": items,
            "total_records": total_records,
            "page": page,
            "page_size": page_size,
            "total_pages": (total_records + page_size - 1) // page_size if page_size > 0 else 1,
            "plan": plan
        }

    @staticmethod
    def generate_excel_report(
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        tx_type: Optional[str] = None
    ) -> str:
        # Check plan
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT full_name, plan FROM profiles WHERE id = ?", (user_id,))
        p = cursor.fetchone()
        if not p or p["plan"] != "pro":
            conn.close()
            raise ValueError("Fitur Export Laporan Excel eksklusif untuk pengguna paket Pro.")

        user_name = p["full_name"]

        # Fetch all transactions in range
        where_clauses = ["t.user_id = ?"]
        params = [user_id]
        if start_date:
            where_clauses.append("t.transaction_date >= ?")
            params.append(f"{start_date} 00:00:00")
        if end_date:
            where_clauses.append("t.transaction_date <= ?")
            params.append(f"{end_date} 23:59:59")
        if category_id:
            where_clauses.append("t.category_id = ?")
            params.append(category_id)
        if wallet_id:
            where_clauses.append("t.wallet_id = ?")
            params.append(wallet_id)
        if tx_type:
            where_clauses.append("t.type = ?")
            params.append(tx_type)

        cursor.execute(f"""
        SELECT t.transaction_date, t.type, t.amount, t.note, t.source, t.receipt_items,
               w.name as wallet_name, c.name as category_name
        FROM transactions t
        LEFT JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE {" AND ".join(where_clauses)}
        ORDER BY t.transaction_date ASC
        """, params)
        rows = cursor.fetchall()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Laporan TataDana"

        # Theme Colors: Orange (#FF6B00)
        orange_fill = PatternFill(start_color="FF6B00", end_color="FF6B00", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=16, bold=True, color="FF6B00")
        sub_font = Font(name="Calibri", size=10, italic=True, color="64748B")
        bold_font = Font(name="Calibri", size=11, bold=True)
        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='E2E8F0'),
            bottom=Side(style='thin', color='E2E8F0')
        )

        # Title
        ws.cell(row=1, column=1, value="TataDana — Laporan Keuangan Pribadi").font = title_font
        period_text = f"Periode: {start_date or 'Awal'} s/d {end_date or 'Sekarang'} | Pemilik: {user_name} | Generated: {format_wib_display()}"
        ws.cell(row=2, column=1, value=period_text).font = sub_font

        # Headers
        headers = ["No", "Tanggal (WIB)", "Jenis", "Kategori", "Dompet", "Nominal (IDR)", "Catatan", "Sumber", "Rincian Item Struk"]
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col_idx, value=h)
            cell.fill = orange_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center" if col_idx in [1, 2, 3, 8] else "left", vertical="center")

        total_income = 0.0
        total_expense = 0.0

        for idx, r in enumerate(rows, 1):
            row_idx = 4 + idx
            amount = float(r["amount"])
            tx_type = "Pemasukan" if r["type"] == "income" else ("Pengeluaran" if r["type"] == "expense" else "Transfer")
            if r["type"] == "income":
                total_income += amount
            elif r["type"] == "expense":
                total_expense += amount

            items_str = ""
            try:
                items = json.loads(r["receipt_items"] or "[]")
                if items:
                    items_str = ", ".join([f"{it.get('name')}: Rp{it.get('price', 0):,}" for it in items])
            except Exception:
                pass

            ws.cell(row=row_idx, column=1, value=idx).alignment = Alignment(horizontal="center")
            ws.cell(row=row_idx, column=2, value=r["transaction_date"][:16])
            ws.cell(row=row_idx, column=3, value=tx_type)
            ws.cell(row=row_idx, column=4, value=r["category_name"] or "-")
            ws.cell(row=row_idx, column=5, value=r["wallet_name"] or "-")
            
            num_cell = ws.cell(row=row_idx, column=6, value=amount)
            num_cell.number_format = '#,##0'
            num_cell.alignment = Alignment(horizontal="right")

            ws.cell(row=row_idx, column=7, value=r["note"] or "-")
            ws.cell(row=row_idx, column=8, value=r["source"] or "web")
            ws.cell(row=row_idx, column=9, value=items_str)

            for c in range(1, 10):
                ws.cell(row=row_idx, column=c).border = thin_border

        # Summary Row
        summary_row = 5 + len(rows)
        ws.cell(row=summary_row, column=5, value="Total Pemasukan").font = bold_font
        c_inc = ws.cell(row=summary_row, column=6, value=total_income)
        c_inc.number_format = '#,##0'
        c_inc.font = bold_font

        ws.cell(row=summary_row+1, column=5, value="Total Pengeluaran").font = bold_font
        c_exp = ws.cell(row=summary_row+1, column=6, value=total_expense)
        c_exp.number_format = '#,##0'
        c_exp.font = bold_font

        ws.cell(row=summary_row+2, column=5, value="Net Cashflow").font = bold_font
        c_net = ws.cell(row=summary_row+2, column=6, value=total_income - total_expense)
        c_net.number_format = '#,##0'
        c_net.font = bold_font

        # Column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        file_id = f"TataDana_Laporan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.xlsx"
        file_path = os.path.join(STORAGE_DIR, file_id)
        wb.save(file_path)

        # Save to Export History
        now_wib = get_wib_str()
        cursor.execute("""
        INSERT INTO export_history (id, user_id, file_name, file_type, file_path, storage_url, period_start, period_end, download_count, created_at)
        VALUES (?, ?, ?, 'xlsx', ?, ?, ?, ?, 0, ?)
        """, (str(uuid.uuid4()), user_id, file_id, file_path, f"/api/reports/download/{file_id}", start_date, end_date, now_wib))
        conn.commit()
        conn.close()

        return file_id

    @staticmethod
    def generate_pdf_report(
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        tx_type: Optional[str] = None
    ) -> str:
        # Check plan
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT full_name, plan FROM profiles WHERE id = ?", (user_id,))
        p = cursor.fetchone()
        if not p or p["plan"] != "pro":
            conn.close()
            raise ValueError("Fitur Export Laporan PDF eksklusif untuk pengguna paket Pro.")

        user_name = p["full_name"]

        # Fetch transactions with filters
        where_clauses = ["t.user_id = ?"]
        params = [user_id]
        filter_descs = []

        if start_date:
            where_clauses.append("t.transaction_date >= ?")
            params.append(f"{start_date} 00:00:00")
        if end_date:
            where_clauses.append("t.transaction_date <= ?")
            params.append(f"{end_date} 23:59:59")
        if category_id:
            where_clauses.append("t.category_id = ?")
            params.append(category_id)
            cursor.execute("SELECT name FROM categories WHERE id = ?", (category_id,))
            c_row = cursor.fetchone()
            if c_row:
                filter_descs.append(f"Kategori: {c_row['name']}")
        if wallet_id:
            where_clauses.append("t.wallet_id = ?")
            params.append(wallet_id)
            cursor.execute("SELECT name FROM wallets WHERE id = ?", (wallet_id,))
            w_row = cursor.fetchone()
            if w_row:
                filter_descs.append(f"Dompet: {w_row['name']}")
        if tx_type:
            where_clauses.append("t.type = ?")
            params.append(tx_type)
            type_label = "Pemasukan" if tx_type == "income" else ("Pengeluaran" if tx_type == "expense" else "Transfer")
            filter_descs.append(f"Jenis: {type_label}")

        cursor.execute(f"""
        SELECT t.transaction_date, t.type, t.amount, t.note,
               w.name as wallet_name, c.name as category_name
        FROM transactions t
        LEFT JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE {" AND ".join(where_clauses)}
        ORDER BY t.transaction_date DESC
        LIMIT 500
        """, params)
        rows = cursor.fetchall()

        file_id = f"TataDana_Laporan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.pdf"
        file_path = os.path.join(STORAGE_DIR, file_id)

        doc = SimpleDocTemplate(
            file_path,
            pagesize=A4,
            rightMargin=30,
            leftMargin=30,
            topMargin=32,
            bottomMargin=45
        )
        styles = getSampleStyleSheet()
        elements = []

        # Header Title
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=18,
            textColor=colors.HexColor('#FF6B00'),
            spaceAfter=4
        )
        sub_style = ParagraphStyle(
            'SubStyle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor('#64748B'),
            spaceAfter=14
        )
        section_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=11,
            textColor=colors.HexColor('#1E293B'),
            spaceBefore=10,
            spaceAfter=6
        )
        note_cell_style = ParagraphStyle(
            'NoteCellStyle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor('#334155')
        )
        footer_style = ParagraphStyle(
            'FooterStyle',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor('#94A3B8'),
            spaceBefore=14
        )

        elements.append(Paragraph("<b>TataDana</b> — Laporan Keuangan Pribadi", title_style))
        filter_str = f" | {', '.join(filter_descs)}" if filter_descs else ""
        period_str = f"{start_date or 'Awal'} s/d {end_date or 'Sekarang'}"
        elements.append(Paragraph(
            f"Pemilik Akun: <b>{user_name}</b> | Periode: <b>{period_str}</b>{filter_str} | Waktu Ekspor: {format_wib_display()}",
            sub_style
        ))

        # Calculate Totals & Savings Rate
        total_income = sum(float(r["amount"]) for r in rows if r["type"] == "income")
        total_expense = sum(float(r["amount"]) for r in rows if r["type"] == "expense")
        net = total_income - total_expense
        savings_rate = ((net / total_income) * 100.0) if total_income > 0 and net > 0 else 0.0

        # Summary Box Table
        summary_data = [
            ["Total Pemasukan", "Total Pengeluaran", "Arus Kas Bersih (Net)", "Tingkat Tabungan"],
            [f"Rp {total_income:,.0f}", f"Rp {total_expense:,.0f}", f"Rp {net:,.0f}", f"{savings_rate:.1f}%"]
        ]
        summary_table = Table(summary_data, colWidths=[133, 134, 134, 134])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FFF7ED')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#9A3412')),
            ('TEXTCOLOR', (0, 1), (0, 1), colors.HexColor('#059669')),
            ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#DC2626')),
            ('TEXTCOLOR', (2, 1), (2, 1), colors.HexColor('#2563EB') if net >= 0 else colors.HexColor('#DC2626')),
            ('TEXTCOLOR', (3, 1), (3, 1), colors.HexColor('#7C3AED')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8.5),
            ('FONTSIZE', (0, 1), (-1, 1), 11),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#FDBA74')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#FED7AA')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(summary_table)

        # Category Breakdown (if expenses exist)
        category_totals = {}
        for r in rows:
            if r["type"] == "expense":
                cname = r["category_name"] or "Lain-lain"
                category_totals[cname] = category_totals.get(cname, 0.0) + float(r["amount"])

        if category_totals and total_expense > 0:
            elements.append(Paragraph("Distribusi Pengeluaran per Kategori", section_style))
            cat_rows = [["Kategori", "Total Pengeluaran (IDR)", "Persentase (%)"]]
            sorted_cats = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)[:5]
            for cname, camount in sorted_cats:
                pct = (camount / total_expense) * 100.0
                cat_rows.append([cname, f"Rp {camount:,.0f}", f"{pct:.1f}%"])

            cat_table = Table(cat_rows, colWidths=[235, 170, 130])
            cat_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#334155')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
                ('TOPPADDING', (0, 0), (-1, -1), 3.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
            ]))
            elements.append(cat_table)

        # Transactions Detail Table
        elements.append(Paragraph("Rincian Riwayat Transaksi", section_style))
        table_data = [["No", "Tanggal (WIB)", "Jenis", "Kategori", "Dompet", "Nominal (IDR)", "Catatan"]]
        
        if not rows:
            table_data.append(["-", "-", "-", "Tidak ada transaksi pada filter ini", "-", "Rp 0", "-"] * 1)
        else:
            for idx, r in enumerate(rows, 1):
                t_type = "Pemasukan" if r["type"] == "income" else ("Pengeluaran" if r["type"] == "expense" else "Transfer")
                clean_note = (r["note"] or "-").strip()
                note_p = Paragraph(clean_note, note_cell_style)
                table_data.append([
                    str(idx),
                    r["transaction_date"][:16],
                    t_type,
                    r["category_name"] or "-",
                    r["wallet_name"] or "-",
                    f"Rp {float(r['amount']):,.0f}",
                    note_p
                ])

        tx_table = Table(table_data, colWidths=[24, 76, 60, 95, 80, 85, 115], repeatRows=1)
        tx_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF6B00')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (4, -1), 'LEFT'),
            ('ALIGN', (5, 0), (5, -1), 'RIGHT'),
            ('ALIGN', (6, 0), (6, -1), 'LEFT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
            ('TOPPADDING', (0, 0), (-1, -1), 3.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')])
        ]))
        elements.append(tx_table)

        elements.append(Paragraph(
            "Dokumen ini sah dihasilkan secara elektronik oleh sistem TataDana dan berlaku sebagai arsip rekapitulasi keuangan pribadi pengguna.",
            footer_style
        ))

        doc.build(elements, canvasmaker=NumberedCanvas)

        # Save to Export History
        now_wib = get_wib_str()
        cursor.execute("""
        INSERT INTO export_history (id, user_id, file_name, file_type, file_path, storage_url, period_start, period_end, download_count, created_at)
        VALUES (?, ?, ?, 'pdf', ?, ?, ?, ?, 0, ?)
        """, (str(uuid.uuid4()), user_id, file_id, file_path, f"/api/reports/download/{file_id}", start_date, end_date, now_wib))
        conn.commit()
        conn.close()

        return file_id

    @staticmethod
    def get_export_history(user_id: str) -> List[Dict[str, Any]]:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, file_name, file_type, storage_url, period_start, period_end, download_count, created_at
        FROM export_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
