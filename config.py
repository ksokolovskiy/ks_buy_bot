"""Configuration module for the shopping list bot."""
import os
from typing import List

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Parse allowed users from string "id1,id2,id3"
ALLOWED_USERS = [int(user_id.strip()) for user_id in os.getenv("ALLOWED_USERS", "").split(",") if user_id.strip()]

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "data/shopping_list.db")

# Button labels
BUTTON_ADD_ITEM = "➕ Добавить"
BUTTON_SHOW_LIST = "📋 Список"
BUTTON_TOGGLE_BOUGHT = "👁 Показать/Скрыть"
BUTTON_MANAGE_CATS = "⚙️ Категории"
BUTTON_CANCEL = "❌ Отмена"

# Messages
MSG_WELCOME = """
Привет! 👋

Это бот для управления списком покупок.

Используй кнопки ниже для управления списком:
• Добавить товар
• Показать список покупок
• Показать/скрыть купленные товары
• Удалить все купленные товары
"""

MSG_ACCESS_DENIED = "⛔️ У вас нет доступа к этому боту."
MSG_CHOOSE_DEPARTMENT = "Выберите отдел для товара:"
MSG_ENTER_ITEM_NAME = "Введите название товара:"
MSG_ITEM_ADDED = "✅ Товар добавлен в список!"
MSG_LIST_EMPTY = "📭 Список покупок пуст."
MSG_BOUGHT_CLEARED = "🗑 Все купленные товары удалены."
MSG_NO_BOUGHT_ITEMS = "Нет купленных товаров для удаления."

# Category management messages
MSG_CATEGORY_MENU = "⚙️ *Управление категориями*\n\nВыберите действие:"
MSG_CHOOSE_CATEGORY_TO_DELETE = "Выберите категорию для удаления:"
MSG_CHOOSE_CATEGORY_TO_RENAME = "Выберите категорию для переименования:"
MSG_ENTER_NEW_CATEGORY_NAME = "Введите новое название категории:"
MSG_CATEGORY_DELETED = "✅ Категория удалена вместе с {} товарами."
MSG_CATEGORY_RENAMED = "✅ Категория переименована."
MSG_CATEGORY_EXISTS = "❌ Категория с таким названием уже существует."
MSG_CONFIRM_DELETE_CATEGORY = "⚠️ Удалить категорию *{}*?\n\nВ ней {} товаров. Все товары будут удалены!"
