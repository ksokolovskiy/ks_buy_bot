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
import functools
import config
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
CAT_MANAGE_ACTION, CAT_ADDING, CAT_RENAMING_SELECT, CAT_RENAMING_NEW_NAME, CAT_DELETING_SELECT, CAT_DELETING_CONFIRM = range(2, 8)

# Initialize database
db = Database(config.DATABASE_URL)

def restricted(func):
    """Decorator to check if user is allowed to use the bot."""
    @functools.wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.ALLOWED_USERS:
            logger.warning(f"Unauthorized access attempt by user {user_id}")
            await update.effective_message.reply_text(config.MSG_ACCESS_DENIED)
            return ConversationHandler.END if isinstance(func, type(add_item_start)) else None
        return await func(update, context, *args, **kwargs)
    return wrapped


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
        ],
        [
            KeyboardButton(config.BUTTON_MANAGE_CATS),
            KeyboardButton(config.BUTTON_SHARE_LIST)
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    logger.info(f"Start command from {update.effective_user.id}")
    
    # Seed data for the user on first start
    db.seed_data(update.effective_user.id)
    
    msg = await update.message.reply_text(
        config.MSG_WELCOME,
        reply_markup=get_main_keyboard(context)
    )
    # CRITICAL: Save keyboard message ID to prevent deletion
    context.user_data["keyboard_msg_id"] = msg.message_id


@restricted
async def add_item_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the add item flow."""
    logger.info(f"Add item started by {update.effective_user.id}")
    
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
    
    # Targeted cleanup
    for key in ["department"]:
        context.user_data.pop(key, None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current operation."""
    # Targeted cleanup
    for key in ["department", "delete_cat_name", "rename_old_name"]:
        context.user_data.pop(key, None)
    
    msg = "Отменено."
    if update.message:
        await update.message.reply_text(msg)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg)
    
    return ConversationHandler.END


async def list_items(update: Update, context: ContextTypes.DEFAULT_TYPE, category=None, force_new=False):
    """List shopping items. If category is None, show category selection."""
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
    keyboard.append([InlineKeyboardButton("⚙️ Управление категориями", callback_data="manage_cats_inline")])
    
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


@restricted
async def show_list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the 'List' button."""
    logger.info(f"Show list requested by {update.effective_user.id}")
    await list_items(update, context, force_new=True)


@restricted
async def toggle_view_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle showing/hiding bought items from the main keyboard."""
    logger.info(f"Toggle view requested by {update.effective_user.id}")
    
    # Delete the user's message to keep chat clean
    try: await update.message.delete()
    except Exception: pass
    
    current = context.user_data.get("show_bought", False)
    context.user_data["show_bought"] = not current
    
    # Refresh the view
    last_cat = context.user_data.get("last_category")
    await list_items(update, context, category=last_cat, force_new=True)


