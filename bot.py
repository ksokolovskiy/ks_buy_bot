"""Main Telegram bot implementation."""
from dotenv import load_dotenv
load_dotenv() # Load environment variables FIRST

import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
import config
from database import Database


# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Disable httpx logging to reduce noise
logging.getLogger('httpx').setLevel(logging.WARNING)

# Conversation states
CHOOSING_DEPARTMENT, ENTERING_NAME = range(2)

# Initialize database
db = Database(config.DATABASE_URL)


async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is allowed to use the bot."""
    user_id = update.effective_user.id
    logger.info(f"Checking access for user {user_id}. Allowed: {config.ALLOWED_USERS}")
    if user_id not in config.ALLOWED_USERS:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        await update.effective_message.reply_text(config.MSG_ACCESS_DENIED)
        return False
    return True


async def global_trace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log every incoming update for debugging."""
    if update.message:
        logger.info(f"TRACE: Message from {update.effective_user.id}: {update.message.text}")
    elif update.callback_query:
        logger.info(f"TRACE: Callback from {update.effective_user.id}: {update.callback_query.data}")
    else:
        logger.info(f"TRACE: Unknown update type from {update.effective_user.id}")

def get_main_keyboard(context: ContextTypes.DEFAULT_TYPE = None):
    """Get the main menu keyboard."""
    keyboard = [
        [
            KeyboardButton(config.BUTTON_ADD_ITEM),
            KeyboardButton(config.BUTTON_SHOW_LIST),
            KeyboardButton(config.BUTTON_TOGGLE_BOUGHT)
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    logger.info(f"Start command from {update.effective_user.id}")
    if not await check_access(update, context):
        return
    
    # Seed data for the user on first start
    db.seed_data(update.effective_user.id)
    
    msg = await update.message.reply_text(
        config.MSG_WELCOME,
        reply_markup=get_main_keyboard(context)
    )
    # CRITICAL: Save keyboard message ID to prevent deletion
    context.user_data["keyboard_msg_id"] = msg.message_id


async def add_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the add item flow."""
    logger.info(f"Add item started by {update.effective_user.id}")
    if not await check_access(update, context):
        return ConversationHandler.END
    
    categories = db.get_categories(update.effective_user.id)
    if not categories:
        # Fallback if no categories exist
        db.seed_data(update.effective_user.id)
        categories = db.get_categories(update.effective_user.id)

    keyboard = []
    for i in range(0, len(categories), 2):
        row = [InlineKeyboardButton(categories[i], callback_data=f"dept_{i}")]
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(categories[i+1], callback_data=f"dept_{i+1}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(config.BUTTON_CANCEL, callback_data="cancel")])
    
    await update.message.reply_text(
        config.MSG_CHOOSE_DEPARTMENT,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_DEPARTMENT


async def department_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle department selection."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("Отменено.")
        return ConversationHandler.END
    
    dept_index = int(query.data.split("_")[1])
    categories = db.get_categories(update.effective_user.id)
    department = categories[dept_index]
    context.user_data["department"] = department
    
    await query.edit_message_text(
        f"Отдел: {department}\n\n{config.MSG_ENTER_ITEM_NAME}"
    )
    return ENTERING_NAME


async def item_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle item name entry."""
    item_name = update.message.text.strip()
    department = context.user_data.get("department")
    user_id = update.effective_user.id
    
    if item_name and department:
        db.add_item(user_id, item_name, department)
        await update.message.reply_text(config.MSG_ITEM_ADDED)
    
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current operation."""
    context.user_data.clear()
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE, category=None, force_new=False):
    """List shopping items. If category is None, show category selection."""
    if not await check_access(update, context):
        return
    
    user_id = update.effective_user.id
    show_bought = context.user_data.get("show_bought", False)
    edit_mode = context.user_data.get("edit_mode", False)
    
    # Store current view context
    context.user_data["last_category"] = category
    
    if category == "ALL":
        items = db.get_items(user_id, include_bought=show_bought)
        if not items:
            await send_or_edit(update, context, config.MSG_LIST_EMPTY, reply_markup=None, force_new=force_new)
            return

        grouped = {}
        for item in items:
            dept = item["department"]
            if dept not in grouped: grouped[dept] = []
            grouped[dept].append(item)
        
        message_text = "📋 *Весь список:*\n"
        if edit_mode: message_text += "⚠️ _Режим удаления_\n"
            
        # Navigation at TOP for long lists
        keyboard = [[InlineKeyboardButton("⬅️ Назад к категориям", callback_data="list_cats")]]
        mode_btn = InlineKeyboardButton("✅ Готово", callback_data="toggle_edit_all") if edit_mode else InlineKeyboardButton("⚙️ Удаление", callback_data="toggle_edit_all")
        keyboard.append([mode_btn])
        
        categories = db.get_categories(user_id)
        for dept in categories:
            if dept not in grouped: continue
            message_text += f"\n*{dept}*\n"
            for item in grouped[dept]:
                status = "✅" if item["is_bought"] else "⬜️"
                if edit_mode:
                    btn_text = f"🗑 Удалить: {item['name']}"
                    keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_{item['id']}_all")])
                else:
                    btn_text = f"{status} {item['name']}"
                    keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"tog_{item['id']}_all")])
        
        # Limit total buttons to 90 to stay safe (Telegram limit is ~100)
        if len(keyboard) > 90:
            keyboard = keyboard[:90]
            message_text += "\n\n⚠️ _Список слишком длинный, показаны первые товары._"
        
        # Bottom navigation too for convenience if not too many
        if len(keyboard) < 88:
            keyboard.append([mode_btn])
            keyboard.append([InlineKeyboardButton("⬅️ Назад к категориям", callback_data="list_cats")])

        await send_or_edit(update, context, message_text, reply_markup=InlineKeyboardMarkup(keyboard), force_new=force_new)
        return

    if category:
        items = [i for i in db.get_items(user_id, include_bought=show_bought) if i["department"] == category]
        if not items:
            await send_or_edit(update, context, f"В категории *{category}* пусто.", 
                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="list_cats")]]), force_new=force_new)
            return

        message_text = f"📂 *Категория:* {category}\n"
        if edit_mode: message_text += "⚠️ _Режим удаления_\n"
            
        # Navigation at TOP
        keyboard = [[InlineKeyboardButton("⬅️ Назад к категориям", callback_data="list_cats")]]
        for item in items:
            status = "✅" if item["is_bought"] else "⬜️"
            if edit_mode:
                btn_text = f"🗑 Удалить: {item['name']}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_{item['id']}_{category}")])
            else:
                btn_text = f"{status} {item['name']}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"tog_{item['id']}_{category}")])
        
        mode_btn = InlineKeyboardButton("✅ Готово", callback_data=f"toggle_edit_{category}") if edit_mode else InlineKeyboardButton("⚙️ Удаление", callback_data=f"toggle_edit_{category}")
        keyboard.append([mode_btn])
        keyboard.append([InlineKeyboardButton("⬅️ Назад к категориям", callback_data="list_cats")])
        await send_or_edit(update, context, message_text, reply_markup=InlineKeyboardMarkup(keyboard), force_new=force_new)
        return

    # Category selection with navigation at TOP if many
    # Filter categories based on show_bought flag
    categories = db.get_categories_with_items(user_id, include_bought=show_bought)
    keyboard = []
    if len(categories) > 6:
        keyboard.append([InlineKeyboardButton("📝 Показать всё", callback_data="list_ALL")])
    
    for cat in categories:
        keyboard.append([InlineKeyboardButton(cat, callback_data=f"list_{cat}")])
    
    keyboard.append([InlineKeyboardButton("📝 Показать всё", callback_data="list_ALL")])
    
    await send_or_edit(update, context, "🗏 *Выберите категорию:*", reply_markup=InlineKeyboardMarkup(keyboard), force_new=force_new)




async def send_or_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, force_new=False):
    """Helper to send a new message or edit the existing one, with tracking.
    
    NOTE: ReplyKeyboardMarkup is ONLY sent once at /start and never touched again.
    """
    try:
        last_msg_id = context.user_data.get("last_list_msg_id")
        
        # 1. Try to edit in-place if no force_new
        if last_msg_id and not force_new:
            try:
                msg = await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=last_msg_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup 
                )
                context.user_data["last_list_msg_id"] = msg.message_id
                return
            except Exception:
                pass

        # 2. Delete old list message if exists (but NEVER delete the keyboard message)
        keyboard_msg_id = context.user_data.get("keyboard_msg_id")
        logger.info(f"send_or_edit: last_msg_id={last_msg_id}, keyboard_msg_id={keyboard_msg_id}")
        if last_msg_id and last_msg_id != keyboard_msg_id:
            logger.info(f"Deleting old list message: {last_msg_id}")
            try: 
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=last_msg_id)
            except Exception as e:
                logger.error(f"Failed to delete message {last_msg_id}: {e}")
        elif last_msg_id == keyboard_msg_id:
            logger.info(f"Skipping deletion of keyboard message: {keyboard_msg_id}")

        # 3. Send the new list message with inline buttons
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        context.user_data["last_list_msg_id"] = msg.message_id
            
    except Exception as e:
        logger.error(f"Send/Edit error: {e}")


async def show_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle click on 'Show list' - always forces a new message to stay at bottom."""
    logger.info(f"Show list requested by {update.effective_user.id}")
    await list_items(update, context, force_new=True)


async def toggle_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle showing/hiding bought items from the main keyboard."""
    logger.info(f"Toggle view requested by {update.effective_user.id}")
    if not await check_access(update, context): return
    
    # Delete the user's message to keep chat clean
    try: await update.message.delete()
    except Exception: pass
    
    current = context.user_data.get("show_bought", False)
    context.user_data["show_bought"] = not current
    
    # Refresh the view
    last_cat = context.user_data.get("last_category")
    await list_items(update, context, category=last_cat, force_new=True)


async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to add a new category."""
    if not await check_access(update, context):
        return
    
    if not context.args:
        await update.message.reply_text("Использование: /add_cat Название категории")
        return
    
    cat_name = " ".join(context.args).strip()
    if db.add_category(update.effective_user.id, cat_name):
        await update.message.reply_text(f"✅ Категория '{cat_name}' добавлена.")
    else:
        await update.message.reply_text("❌ Категория уже существует.")


async def test_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple test handler that skips check_access."""
    await update.message.reply_text("Бот работает и видит ваши сообщения! ✅")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "list_cats":
        context.user_data["edit_mode"] = False
        await list_items(update, context)
    elif data.startswith("list_"):
        cat = data[5:] # More robust
        await list_items(update, context, category=cat)
    elif data == "toggle_view_inline":
        current = context.user_data.get("show_bought", False)
        context.user_data["show_bought"] = not current
        await list_items(update, context)
    elif data.startswith("toggle_edit_"):
        cat = data.replace("toggle_edit_", "")
        current = context.user_data.get("edit_mode", False)
        context.user_data["edit_mode"] = not current
        await list_items(update, context, category=cat)
    elif data.startswith("tog_"):
        parts = data.split("_")
        item_id = int(parts[1])
        ref_cat = parts[2] if len(parts) > 2 else None
        db.toggle_bought(item_id, user_id)
        # Update current view
        await list_items(update, context, category=ref_cat if ref_cat != "all" else "ALL")
    elif data.startswith("del_"):
        parts = data.split("_")
        item_id = int(parts[1])
        ref_cat = parts[2] if len(parts) > 2 else None
        db.delete_item(item_id, user_id)
        # Stay in edit mode/current view
        await list_items(update, context, category=ref_cat if ref_cat != "all" else "ALL")


def main():
    """Run bot."""
    logger.info(f"DEBUG: BOT_TOKEN is set: {bool(config.BOT_TOKEN)}")
    logger.info(f"DEBUG: ALLOWED_USERS: {config.ALLOWED_USERS}")
    if not config.BOT_TOKEN:
        print("Error: BOT_TOKEN not found in .env")
        return

    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # Add Item logic
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{config.BUTTON_ADD_ITEM}$"), add_item_start)],
        states={
            CHOOSING_DEPARTMENT: [CallbackQueryHandler(department_chosen)],
            ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_name_entered)],
        },
        fallbacks=[MessageHandler(filters.Regex(f"^{config.BUTTON_CANCEL}$"), cancel)],
    )
    
    application.add_handler(MessageHandler(filters.ALL, global_trace), group=-1) # Group -1 ensures it runs first
    application.add_handler(CommandHandler("test", test_handler))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_cat", add_category))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Text([config.BUTTON_SHOW_LIST]), show_list_handler))
    application.add_handler(MessageHandler(filters.Text([config.BUTTON_TOGGLE_BOUGHT]), toggle_view_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    logger.info("Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
