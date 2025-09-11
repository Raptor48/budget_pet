"""
Telegram bot using FastAPI instead of GitHub synchronization.
This is the new API-based version of bot.py
"""
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)
import os, re, logging
from datetime import datetime
# --- telegram imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler

# --- API client imports (replacing GitHub I/O) ------------------------------
from services.bot_adapter import (
    add_expense, get_month_report, get_remaining, list_limits, set_limit, get_current_month,
    add_peer_if_new, get_peer_ids, maybe_notify_thresholds, notify_peers
)
from services.finance_adapter import get_finance_accounts, get_finance_summary, create_finance_payment, get_loans, get_cards, get_income, FinanceAPIError

BOT_CURRENCY_SYMBOL = os.getenv("BOT_CURRENCY_SYMBOL", "$")
currency_symbol = BOT_CURRENCY_SYMBOL

def _format_report_html(report, month):
    lines = [f"<b>Отчёт за {month}</b>", ""]
    max_cat_len = max(len(r[0]) for r in report) if report else 0
    for category, spent, limit, remaining in report:
        limit_str = f"${limit:.2f}" if limit is not None else "—"
        lines.append(f"{category.ljust(max_cat_len)}  ${spent:.2f} / {limit_str}  Остаток: ${remaining:.2f}")
    return "<pre>" + "\n".join(lines) + "</pre>"

# --- category usage (MRU/most-used sorting) ----------------------------------
# Simplified version - we'll use API for this later if needed

def _record_category_use(cat: str):
    """Record category use - simplified for API mode."""
    # In API mode, we could track this via API calls if needed
    # For now, just pass - the API handles usage tracking
    pass

def _sort_categories_by_usage(cats: list[str]) -> list[str]:
    """Sort categories by usage - simplified for API mode."""
    # Return as-is for now, can be enhanced later with API call
    return sorted(cats)

# --- Telegram Bot Logic ---

# Logging configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# Set httpx logging to WARNING to reduce noise in Railway logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Config
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED = list(map(int, filter(None, os.getenv("ALLOWED_USERS", "").split(","))))

def _allowed(user_id: int) -> bool:
    return not ALLOWED or user_id in ALLOWED

def _current_month_for_user(context):
    return get_current_month()

# --- Categories ---

def _get_categories():
    """Get list of categories from limits."""
    try:
        # Use asyncio to run the async function
        import asyncio
        import threading
        
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(list_limits())
            finally:
                loop.close()
        
        # Run in a separate thread to avoid event loop conflicts
        result = None
        def target():
            nonlocal result
            result = run_in_thread()
        
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()
        
        if result:
            categories = [cat for cat, _ in result]
            return _sort_categories_by_usage(categories)
        else:
            return ["Food", "Transport", "Entertainment"]  # fallback
            
    except Exception as e:
        log.error("Failed to get categories: %s", e)
        return ["Food", "Transport", "Entertainment"]  # fallback

def _build_categories_keyboard(page=0, per_page=8):
    """Inline-клавиатура для выбора категории с пагинацией."""
    cats = _get_categories()
    total = len(cats)
    start = max(0, page * per_page)
    end = min(total, start + per_page)
    page_cats = cats[start:end]

    rows = []
    # кладём по 2 кнопки в ряд
    for i in range(0, len(page_cats), 2):
        chunk = page_cats[i:i+2]
        rows.append([InlineKeyboardButton(c, callback_data=f"cat:{c}") for c in chunk])

    # навигация
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"page:{page+1}"))
    if nav:
        rows.append(nav)

    # назад в главное меню
    rows.append([InlineKeyboardButton("⬅️ back", callback_data="back:main")])

    # если категорий нет – сообщим об этом
    if not cats:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ back", callback_data="back:main")]
        ])

    return InlineKeyboardMarkup(rows)

def _build_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Report (month)", callback_data="report")],
        [InlineKeyboardButton("➕ add expenses", callback_data="add")],
        [InlineKeyboardButton("💰 Loans & Credit Cards", callback_data="finance")]
    ])

