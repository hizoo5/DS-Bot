import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional

class AccountDatabase:
    """SQLite database for multi-user account management"""
    
    def __init__(self, db_path: str = "accounts.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Users table - with whitelist
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                is_authorized INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        
        # Accounts table - per user
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone_number TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                mode TEXT NOT NULL,
                proxy TEXT,
                created_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, phone_number)
            )
        ''')
        
        # Recovery data table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recovery_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                recovery_code TEXT,
                created_at TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        ''')
        
        conn.commit()
        conn.close()
        print("[✓] Database initialized successfully")
    
    def add_user(self, user_id: int, username: str, is_authorized: bool = False) -> bool:
        """Add a new user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, is_authorized, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, 1 if is_authorized else 0, now, now))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to add user: {str(e)}")
            return False
    
    def is_user_authorized(self, user_id: int) -> bool:
        """Check if user is authorized (whitelisted)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT is_authorized FROM users WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            conn.close()
            
            return result and result[0] == 1 if result else False
        except Exception as e:
            print(f"[ERROR] Failed to check authorization: {str(e)}")
            return False
    
    def authorize_user(self, user_id: int) -> bool:
        """Authorize a user (add to whitelist)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE users SET is_authorized = 1, updated_at = ?
                WHERE user_id = ?
            ''', (datetime.now().isoformat(), user_id))
            
            conn.commit()
            conn.close()
            print(f"[✓] User {user_id} authorized")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to authorize user: {str(e)}")
            return False
    
    def save_account(self, user_id: int, phone: str, username: str, password: str, 
                     mode: str, proxy: str = None) -> bool:
        """Save generated account to database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Ensure user exists
            self.add_user(user_id, f"user_{user_id}")
            
            cursor.execute('''
                INSERT INTO accounts (user_id, phone_number, username, password, mode, proxy, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, phone, username, password, mode, proxy, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            print(f"[✓] Account saved for user {user_id}: {username}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to save account: {str(e)}")
            return False
    
    def get_user_accounts(self, user_id: int, mode: str = None) -> List[Dict]:
        """Get all accounts for a user, optionally filtered by mode"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if mode:
                cursor.execute('''
                    SELECT id, phone_number, username, password, mode, created_at
                    FROM accounts
                    WHERE user_id = ? AND mode = ?
                    ORDER BY created_at DESC
                ''', (user_id, mode))
            else:
                cursor.execute('''
                    SELECT id, phone_number, username, password, mode, created_at
                    FROM accounts
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                ''', (user_id,))
            
            results = cursor.fetchall()
            conn.close()
            
            accounts = []
            for row in results:
                accounts.append({
                    'id': row[0],
                    'phone': row[1],
                    'username': row[2],
                    'password': row[3],
                    'mode': row[4],
                    'created_at': row[5]
                })
            
            return accounts
        except Exception as e:
            print(f"[ERROR] Failed to retrieve accounts: {str(e)}")
            return []
    
    def get_user_main_accounts(self, user_id: int, limit: int = None) -> List[Dict]:
        """Get MAIN accounts for a user"""
        accounts = self.get_user_accounts(user_id, mode="MAIN")
        if limit:
            accounts = accounts[:limit]
        return accounts
    
    def get_account_detail(self, user_id: int, account_id: int) -> Optional[Dict]:
        """Get detailed info about specific account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, phone_number, username, password, mode, created_at
                FROM accounts
                WHERE id = ? AND user_id = ?
            ''', (account_id, user_id))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    'id': result[0],
                    'phone': result[1],
                    'username': result[2],
                    'password': result[3],
                    'mode': result[4],
                    'created_at': result[5]
                }
            return None
        except Exception as e:
            print(f"[ERROR] Failed to get account detail: {str(e)}")
            return None
    
    def get_user_account_count(self, user_id: int) -> Dict:
        """Get account count breakdown for user"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM accounts WHERE user_id = ?', (user_id,))
            total = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM accounts WHERE user_id = ? AND mode = ?', (user_id, "MAIN"))
            main_count = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM accounts WHERE user_id = ? AND mode = ?', (user_id, "DUMMY"))
            dummy_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'total': total,
                'main': main_count,
                'dummy': dummy_count
            }
        except Exception as e:
            print(f"[ERROR] Failed to get account count: {str(e)}")
            return {'total': 0, 'main': 0, 'dummy': 0}
    
    def delete_account(self, user_id: int, account_id: int) -> bool:
        """Delete an account"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Also delete recovery data
            cursor.execute('DELETE FROM recovery_data WHERE account_id = ?', (account_id,))
            cursor.execute('DELETE FROM accounts WHERE id = ? AND user_id = ?', (account_id, user_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to delete account: {str(e)}")
            return False
