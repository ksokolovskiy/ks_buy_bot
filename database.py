"""Database module for managing shopping list items using SQLite."""
import sqlite3
import os
import uuid
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager


class Database:
    """Lightweight SQLite database for shopping list management."""
    
    def __init__(self, db_path: str):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        # Ensure data directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database schema and seed initial data."""
        with self._get_connection() as conn:
            # Groups table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invite_code TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # User to Group mapping
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_groups (
                    user_id INTEGER PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES groups(id)
                )
            """)

            # Categories table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    group_id INTEGER,
                    UNIQUE(group_id, name)
                )
            """)
            
            # Items table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    department TEXT NOT NULL,
                    is_bought INTEGER DEFAULT 0,
                    group_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Migrations
            self._migrate(conn)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_group_id ON items(group_id)
            """)

    def _migrate(self, conn):
        """Migrate legacy data to group-based system."""
        # 1. Add group_id column to categories if not exists
        cursor = conn.execute("PRAGMA table_info(categories)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "group_id" not in columns:
            conn.execute("ALTER TABLE categories ADD COLUMN group_id INTEGER")
            # We also need to remove the UNIQUE(user_id, name) constraint and add UNIQUE(group_id, name)
            # In SQLite this is hard, but for now we'll just live with both or ignore name conflicts if they happen.
        
        # 2. Add group_id column to items if not exists
        cursor = conn.execute("PRAGMA table_info(items)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "group_id" not in columns:
            conn.execute("ALTER TABLE items ADD COLUMN group_id INTEGER")

        # 3. Create groups for existing users who don't have one
        # Find all unique user_ids from all tables
        cursor = conn.execute("""
            SELECT user_id FROM items 
            UNION SELECT user_id FROM categories 
            UNION SELECT user_id FROM user_groups
        """)
        user_ids = [row["user_id"] for row in cursor.fetchall()]
        
        for user_id in user_ids:
            # Check if user has a group
            cursor = conn.execute("SELECT group_id FROM user_groups WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if not row:
                # Create a group for this user
                import uuid
                invite_code = str(uuid.uuid4())[:8].upper()
                cursor = conn.execute("INSERT INTO groups (invite_code) VALUES (?)", (invite_code,))
                group_id = cursor.lastrowid
                conn.execute("INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)", (user_id, group_id))
            else:
                group_id = row["group_id"]
            
            # Update their items and categories
            conn.execute("UPDATE items SET group_id = ? WHERE user_id = ? AND group_id IS NULL", (group_id, user_id))
            conn.execute("UPDATE categories SET group_id = ? WHERE user_id = ? AND group_id IS NULL", (group_id, user_id))
            
    def _get_user_group(self, user_id: int) -> int:
        """Get the group_id for a user, creating a personal group if none exists."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT group_id FROM user_groups WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return row["group_id"]
            
            # Create a personal group if none exists
            invite_code = str(uuid.uuid4())[:8].upper()
            cursor = conn.execute("INSERT INTO groups (invite_code) VALUES (?)", (invite_code,))
            group_id = cursor.lastrowid
            conn.execute("INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)", (user_id, group_id))
            return group_id

    def get_invite_code(self, user_id: int) -> str:
        """Get the invite code for the user's current group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT invite_code FROM groups WHERE id = ?", (group_id,))
            row = cursor.fetchone()
            return row["invite_code"] if row else ""

    def join_group(self, user_id: int, invite_code: str) -> Tuple[bool, str]:
        """Join a group by invite code.
        
        Returns:
            Tuple of (success, message)
        """
        invite_code = invite_code.strip().upper()
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT id FROM groups WHERE invite_code = ?", (invite_code,))
            row = cursor.fetchone()
            if not row:
                return False, "Неверный код приглашения."
            
            new_group_id = row["id"]
            
            # Check if user is already in this group
            cursor = conn.execute("SELECT group_id FROM user_groups WHERE user_id = ?", (user_id,))
            current_row = cursor.fetchone()
            if current_row and current_row["group_id"] == new_group_id:
                return True, "Вы уже в этой группе."

            # Update or insert user's group
            if current_row:
                conn.execute("UPDATE user_groups SET group_id = ? WHERE user_id = ?", (new_group_id, user_id))
            else:
                conn.execute("INSERT INTO user_groups (user_id, group_id) VALUES (?, ?)", (user_id, new_group_id))
            
            return True, "Вы успешно присоединились к группе!"

    def seed_data(self, user_id: int):
        """Seed initial categories and items for the user's group."""
        group_id = self._get_user_group(user_id)
        
        initial_categories = [
            "🧹 Быт и уборка",
            "🧴 Гигиена и уход",
            "🍳 Дом и кухня",
            "🥦 Овощи и зелень",
            "🍎 Фрукты и ягоды",
            "🥩 Мясо, рыба и птица",
            "🥛 Молочные продукты и яйца",
            "🍝 Бакалея",
            "🥫 Консервы и готовые продукты",
            "🍬 Сладости и снеки",
            "🍷 Напитки и алкоголь",
            "🍼 Детские товары"
        ]
        
        with self._get_connection() as conn:
            # Add categories
            for cat in initial_categories:
                conn.execute(
                    "INSERT OR IGNORE INTO categories (user_id, group_id, name) VALUES (?, ?, ?)",
                    (user_id, group_id, cat)
                )
            
            # Check if items already exist for this group to avoid double seeding
            cursor = conn.execute("SELECT COUNT(*) as count FROM items WHERE group_id = ?", (group_id,))
            if cursor.fetchone()["count"] > 0:
                return

            # Pre-populate items
            items_to_seed = [
                # Быт и уборка
                ("Пакеты для мусора", "🧹 Быт и уборка"), ("Жидкость для посудомойки", "🧹 Быт и уборка"),
                ("Таблетки для посудомойки", "🧹 Быт и уборка"), ("Хлорка", "🧹 Быт и уборка"),
                ("Максима для стирки", "🧹 Быт и уборка"), ("Батарейки", "🧹 Быт и уборка"),
                
                # Гигиена и уход
                ("Мыло для рук", "🧴 Гигиена и уход"), ("Зубная паста", "🧴 Гигиена и уход"),
                ("Влажные салфетки", "🧴 Гигиена и уход"), ("Ёршики для унитаза", "🧴 Гигиена и уход"),
                ("Репеллент", "🧴 Гигиена и уход"), ("Прокладки", "🧴 Гигиена и уход"),
                ("Шампунь", "🧴 Гигиена и уход"), ("Зубные щётки", "🧴 Гигиена и уход"),
                ("Дезодорант", "🧴 Гигиена и уход"), ("Жидкое мыло", "🧴 Гигиена и уход"),
                ("Туалетная бумага", "🧴 Гигиена и уход"), ("Бумажные полотенца", "🧴 Гигиена и уход"),
                ("Детская нить для зубов", "🧴 Гигиена и уход"),
                
                # Дом и кухня
                ("Прихватки", "🍳 Дом и кухня"), ("Сидушка для унитаза", "🍳 Дом и кухня"),
                ("Контейнеры для хранения", "🍳 Дом и кухня"), ("Фольга", "🍳 Дом и кухня"),
                ("Дуршлаг", "🍳 Дом и кухня"), ("Силикон формы для запекания", "🍳 Дом и кухня"),
                ("Бутылка для воды", "🍳 Дом и кухня"),
                
                # Овощи и зелень
                ("Помидоры", "🥦 Овощи и зелень"), ("Картошка", "🥦 Овощи и зелень"),
                ("Болгарский перец", "🥦 Овощи и зелень"), ("Огурцы свежие", "🥦 Овощи и зелень"),
                ("Морковь", "🥦 Овощи и зелень"), ("Лук", "🥦 Овощи и зелень"),
                ("Кукуруза", "🥦 Овощи и зелень"), ("Батат", "🥦 Овощи и зелень"),
                ("Чеснок", "🥦 Овощи и зелень"), ("Баклажан", "🥦 Овощи и зелень"),
                ("Свекла", "🥦 Овощи и зелень"), ("Брокколи", "🥦 Овощи и зелень"),
                ("Руккола", "🥦 Овощи и зелень"), ("Авокадо", "🥦 Овощи и зелень"),
                ("Кабачки", "🥦 Овощи и зелень"), ("Тыква", "🥦 Овощи и зелень"),
                ("Капуста", "🥦 Овощи и зелень"), ("Шампиньоны", "🥦 Овощи и зелень"),
                
                # Фрукты и ягоды
                ("Бананы", "🍎 Фрукты и ягоды"), ("Яблоки", "🍎 Фрукты и ягоды"),
                ("Арбуз", "🍎 Фрукты и ягоды"), ("Груша", "🍎 Фрукты и ягоды"),
                ("Нектарины", "🍎 Фрукты и ягоды"), ("Дыня", "🍎 Фрукты и ягоды"),
                ("Виноград", "🍎 Фрукты и ягоды"), ("Чернослив", "🍎 Фрукты и ягоды"),
                ("Ягоды / заморозка", "🍎 Фрукты и ягоды"), ("Хурма", "🍎 Фрукты и ягоды"),
                ("Апельсин", "🍎 Фрукты и ягоды"),
                
                # Напитки и алкоголь
                ("Вода", "🍷 Напитки и алкоголь"), ("Вино", "🍷 Напитки и алкоголь"),
                ("Сок", "🍷 Напитки и алкоголь"), ("Лёд", "🍷 Напитки и алкоголь"),
                ("Пиво", "🍷 Напитки и алкоголь"), ("Коньяк", "🍷 Напитки и алкоголь"),
                ("Кофе", "🍷 Напитки и алкоголь"), ("Чай", "🍷 Напитки и алкоголь"),
                ("Какао", "🍷 Напитки и алкоголь"),
                
                # Детские товары
                ("Пюре", "🍼 Детские товары"), ("Памперсы", "🍼 Детские товары"),
                ("Памперсы трусики", "🍼 Детские товары"),
                
                # Сладости и снеки
                ("Бамба", "🍬 Сладости и снеки"), ("Маршмэллоу", "🍬 Сладости и снеки"),
                ("Сахар", "🍬 Сладости и снеки"), ("Темный шоколад", "🍬 Сладости и снеки"),
                ("Курага", "🍬 Сладости и снеки"), ("Тыквенные семечки", "🍬 Сладости и снеки"),
                ("К чаю", "🍬 Сладости и снеки"), ("Ванильный сахар", "🍬 Сладости и снеки"),
                
                # Бакалея
                ("Паста", "🍝 Бакалея"), ("Гречка", "🍝 Бакалея"), ("Манка", "🍝 Бакалея"),
                ("Соль", "🍝 Бакалея"), ("Мука", "🍝 Бакалея"), ("Овсянка", "🍝 Бакалея"),
                ("Лимонный сок", "🍝 Бакалея"), ("Оливковое масло", "🍝 Бакалея"),
                ("Рис", "🍝 Бакалея"), ("Киноа", "🍝 Бакалея"), ("Булгур", "🍝 Бакалея"),
                ("Бурый рис", "🍝 Бакалея"), ("Пшено", "🍝 Бакалея"), ("Хумус", "🍝 Бакалея"),
                ("Паста для пиццы", "🍝 Бакалея"), ("Чечевица", "🍝 Бакалея"), ("Хлеб", "🍝 Бакалея"),
                
                # Консервы и готовые продукты
                ("Соленые огурцы", "🥫 Консервы и готовые продукты"),
                ("Консервированная кукуруза", "🥫 Консервы и готовые продукты"),
                ("Мак (сушеный)", "🥫 Консервы и готовые продукты"),
                ("Консерв белая фасоль", "🥫 Консервы и готовые продукты"),
                ("Корица молотая", "🥫 Консервы и готовые продукты"),
                ("Сардины в банке", "🥫 Консервы и готовые продукты"),
                ("Оливки", "🥫 Консервы и готовые продукты"),
                
                # Молочные продукты и яйца
                ("Яйца", "🥛 Молочные продукты и яйца"), ("Молоко", "🥛 Молочные продукты и яйца"),
                ("Сливочное масло", "🥛 Молочные продукты и яйца"), ("Йогурт", "🥛 Молочные продукты и яйца"),
                ("Сыр", "🥛 Молочные продукты и яйца"), ("Сыр фета", "🥛 Молочные продукты и яйца"),
                ("Творог", "🥛 Молочные продукты и яйца"), ("Кефир", "🥛 Молочные продукты и яйца"),
                ("Моцарелла", "🥛 Молочные продукты и яйца"), ("Сливки", "🥛 Молочные продукты и яйца"),
                
                # Мясо, рыба и птица
                ("Мясо", "🥩 Мясо, рыба и птица"), ("Курица", "🥩 Мясо, рыба и птица"),
                ("Рыба", "🥩 Мясо, рыба и птица"), ("Ветчина", "🥩 Мясо, рыба и птица"),
                ("Колбаса", "🥩 Мясо, рыба и птица"), ("Печень", "🥩 Мясо, рыба и птица"),
                ("Индейка", "🥩 Мясо, рыба и птица"), ("Фарш говяжий", "🥩 Мясо, рыба и птица"),
                ("Сосиски", "🥩 Мясо, рыба и птица")
            ]
            
            for name, dept in items_to_seed:
                conn.execute(
                    "INSERT INTO items (user_id, group_id, name, department, is_bought) VALUES (?, ?, ?, ?, 0)",
                    (user_id, group_id, name, dept)
                )

    def get_categories(self, user_id: int) -> List[str]:
        """Get all categories for a user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM categories WHERE group_id = ? ORDER BY id",
                (group_id,)
            )
            return [row["name"] for row in cursor.fetchall()]

    def get_categories_with_items(self, user_id: int, include_bought: bool = False) -> List[str]:
        """Get categories that have items in the user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            query = """
                SELECT DISTINCT c.name 
                FROM categories c
                INNER JOIN items i ON c.name = i.department AND c.group_id = i.group_id
                WHERE c.group_id = ?
            """
            params = [group_id]
            
            if not include_bought:
                query += " AND i.is_bought = 0"
            
            query += " ORDER BY c.id"
            
            cursor = conn.execute(query, params)
            return [row["name"] for row in cursor.fetchall()]

    def add_category(self, user_id: int, name: str) -> bool:
        """Add a new category to user's group."""
        group_id = self._get_user_group(user_id)
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO categories (user_id, group_id, name) VALUES (?, ?, ?)",
                    (user_id, group_id, name)
                )
                return True
        except sqlite3.IntegrityError:
            return False

    def delete_category(self, user_id: int, name: str) -> Tuple[bool, int]:
        """Delete a category and all its items from user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            # First, delete all items in this category
            cursor = conn.execute(
                "DELETE FROM items WHERE group_id = ? AND department = ?",
                (group_id, name)
            )
            items_deleted = cursor.rowcount
            
            # Then delete the category
            cursor = conn.execute(
                "DELETE FROM categories WHERE group_id = ? AND name = ?",
                (group_id, name)
            )
            return (cursor.rowcount > 0, items_deleted)
    
    def rename_category(self, user_id: int, old_name: str, new_name: str) -> bool:
        """Rename a category in user's group."""
        group_id = self._get_user_group(user_id)
        try:
            with self._get_connection() as conn:
                # Update category name
                conn.execute(
                    "UPDATE categories SET name = ? WHERE group_id = ? AND name = ?",
                    (new_name, group_id, old_name)
                )
                
                # Update all items in this category
                conn.execute(
                    "UPDATE items SET department = ? WHERE group_id = ? AND department = ?",
                    (new_name, group_id, old_name)
                )
                return True
        except sqlite3.IntegrityError:
            return False
    
    def get_items(self, user_id: int, include_bought: bool = False) -> List[Dict]:
        """Get all items for a user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            query = "SELECT * FROM items WHERE group_id = ?"
            params = [group_id]
            
            if not include_bought:
                query += " AND is_bought = 0"
            
            query += " ORDER BY name COLLATE NOCASE"
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def add_item(self, user_id: int, name: str, department: str) -> bool:
        """Add a new item to the user's group shopping list."""
        group_id = self._get_user_group(user_id)
        try:
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT INTO items (user_id, group_id, name, department, is_bought) VALUES (?, ?, ?, ?, 0)",
                    (user_id, group_id, name, department)
                )
                return True
        except Exception:
            return False
    
    def toggle_bought(self, item_id: int, user_id: int) -> bool:
        """Toggle the bought status of an item in user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT is_bought FROM items WHERE id = ? AND group_id = ?",
                (item_id, group_id)
            )
            row = cursor.fetchone()
            if not row:
                return False
            
            new_status = 0 if row["is_bought"] else 1
            conn.execute(
                "UPDATE items SET is_bought = ? WHERE id = ? AND group_id = ?",
                (new_status, item_id, group_id)
            )
            return bool(new_status)
    
    def delete_item(self, item_id: int, user_id: int) -> bool:
        """Delete an item from user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM items WHERE id = ? AND group_id = ?",
                (item_id, group_id)
            )
            return cursor.rowcount > 0
    
    def clear_bought_items(self, user_id: int) -> int:
        """Delete all bought items for a user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM items WHERE group_id = ? AND is_bought = 1",
                (group_id,)
            )
            return cursor.rowcount
    
    def update_item_name(self, item_id: int, user_id: int, name: str) -> bool:
        """Update an item's name in user's group."""
        group_id = self._get_user_group(user_id)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE items SET name = ? WHERE id = ? AND group_id = ?",
                (name, item_id, group_id)
            )
            return cursor.rowcount > 0