def _build_finance_keyboard():
    """Build finance menu keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Finance Summary", callback_data="finance:summary")],
        [InlineKeyboardButton("🏦 Loans", callback_data="finance:loans")],
        [InlineKeyboardButton("💳 Credit Cards", callback_data="finance:cards")],
        [InlineKeyboardButton("💵 Income", callback_data="finance:income")],
        [InlineKeyboardButton("⬅️ back", callback_data="back:main")]
    ])

def _build_loans_keyboard():
    """Build loans menu keyboard."""
    try:
        loans = get_loans()
        if not loans:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ back", callback_data="back:finance")]
            ])
        
        rows = []
        for loan in loans:
            rows.append([InlineKeyboardButton(
                f"🏦 {loan['name']} (${loan['current_balance_cents']/100:.2f})", 
                callback_data=f"loan:{loan['id']}"
            )])
        
        rows.append([InlineKeyboardButton("⬅️ back", callback_data="back:finance")])
        return InlineKeyboardMarkup(rows)
    except FinanceAPIError:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Error loading loans", callback_data="back:finance")]
        ])

def _build_cards_keyboard():
    """Build credit cards menu keyboard."""
    try:
        cards = get_cards()
        if not cards:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ back", callback_data="back:finance")]
            ])
        
        rows = []
        for card in cards:
            rows.append([InlineKeyboardButton(
                f"💳 {card['name']} (${card['current_balance_cents']/100:.2f})", 
                callback_data=f"card:{card['id']}"
            )])
        
        rows.append([InlineKeyboardButton("⬅️ back", callback_data="back:finance")])
        return InlineKeyboardMarkup(rows)
    except FinanceAPIError:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Error loading cards", callback_data="back:finance")]
        ])

def _build_income_keyboard():
    """Build income menu keyboard."""
    try:
        current_month = get_current_month()
        income = get_income(current_month)
        if not income:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ back", callback_data="back:finance")]
            ])
        
        rows = []
        for entry in income:
            rows.append([InlineKeyboardButton(
                f"💵 {entry['person']} - ${entry['amount_cents']/100:.2f} ({entry['occurred_at']})", 
                callback_data=f"income:{entry['id']}"
            )])
        
        rows.append([InlineKeyboardButton("⬅️ back", callback_data="back:finance")])
        return InlineKeyboardMarkup(rows)
    except FinanceAPIError:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Error loading income", callback_data="back:finance")]
        ])

# --- Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        await update.message.reply_text("Access denied.")
        return
    
    # Add user to peers for notifications
    user_id = update.effective_user.id
    username = update.effective_user.full_name or "Unknown"
    await add_peer_if_new(user_id, username)
    
    await update.message.reply_text(
        "👋 Привет! Я бот для учёта расходов.\n\n"
        "Команды:\n"
        "/help - помощь\n"
        "/month - отчёт за месяц\n"
        "/limits - лимиты категорий\n"
        "/setlimit <категория> <сумма> - установить лимит\n\n"
        "Или просто выберите действие:",
        reply_markup=_build_main_keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот для семейного бюджета\n\n"
        "📝 Добавление расходов:\n"
        "• Нажмите 'Добавить расход' или /add\n"
        "• Выберите категорию\n"
        "• Введите сумму\n\n"
        "📊 Отчёты и лимиты:\n"
        "• /month - отчёт за текущий месяц\n"
        "• /limits - посмотреть лимиты\n"
        "• /setlimit Еда 1000 - установить лимит\n\n"
        "💡 Бот работает через API и синхронизируется в реальном времени!"
    )

async def month_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    
    try:
        month = get_current_month()
        report_data = await get_month_report(month)
        
        if not report_data:
            await update.message.reply_text(f"Нет расходов за {month}")
            return
        
        # Convert to format expected by _format_report_html
        report = []
        for category, data in report_data.items():
            spent = data.get('spent', 0.0)
            budget = data.get('budget', 0.0)
            remaining = budget - spent
            report.append((category, spent, budget if budget > 0 else None, remaining))
        
        # Sort by spending
        report.sort(key=lambda x: x[1], reverse=True)
        
        html = _format_report_html(report, month)
        await update.message.reply_text(html, parse_mode="HTML")
        
    except Exception as e:
        log.error("Month command failed: %s", e)
        await update.message.reply_text(f"Ошибка: {e}")

async def limits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    
    try:
        limits_list = await list_limits()
        
        if not limits_list:
            await update.message.reply_text("Лимиты не установлены")
            return
        
        lines = ["💰 <b>Лимиты категорий:</b>\n"]
        for category, amount in limits_list:
            lines.append(f"• {category}: {currency_symbol}{amount:.2f}")
        
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        
    except Exception as e:
        log.error("Limits command failed: %s", e)
        await update.message.reply_text(f"Ошибка: {e}")

async def setlimit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /setlimit <категория> <сумма>\nПример: /setlimit Еда 1000")
        return
    
    try:
        cat = context.args[0]
        amount = float(context.args[1])
        
        await set_limit(cat, amount)
        await update.message.reply_text(f"✅ Лимит для '{cat}': {currency_symbol}{amount:.2f}")
        
    except ValueError:
        await update.message.reply_text("Ошибка: введите корректную сумму")
    except Exception as e:
        log.error("Setlimit command failed: %s", e)
        await update.message.reply_text(f"Ошибка: {e}")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for month command."""
    await month_cmd(update, context)

