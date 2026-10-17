import unittest
import uuid
import sqlite3
from app.database import get_db, init_db
from app.services.transaction_service import TransactionService
from app.config import get_wib_str

class TestWalletOwnershipSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        # Create 2 isolated test users
        self.user1_id = f"user1_{uuid.uuid4().hex[:8]}"
        self.user2_id = f"user2_{uuid.uuid4().hex[:8]}"

        conn = get_db()
        cursor = conn.cursor()

        # Seed profiles
        now = get_wib_str()
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, ?, ?, 'starter', 'user', ?)",
                       (self.user1_id, f"{self.user1_id}@test.com", "hash", "User 1", now))
        cursor.execute("INSERT INTO profiles (id, email, password_hash, full_name, plan, role, created_at) VALUES (?, ?, ?, ?, 'starter', 'user', ?)",
                       (self.user2_id, f"{self.user2_id}@test.com", "hash", "User 2", now))

        # User 1 Wallets & Category
        self.u1_wallet_cash = f"w1_{uuid.uuid4().hex[:8]}"
        self.u1_wallet_bank = f"w1b_{uuid.uuid4().hex[:8]}"
        self.u1_category = f"cat1_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, created_at) VALUES (?, ?, 'Cash U1', 'cash', 100000.0, ?)",
                       (self.u1_wallet_cash, self.user1_id, now))
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, created_at) VALUES (?, ?, 'BCA U1', 'bank', 500000.0, ?)",
                       (self.u1_wallet_bank, self.user1_id, now))
        cursor.execute("INSERT INTO categories (id, user_id, name, type, created_at) VALUES (?, ?, 'Makan U1', 'expense', ?)",
                       (self.u1_category, self.user1_id, now))

        # User 2 Wallets & Category
        self.u2_wallet_cash = f"w2_{uuid.uuid4().hex[:8]}"
        self.u2_category = f"cat2_{uuid.uuid4().hex[:8]}"
        cursor.execute("INSERT INTO wallets (id, user_id, name, type, balance, created_at) VALUES (?, ?, 'Cash U2', 'cash', 200000.0, ?)",
                       (self.u2_wallet_cash, self.user2_id, now))
        cursor.execute("INSERT INTO categories (id, user_id, name, type, created_at) VALUES (?, ?, 'Hobi U2', 'expense', ?)",
                       (self.u2_category, self.user2_id, now))

        conn.commit()
        conn.close()

    def test_user_cannot_create_transaction_with_other_user_wallet(self):
        """Memastikan User 1 tidak bisa membuat transaksi menggunakan wallet milik User 2"""
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u2_wallet_cash, # Milik User 2!
                tx_type="expense",
                amount=25000.0,
                note="Mencoba membobol dompet user 2"
            )
        self.assertIn("bukan milik Anda", str(ctx.exception))

    def test_user_cannot_transfer_to_other_user_wallet(self):
        """Memastikan transfer tidak bisa ditargetkan ke dompet pengguna lain"""
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_wallet_cash,
                target_wallet_id=self.u2_wallet_cash, # Milik User 2!
                tx_type="transfer",
                amount=50000.0,
                note="Mencoba transfer ke user lain secara ilegal"
            )
        self.assertIn("bukan milik Anda", str(ctx.exception))

    def test_user_cannot_transfer_to_same_wallet(self):
        """Memastikan dompet asal dan dompet tujuan transfer tidak boleh sama"""
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_wallet_cash,
                target_wallet_id=self.u1_wallet_cash, # Sama dengan dompet asal!
                tx_type="transfer",
                amount=10000.0,
                note="Transfer ke diri sendiri"
            )
        self.assertIn("tidak boleh sama", str(ctx.exception))

    def test_user_cannot_use_other_user_category(self):
        """Memastikan User 1 tidak bisa memakai kategori belanja milik User 2"""
        with self.assertRaises(ValueError) as ctx:
            TransactionService.create_transaction(
                user_id=self.user1_id,
                wallet_id=self.u1_wallet_cash,
                tx_type="expense",
                amount=15000.0,
                category_id=self.u2_category, # Milik User 2!
                note="Mencoba pakai kategori user 2"
            )
        self.assertIn("Kategori tidak ditemukan atau bukan milik Anda", str(ctx.exception))

    def test_user_cannot_update_transaction_to_other_wallet(self):
        """Memastikan update transaksi tidak bisa mengubah dompet menjadi milik user lain"""
        # Buat transaksi sah oleh User 1
        tx = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_wallet_cash,
            tx_type="expense",
            amount=20000.0,
            category_id=self.u1_category,
            note="Transaksi sah"
        )
        tx_id = tx["id"]

        # User 1 mencoba update transaksi agar memotong dompet User 2
        with self.assertRaises(ValueError) as ctx:
            TransactionService.update_transaction(
                tx_id=tx_id,
                user_id=self.user1_id,
                wallet_id=self.u2_wallet_cash # Dompet User 2!
            )
        self.assertIn("Dompet asal tidak ditemukan atau bukan milik Anda", str(ctx.exception))

    def test_user_cannot_update_other_user_transaction(self):
        """Memastikan User 2 tidak bisa mengedit transaksi milik User 1"""
        tx = TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_wallet_cash,
            tx_type="expense",
            amount=10000.0,
            note="Milik User 1"
        )
        tx_id = tx["id"]

        with self.assertRaises(ValueError) as ctx:
            TransactionService.update_transaction(
                tx_id=tx_id,
                user_id=self.user2_id, # User 2 mencoba edit!
                amount=99999.0
            )
        self.assertIn("Transaksi tidak ditemukan atau bukan milik Anda", str(ctx.exception))

    def test_legitimate_transactions_and_balances(self):
        """Memastikan transaksi legal antar dompet sendiri berjalan dengan kalkulasi saldo yang akurat"""
        # 1. Pemasukan ke BCA U1 Rp 100.000 (Awal 500.000 -> Menjadi 600.000)
        TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_wallet_bank,
            tx_type="income",
            amount=100000.0,
            note="Gaji freelance"
        )

        # 2. Transfer dari BCA U1 ke Cash U1 Rp 50.000
        # BCA U1: 600.000 - 50.000 = 550.000
        # Cash U1: 100.000 + 50.000 = 150.000
        TransactionService.create_transaction(
            user_id=self.user1_id,
            wallet_id=self.u1_wallet_bank,
            target_wallet_id=self.u1_wallet_cash,
            tx_type="transfer",
            amount=50000.0,
            note="Tarik tunai"
        )

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_wallet_bank,))
        bca_balance = cursor.fetchone()[0]
        cursor.execute("SELECT balance FROM wallets WHERE id = ?", (self.u1_wallet_cash,))
        cash_balance = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(bca_balance, 550000.0)
        self.assertEqual(cash_balance, 150000.0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
