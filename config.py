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
BUTTON_SHOW_BOUGHT = "👁 Показать"
BUTTON_HIDE_BOUGHT = "🛡 Скрыть"
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