# --- Callback handlers ---

async def on_btn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    if not _allowed(q.from_user.id):
        await q.edit_message_text("Access denied.")
        return
    
    data = q.data
    
    if data == "add":
        await q.edit_message_text("Выберите категорию:", reply_markup=_build_categories_keyboard())
    
    elif data.startswith("page:"):
        page = int(data.split(":")[1])
        await q.edit_message_text("Выберите категорию:", reply_markup=_build_categories_keyboard(page))
    
    elif data.startswith("cat:"):
        category = data.split(":", 1)[1]
        context.user_data["await_amount_for"] = category
        await q.edit_message_text(f"Категория: {category}\nВведите сумму:")
    
    elif data == "report":
        try:
            month = get_current_month()
            report_data = await get_month_report(month)
            
            if not report_data:
                await q.edit_message_text(f"Нет расходов за {month}")
                return

            # Convert to format expected by _format_report_html
            report = []
            for category, data in report_data.items():
                spent = data.get('spent', 0.0)
                budget = data.get('budget', 0.0)
                remaining = budget - spent
                report.append((category, spent, budget if budget > 0 else None, remaining))
            
            # Sort by spending
            report.sort(key=lambda x: x[1], reverse=True)
            
            html = _format_report_html(report, month)
            await q.edit_message_text(html, parse_mode="HTML")
            
        except Exception as e:
            log.error("Report button failed: %s", e)
            await q.edit_message_text(f"Ошибка: {e}")
    
    elif data == "limits":
        try:
            limits_list = await list_limits()
            
            if not limits_list:
                await q.edit_message_text("Лимиты не установлены")
                return
            
            lines = ["💰 <b>Лимиты категорий:</b>\n"]
            for category, amount in limits_list:
                lines.append(f"• {category}: {currency_symbol}{amount:.2f}")
            
            await q.edit_message_text("\n".join(lines), parse_mode="HTML")
            
        except Exception as e:
            log.error("Limits button failed: %s", e)
            await q.edit_message_text(f"Ошибка: {e}")
    
    elif data == "finance":
        await q.edit_message_text("💰 <b>Loans & Credit Cards</b>\n\nВыберите действие:", reply_markup=_build_finance_keyboard(), parse_mode="HTML")
    
    elif data == "finance:summary":
        try:
            month = get_current_month()
            summary = get_finance_summary(month)
            
            text = f"📊 <b>Finance Summary - {month}</b>\n\n"
            text += f"💰 <b>Total Income:</b> ${summary['income_total_cents']/100:.2f}\n"
            text += f"   • Denis: ${summary['income_by_person']['Denis']/100:.2f}\n"
            text += f"   • Taya: ${summary['income_by_person']['Taya']/100:.2f}\n\n"
            text += f"💳 <b>Total Debt:</b> ${summary['debt_totals']['combined_balance_cents']/100:.2f}\n"
            text += f"   • Loans: ${summary['debt_totals']['loans_balance_cents']/100:.2f}\n"
            text += f"   • Cards: ${summary['debt_totals']['cards_balance_cents']/100:.2f}\n\n"
            text += f"💸 <b>Min Payments:</b> ${summary['debt_totals']['min_payments_cents']/100:.2f}\n\n"
            
            net_income = summary['income_total_cents'] - summary['debt_totals']['min_payments_cents']
            text += f"📈 <b>Net Income:</b> ${net_income/100:.2f}\n"
            
            if summary['loans_estimated_close']:
                text += f"\n🏦 <b>Estimated Loan Closures:</b>\n"
                for loan in summary['loans_estimated_close']:
                    text += f"   • {loan['name']}: {loan['remaining_months']} months (est. {loan['estimated_close_date']})\n"
            
            await q.edit_message_text(text, reply_markup=_build_finance_keyboard(), parse_mode="HTML")
            
        except FinanceAPIError as e:
            await q.edit_message_text(f"❌ Error loading finance summary: {e}", reply_markup=_build_finance_keyboard())
        except Exception as e:
            log.error("Finance summary failed: %s", e)
            await q.edit_message_text(f"❌ Error: {e}", reply_markup=_build_finance_keyboard())
    
    elif data == "finance:loans":
        await q.edit_message_text("🏦 <b>Loans</b>\n\nВыберите займ для платежа:", reply_markup=_build_loans_keyboard(), parse_mode="HTML")
    
    elif data == "finance:cards":
        await q.edit_message_text("💳 <b>Credit Cards</b>\n\nВыберите карту для платежа:", reply_markup=_build_cards_keyboard(), parse_mode="HTML")
    
    elif data == "finance:income":
        await q.edit_message_text("💵 <b>Income</b>\n\nДоходы за текущий месяц:", reply_markup=_build_income_keyboard(), parse_mode="HTML")
    
    elif data.startswith("loan:"):
        loan_id = int(data.split(":")[1])
        context.user_data["await_payment_for"] = {"type": "loan", "id": loan_id}
        await q.edit_message_text("💳 Введите сумму платежа по займу:")
    
    elif data.startswith("card:"):
        card_id = int(data.split(":")[1])
        context.user_data["await_payment_for"] = {"type": "card", "id": card_id}
        await q.edit_message_text("💳 Введите сумму платежа по кредитной карте:")
    
    elif data == "back:finance":
        await q.edit_message_text("💰 <b>Loans & Credit Cards</b>\n\nВыберите действие:", reply_markup=_build_finance_keyboard(), parse_mode="HTML")
    
    elif data == "back:main":
        await q.edit_message_text("🤖 Бот для семейного бюджета\n\nВыберите действие:", reply_markup=_build_main_keyboard())