@restricted
async def share_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the 'Share' button."""
    logger.info(f"Share requested by {update.effective_user.id}")
    invite_code = db.get_invite_code(update.effective_user.id)
    await update.message.reply_text(
        config.MSG_SHARE_INFO.format(invite_code, invite_code),
        parse_mode="Markdown"
    )


@restricted
async def join_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /join command."""
    if not context.args:
        await update.message.reply_text("Использование: /join КОД")
        return
    
    invite_code = context.args[0].upper()
    context.user_data["pending_invite_code"] = invite_code
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Присоединиться", callback_data="join_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="join_cancel")
        ]
    ]
    await update.message.reply_text(
        config.MSG_JOIN_CONFIRM,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def join_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle join confirmation."""
    query = update.callback_query
    await query.answer()
    
    invite_code = context.user_data.get("pending_invite_code")
    if not invite_code:
        await query.edit_message_text("Ошибка: код не найден.")
        return

    success, message = db.join_group(update.effective_user.id, invite_code)
    if success:
        await query.edit_message_text(config.MSG_JOIN_SUCCESS)
    else:
        await query.edit_message_text(config.MSG_JOIN_ERROR)
    
    context.user_data.pop("pending_invite_code", None)


@restricted
async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to add a new category."""
    
    if not context.args:
        await update.message.reply_text("Использование: /add_cat Название категории")
        return
    
    cat_name = " ".join(context.args).strip()
    if db.add_category(update.effective_user.id, cat_name):
        await update.message.reply_text(f"✅ Категория '{cat_name}' добавлена.")
    else:
        await update.message.reply_text("❌ Категория уже существует.")


@restricted
async def manage_categories_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start category management flow."""
    if update.callback_query:
        await update.callback_query.answer()
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить категорию", callback_data="cat_add")],
        [InlineKeyboardButton("✏️ Переименовать категорию", callback_data="cat_rename")],
        [InlineKeyboardButton("🗑 Удалить категорию", callback_data="cat_delete")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(config.MSG_CATEGORY_MENU, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(config.MSG_CATEGORY_MENU, reply_markup=reply_markup, parse_mode='Markdown')
    
    return CAT_MANAGE_ACTION


async def cat_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle action selection in category management."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if query.data == "cat_add":
        await query.edit_message_text("Введите название новой категории:")
        return CAT_ADDING
    
    elif query.data == "cat_rename":
        categories = db.get_categories(user_id)
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(cat, callback_data=f"rename_{cat}")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")])
        
        await query.edit_message_text(config.MSG_CHOOSE_CATEGORY_TO_RENAME, reply_markup=InlineKeyboardMarkup(keyboard))
        return CAT_RENAMING_SELECT
    
    elif query.data == "cat_delete":
        categories = db.get_categories(user_id)
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(cat, callback_data=f"delete_{cat}")])
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_menu")])
        
        await query.edit_message_text(config.MSG_CHOOSE_CATEGORY_TO_DELETE, reply_markup=InlineKeyboardMarkup(keyboard))
        return CAT_DELETING_SELECT
    
    elif query.data == "back_to_menu":
        return await manage_categories_start(update, context)
        
    elif query.data == "cancel":
        await query.edit_message_text("Управление категориями завершено.")
        return ConversationHandler.END


async def cat_adding_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new category name entry."""
    cat_name = update.message.text.strip()
    user_id = update.effective_user.id
    
    if db.add_category(user_id, cat_name):
        await update.message.reply_text(f"✅ Категория '{cat_name}' добавлена.")
    else:
        await update.message.reply_text(config.MSG_CATEGORY_EXISTS)
    
    return await manage_categories_start(update, context)


async def cat_renaming_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection for renaming."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_menu":
        return await manage_categories_start(update, context)
    
    old_name = query.data.replace("rename_", "")
    context.user_data["old_cat_name"] = old_name
    
    await query.edit_message_text(f"Выбрана категория: *{old_name}*\n\n{config.MSG_ENTER_NEW_CATEGORY_NAME}", parse_mode='Markdown')
    return CAT_RENAMING_NEW_NAME


async def cat_renaming_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle entry of new category name."""
    new_name = update.message.text.strip()
    old_name = context.user_data.get("old_cat_name")
    user_id = update.effective_user.id
    
    if db.rename_category(user_id, old_name, new_name):
        await update.message.reply_text(config.MSG_CATEGORY_RENAMED)
    else:
        await update.message.reply_text(config.MSG_CATEGORY_EXISTS)
    
    return await manage_categories_start(update, context)


async def cat_deleting_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection for deletion."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_menu":
        return await manage_categories_start(update, context)
    
    cat_name = query.data.replace("delete_", "")
    user_id = update.effective_user.id
    
    # Check how many items are in this category
    items = db.get_items(user_id, include_bought=True)
    cat_items_count = len([i for i in items if i['department'] == cat_name])
    
    context.user_data["delete_cat_name"] = cat_name
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data="confirm_delete")],
        [InlineKeyboardButton("❌ Отмена", callback_data="back_to_menu")]
    ]
    
    await query.edit_message_text(
        config.MSG_CONFIRM_DELETE_CATEGORY.format(cat_name, cat_items_count),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CAT_DELETING_CONFIRM


async def cat_deleting_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually delete the category and items."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_menu":
        return await manage_categories_start(update, context)
    
    cat_name = context.user_data.get("delete_cat_name")
    user_id = update.effective_user.id
    
    success, items_deleted = db.delete_category(user_id, cat_name)
    if success:
        await query.edit_message_text(config.MSG_CATEGORY_DELETED.format(items_deleted))
    else:
        await query.edit_message_text("❌ Ошибка при удалении категории.")
    
    return await manage_categories_start(update, context)


async def test_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple test handler that skips check_access."""
    await update.message.reply_text("Бот работает и видит ваши сообщения! ✅")

@restricted
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
        # Update current view
        await list_items(update, context, category=ref_cat if ref_cat != "all" else "ALL")
    elif data == "join_confirm":
        await join_confirm_handler(update, context)
    elif data == "join_cancel":
        context.user_data.pop("pending_invite_code", None)
        await query.edit_message_text("Вход в группу отменен.")


def main():
    """Run bot."""
    logger.info(f"DEBUG: BOT_TOKEN is set: {bool(config.BOT_TOKEN)}")
    logger.info(f"DEBUG: ALLOWED_USERS: {config.ALLOWED_USERS}")
    if not config.BOT_TOKEN:
        print("Error: BOT_TOKEN not found in .env")
        return

    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # Common navigation fallbacks to break out of any conversation
    nav_fallbacks = [
        MessageHandler(filters.Regex(f"^{config.BUTTON_SHOW_LIST}$"), show_list_handler),
        MessageHandler(filters.Regex(f"^{config.BUTTON_TOGGLE_BOUGHT}$"), toggle_view_handler),
        MessageHandler(filters.Regex(f"^{config.BUTTON_MANAGE_CATS}$"), manage_categories_start),
        CommandHandler("start", start),
        CommandHandler("share", share_handler),
        CommandHandler("join", join_command_handler),
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel, pattern="^cancel$")
    ]

    # Add Item logic
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{config.BUTTON_ADD_ITEM}$"), add_item_start)],
        states={
            CHOOSING_DEPARTMENT: [CallbackQueryHandler(department_chosen)],
            ENTERING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, item_name_entered)],
        },
        fallbacks=nav_fallbacks,
        allow_reentry=True
    )
    
    cat_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("manage_categories", manage_categories_start),
            MessageHandler(filters.Text([config.BUTTON_MANAGE_CATS]), manage_categories_start),
            CallbackQueryHandler(manage_categories_start, pattern="^manage_cats_inline$")
        ],
        states={
            CAT_MANAGE_ACTION: [CallbackQueryHandler(cat_action_chosen)],
            CAT_ADDING: [MessageHandler(filters.TEXT & ~filters.COMMAND, cat_adding_name)],
            CAT_RENAMING_SELECT: [CallbackQueryHandler(cat_renaming_selected)],
            CAT_RENAMING_NEW_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, cat_renaming_new_name)],
            CAT_DELETING_SELECT: [CallbackQueryHandler(cat_deleting_selected)],
            CAT_DELETING_CONFIRM: [CallbackQueryHandler(cat_deleting_confirmed)],
        },
        fallbacks=nav_fallbacks,
        allow_reentry=True
    )
    
    application.add_handler(MessageHandler(filters.ALL, global_trace), group=-1) # Group -1 ensures it runs first
    application.add_handler(CommandHandler("test", test_handler))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_cat", add_category))
    application.add_handler(conv_handler)
    application.add_handler(cat_conv_handler)
    application.add_handler(MessageHandler(filters.Text([config.BUTTON_SHOW_LIST]), show_list_handler))
    application.add_handler(MessageHandler(filters.Text([config.BUTTON_TOGGLE_BOUGHT]), toggle_view_handler))
    application.add_handler(CommandHandler("join", join_command_handler))
    application.add_handler(CommandHandler("share", share_handler))
    application.add_handler(MessageHandler(filters.Text([config.BUTTON_SHARE_LIST]), share_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    logger.info("Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
