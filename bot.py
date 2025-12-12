# bot.py (final, robust)
import os
import logging
from typing import Dict, Any, List

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, CallbackQueryHandler, filters
)

from recommender import CourseRecommender, Course

# ---------- logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("coursera-bot")

# ---------- config ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_PATH = (os.getenv("DATA_PATH", "C:/Users/Lenovo/OneDrive/Desktop/TelegramCourseBot/coursea_data.csv") or "").replace("\\", "/")

# ---------- model ----------
RECO = CourseRecommender(DATA_PATH)
logger.info("Dataset loaded: %s (%d rows)", DATA_PATH, len(RECO.df))

# simple in-memory prefs
USERS: Dict[int, Dict[str, Any]] = {}

# ---------- helpers ----------
def render_level_menu(text: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🟢 Beginner", callback_data="level_Beginner"),
            InlineKeyboardButton("🟡 Intermediate", callback_data="level_Intermediate"),
            InlineKeyboardButton("🔴 Advanced",   callback_data="level_Advanced"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def render_cert_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🎓 Course",            callback_data="cert_COURSE"),
            InlineKeyboardButton("📚 Specialization",    callback_data="cert_SPECIALIZATION"),
            InlineKeyboardButton("💼 Professional",      callback_data="cert_PROFESSIONAL"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Level", callback_data="back_to_level"),
            InlineKeyboardButton("❌ Cancel",         callback_data="back_home"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def render_confirm_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✅ Save & Close", callback_data="confirm_save"),
        ],
        [
            InlineKeyboardButton("⬅️ Back to Certificate", callback_data="back_to_cert"),
            InlineKeyboardButton("⬅️ Back to Level",       callback_data="back_to_level"),
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="back_home"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def human_int(n: float) -> str:
    n = float(n)
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return f"{int(n)}"

def format_course(c: Course) -> str:
    return (
        f"<b>{c.title}</b>\n"
        f"🏫 {c.organization or 'N/A'} | 🎓 {c.certificate_type or 'N/A'} | 🎯 {c.difficulty or 'N/A'}\n"
        f"⭐ Rating: {c.rating:.1f}   👥 Learners: {human_int(c.students_enrolled)}"
    )

def build_url_button(_: str | None = None) -> InlineKeyboardMarkup:
    # No URL column in your CSV yet; leave empty.
    return InlineKeyboardMarkup([])

def _apply_user_filters(courses: List[Course], prefs: Dict[str, Any]) -> List[Course]:
    """Filter a list of Course objects by saved user prefs (pure Python)."""
    level = (prefs.get("difficulty") or "").lower()
    cert  = (prefs.get("certificate_type") or "").lower()

    def ok(c: Course) -> bool:
        good = True
        if level:
            good = good and (level in (c.difficulty or "").lower())
        if cert:
            good = good and (cert in (c.certificate_type or "").lower())
        return good

    return [c for c in courses if ok(c)]

# ---------- commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "<b>Hi! I’m your Coursera Recommender 🤖</b>\n\n"
        "Just type what you want to learn, e.g.:\n"
        "• python for beginners\n"
        "• data science with python\n\n"
        "Commands:\n"
        "/setprefs – set your level & certificate via buttons\n"
        "/top – show trending courses\n"
        "/help – quick tips"
    )
    await update.message.reply_html(msg)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Tips:\n"
        "• Send a topic (e.g., 'machine learning', 'excel basics').\n"
        "• Use /setprefs to choose difficulty and certificate type.\n"
        "• Use /top to see popular picks."
    )

# ---- /setprefs with buttons ----

async def setprefs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    USERS.setdefault(chat_id, {})
    await update.message.reply_text(
        "Step 1 of 3 — choose your preferred <b>difficulty level</b>:",
        reply_markup=render_level_menu(""),
        parse_mode="HTML",
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    USERS.setdefault(chat_id, {})

    # ----- LEVEL CHOSEN -----
    if data.startswith("level_"):
        level = data.split("_", 1)[1]
        USERS[chat_id]["difficulty"] = level
        await query.edit_message_text(
            text=f"Step 2 of 3 — level set to <b>{level}</b>.\nNow pick a <b>certificate type</b>:",
            reply_markup=render_cert_menu(),
            parse_mode="HTML",
        )

    # ----- CERT CHOSEN -----
    elif data.startswith("cert_"):
        cert = data.split("_", 1)[1]
        USERS[chat_id]["certificate_type"] = cert
        level = USERS[chat_id].get("difficulty", "N/A")
        await query.edit_message_text(
            text=(
                "Step 3 of 3 — review your choices:\n\n"
                f"<b>Difficulty:</b> {level}\n"
                f"<b>Certificate:</b> {cert}\n\n"
                "You can go back and change anything, or press <b>Save & Close</b>."
            ),
            reply_markup=render_confirm_menu(),
            parse_mode="HTML",
        )

    # ----- CONFIRM SAVE -----
    elif data == "confirm_save":
        level = USERS[chat_id].get("difficulty", "N/A")
        cert  = USERS[chat_id].get("certificate_type", "N/A")
        await query.edit_message_text(
            text=(
                "✅ <b>Preferences saved!</b>\n\n"
                f"<b>Difficulty:</b> {level}\n"
                f"<b>Certificate:</b> {cert}\n\n"
                "Now type a topic (e.g., 'data science') or use /top 🔥"
            ),
            parse_mode="HTML",
        )

    # ----- BACK BUTTONS -----
    elif data == "back_to_cert":
        # Go back to certificate selection (keep chosen level)
        await query.edit_message_text(
            text="🔙 Back to Step 2 — choose your <b>certificate type</b>:",
            reply_markup=render_cert_menu(),
            parse_mode="HTML",
        )

    elif data == "back_to_level":
        # Go back to level selection (we keep any previously selected values in USERS)
        await query.edit_message_text(
            text="🔙 Back to Step 1 — choose your preferred <b>difficulty level</b>:",
            reply_markup=render_level_menu(""),
            parse_mode="HTML",
        )

    elif data == "back_home":
        # Cancel the flow completely
        await query.edit_message_text(
            text="❌ Preferences setup cancelled. Use /setprefs to start again.",
        )

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prefs = USERS.get(chat_id, {})
    courses = RECO.trending(top_k=10)
    courses = _apply_user_filters(courses, prefs) or courses[:5]
    await update.message.reply_text("🔥 Trending courses:")
    for c in courses[:5]:
        await update.message.reply_html(format_course(c), reply_markup=build_url_button(None))

# ---- message handler with safe filtering ----
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    chat_id = update.effective_chat.id
    prefs = USERS.get(chat_id, {})

    # get a larger pool, then filter in Python by prefs
    pool = RECO.recommend(query=text, top_k=25)
    picked = _apply_user_filters(pool, prefs)

    if not picked:
        # fallback: just show top relevant if nothing matches prefs
        picked = pool[:5]

    await update.message.reply_text("Here are your recommendations:")
    for c in picked[:5]:
        await update.message.reply_html(format_course(c), reply_markup=build_url_button(None))

# ---- global error handler so the bot never dies silently ----
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception in handler", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text("Oops, something went wrong. Try again.")
    except Exception:
        pass

# ---------- main ----------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set in environment or .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("setprefs", setprefs))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_error_handler(error_handler)

    logger.info("Application started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