# --- Text handler ---

async def text_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _allowed(update.effective_user.id):
        return
    
    text = update.message.text.strip()
    pending_cat = context.user_data.get("await_amount_for")
    pending_payment = context.user_data.get("await_payment_for")
    
    if pending_payment:
        # User is entering payment amount
        amt_txt = text.replace(",", ".")
        try:
            amount = float(amt_txt)
        except ValueError:
            await update.message.reply_text("Введите число, например 123.45 или 123,45. Или нажмите /cancel")
            return
        
        try:
            # Create payment
            today = datetime.now().strftime("%Y-%m-%d")
            payment = create_finance_payment(
                account_type=pending_payment["type"],
                account_id=pending_payment["id"],
                amount=amount,
                occurred_at=today,
                person="Denis",  # Default to Denis, can be made configurable
                note=f"Payment via bot"
            )
            
            context.user_data.pop("await_payment_for", None)
            
            account_type_name = "займ" if pending_payment["type"] == "loan" else "кредитная карта"
            msg = f"✅ Платеж по {account_type_name}: -{currency_symbol}{amount:.2f}\n"
            msg += f"📅 Дата: {today}"
            
            await update.message.reply_text(msg, reply_markup=_build_main_keyboard())
            
        except FinanceAPIError as e:
            await update.message.reply_text(f"❌ Ошибка при создании платежа: {e}")
        except Exception as e:
            log.error("Create payment failed: %s", e)
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    elif pending_cat:
        # User is entering amount
        amt_txt = text.replace(",", ".")
        try:
            amount = float(amt_txt)
        except ValueError:
            await update.message.reply_text("Введите число, например 123.45 или 123,45. Или нажмите /cancel")
            return
        
        try:
            exceeded, remaining = await add_expense(pending_cat, amount)
            context.user_data.pop("await_amount_for", None)
            
            msg = f"✅ {pending_cat}: +{currency_symbol}{amount:.2f}"
            if exceeded:
                msg += f"\n⚠️ Превышен лимит! Остаток: {currency_symbol}{remaining:.2f}"
            
            _record_category_use(pending_cat)
            await update.message.reply_text(msg, reply_markup=_build_main_keyboard())
            
            # Send threshold notifications
            month = get_current_month()
            await maybe_notify_thresholds(pending_cat, month, context)
            
            # Notify other peers
            sender_id = update.effective_user.id if update.effective_user else None
            sender_name = update.effective_user.full_name if update.effective_user else "Someone"
            allowed_ids = ALLOWED if len(ALLOWED) > 0 else None
            await notify_peers(sender_name, pending_cat, amount, currency_symbol, context, sender_id, allowed_ids)
            
        except Exception as e:
            log.error("Add expense failed: %s", e)
            await update.message.reply_text(f"Ошибка: {e}")
    
    else:
        # Try to parse as "Category Amount"
        match = re.match(r"^([a-zA-Zа-яёА-ЯЁ\s]+)\s+([\d,\.]+)$", text)
        if match:
            cat = match.group(1).strip()
            amt_txt = match.group(2).replace(",", ".")
            try:
                amount = float(amt_txt)
                exceeded, remaining = await add_expense(cat, amount)
                
                msg = f"✅ {cat}: +{currency_symbol}{amount:.2f}"
                if exceeded:
                    msg += f"\n⚠️ Превышен лимит! Остаток: {currency_symbol}{remaining:.2f}"
                
                _record_category_use(cat)
                await update.message.reply_text(msg, reply_markup=_build_main_keyboard())
                
                # Send threshold notifications
                month = get_current_month()
                await maybe_notify_thresholds(cat, month, context)
                
                # Notify other peers
                sender_id = update.effective_user.id if update.effective_user else None
                sender_name = update.effective_user.full_name if update.effective_user else "Someone"
                allowed_ids = ALLOWED if len(ALLOWED) > 0 else None
                await notify_peers(sender_name, cat, amount, currency_symbol, context, sender_id, allowed_ids)
                
            except ValueError:
                await update.message.reply_text("Неверный формат суммы")
            except Exception as e:
                log.error("Quick add failed: %s", e)
                await update.message.reply_text(f"Ошибка: {e}")
        else:
            await update.message.reply_text(
                "Не понял 🤔\n\n"
                "Попробуйте:\n"
                "• Нажать кнопку 'Добавить расход'\n"
                "• Написать 'Еда 250' или 'Transport 50'\n"
                "• Использовать команды /help"
            )

# --- Main ---

if __name__ == "__main__":
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        exit(1)
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("month", month_cmd))
    app.add_handler(CommandHandler("limits", limits_cmd))
    app.add_handler(CommandHandler("setlimit", setlimit_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CallbackQueryHandler(on_btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_add))

    log.info("🚀 Starting API-based Telegram bot...")
    log.info("🌐 API URL: %s", os.getenv("API_BASE_URL", "https://fastapi-production-eadf.up.railway.app"))
    
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=1,
        timeout=20
    )
