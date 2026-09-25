import os
import re
import sqlite3
import random
import logging
from datetime import datetime
from urllib.parse import quote

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 8394607974
CHANNEL = "@ByteTunnel"
DB_FILE = "bytetunnel_config.db"

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Prevent Telegram bot token from appearing in HTTP request logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

COUNTRIES = [
    ("🇩🇪", "آلمان"),
    ("🇫🇮", "فنلاند"),
    ("🇺🇸", "آمریکا"),
    ("🇳🇱", "هلند"),
    ("🇫🇷", "فرانسه"),
    ("🇬🇧", "انگلیس"),
    ("🇨🇦", "کانادا"),
    ("🇸🇪", "سوئد"),
    ("🇨🇭", "سوئیس"),
    ("🇯🇵", "ژاپن"),
    ("🇹🇷", "ترکیه"),
    ("🇷🇺", "روسیه"),
    ("🇵🇱", "لهستان"),
    ("🇮🇹", "ایتالیا"),
    ("🇦🇹", "اتریش"),
    ("🇳🇴", "نروژ"),
    ("🇪🇸", "اسپانیا"),
    ("🇧🇪", "بلژیک"),
    ("🇷🇴", "رومانی"),
    ("🇸🇬", "سنگاپور"),
]

USER_MENU = ReplyKeyboardMarkup(
    [
        ["📥 دریافت کانفیگ"],
        ["📖 راهنما"],
        ["🟢 وصل شد", "🔴 وصل نشد"],
    ],
    resize_keyboard=True,
)

ADMIN_MENU = ReplyKeyboardMarkup(
    [
        ["➕ افزودن کانفیگ"],
        ["🗑 حذف کانفیگ", "🧹 حذف همه"],
        ["📊 آمار"],
        ["🔙 منوی کاربر"],
    ],
    resize_keyboard=True,
)


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_config_count INTEGER DEFAULT 0,
            last_status TEXT,
            last_status_at TEXT
        )
        """
    )

    conn.commit()
    conn.close()


def save_user(user):
    conn = db()

    conn.execute(
        """
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name
        """,
        (
            user.id,
            user.username,
            user.first_name,
        ),
    )

    conn.commit()
    conn.close()


def is_admin(user_id):
    return user_id == ADMIN_ID


async def is_joined(context, user_id):
    try:
        member = await context.bot.get_chat_member(
            chat_id=CHANNEL,
            user_id=user_id,
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as e:
        logger.warning("Join check failed: %s", e)
        return False


async def require_join(update, context):
    user = update.effective_user

    if is_admin(user.id):
        return True

    if await is_joined(context, user.id):
        return True

    await update.message.reply_text(
        "🔒 عضویت در کانال\n\n"
        "برای استفاده از بات، ابتدا عضو کانال ما شو 👇\n\n"
        "📢 @ByteTunnel\n\n"
        "بعد از عضویت، روی دکمه 📥 دریافت کانفیگ بزن ❤️",
        reply_markup=USER_MENU,
    )

    return False


def extract_configs(text):
    patterns = re.findall(
        r"(?:vless|vmess|trojan|ss)://[^\s<>\"']+",
        text,
        flags=re.IGNORECASE,
    )

    result = []

    for item in patterns:
        item = item.strip("`'\".,;،")

        if item and item not in result:
            result.append(item)

    return result


def rename_config(config):
    """
    فقط قسمت بعد از # را تغییر می‌دهد.
    اطلاعات اتصال کانفیگ تغییر نمی‌کند.
    """

    flag, country = random.choice(COUNTRIES)

    name = f"{flag} {country} | @ByteTunnel"

    base = config.split("#", 1)[0]

    return f"{base}#{quote(name, safe='')}"


def get_configs():
    conn = db()

    rows = conn.execute(
        "SELECT id, config FROM configs ORDER BY id ASC"
    ).fetchall()

    conn.close()

    return rows


def add_configs(configs):
    conn = db()

    added = 0
    duplicate = 0

    for config in configs:
        try:
            conn.execute(
                """
                INSERT INTO configs (config, created_at)
                VALUES (?, ?)
                """,
                (
                    config,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

            added += 1

        except sqlite3.IntegrityError:
            duplicate += 1

    conn.commit()
    conn.close()

    return added, duplicate


def delete_all_configs():
    conn = db()

    cursor = conn.execute(
        "DELETE FROM configs"
    )

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted


def delete_config(config_id):
    conn = db()

    cursor = conn.execute(
        "DELETE FROM configs WHERE id = ?",
        (config_id,),
    )

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted


def split_message(text, limit=3900):
    parts = []

    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)

        if cut < 1:
            cut = limit

        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")

    if text:
        parts.append(text)

    return parts


async def send_all_configs(update, context):
    rows = get_configs()

    if not rows:
        await update.message.reply_text(
            "⚠️ در حال حاضر هیچ کانفیگی موجود نیست.",
            reply_markup=USER_MENU,
        )
        return

    import html

    blocks = []

    for row in rows:
        flag, country = random.choice(COUNTRIES)

        base = row["config"].split("#", 1)[0]
        name = f"{flag} {country} | @ByteTunnel"
        config = f"{base}#{quote(name, safe='')}"

        blocks.append(
            f"<blockquote expandable>"
            f"{flag}\n"
            f"<code>{html.escape(config)}</code>"
            f"</blockquote>"
        )

    header = (
        "⚡ <b>کانفیگ‌های V2Ray</b>\n"
        "📦 <b>لیست کانفیگ‌ها</b>\n\n"
    )

    footer = "\n\n❤️ @ByteTunnel"

    current = header

    for block in blocks:
        if len(current) + len(block) + len(footer) > 3900:
            current += footer

            await update.message.reply_text(
                current,
                parse_mode="HTML",
            )

            current = ""

        current += block + "\n"

    if current:
        current += footer

        await update.message.reply_text(
            current,
            parse_mode="HTML",
        )

    conn = db()
    conn.execute(
        """
        UPDATE users
        SET last_config_count = ?
        WHERE user_id = ?
        """,
        (len(rows), update.effective_user.id),
    )
    conn.commit()
    conn.close()

async def start(update, context):
    save_user(update.effective_user)

    if not await require_join(update, context):
        return

    if is_admin(update.effective_user.id):
        await update.message.reply_text(
            "⚡ به ByteTunnel Config Bot خوش اومدی.\n\n"
            "👑 پنل مدیریت فعال است.",
            reply_markup=ADMIN_MENU,
        )
    else:
        await update.message.reply_text(
            "⚡ به ByteTunnel Config Bot خوش اومدی ❤️\n\n"
            "📥 برای دریافت کانفیگ‌ها از دکمه زیر استفاده کن.",
            reply_markup=USER_MENU,
        )


async def help_user(update, context):
    if not await require_join(update, context):
        return

    await update.message.reply_text(
        "📖 راهنمای ByteTunnel\n\n"
        "📥 دریافت کانفیگ\n"
        "تمام کانفیگ‌های موجود را برایت ارسال می‌کند.\n\n"
        "🌍 کشور هر کانفیگ به‌صورت تصادفی انتخاب می‌شود.\n\n"
        "🟢 وصل شد\n"
        "اگر کانفیگ‌ها وصل شدند، این گزینه را بزن.\n\n"
        "🔴 وصل نشد\n"
        "اگر کانفیگ‌ها وصل نشدند، این گزینه را بزن.\n\n"
        "📢 @ByteTunnel",
        reply_markup=USER_MENU,
    )


async def status_report(update, context, status):
    if not await require_join(update, context):
        return

    user = update.effective_user

    conn = db()

    row = conn.execute(
        """
        SELECT last_config_count
        FROM users
        WHERE user_id = ?
        """,
        (user.id,),
    ).fetchone()

    count = row["last_config_count"] if row else 0

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn.execute(
        """
        UPDATE users
        SET last_status = ?,
            last_status_at = ?
        WHERE user_id = ?
        """,
        (
            status,
            now,
            user.id,
        ),
    )

    conn.commit()
    conn.close()

    username = (
        f"@{user.username}"
        if user.username
        else "ندارد"
    )

    report = (
        "📊 گزارش وضعیت کانفیگ\n\n"
        f"👤 کاربر: {username}\n"
        f"🆔 ID: {user.id}\n"
        f"📦 تعداد کانفیگ: {count}\n"
        f"📌 وضعیت: {status}\n"
        f"🕐 زمان: {now}"
    )

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=report,
        )
    except Exception as e:
        logger.error(
            "Admin report error: %s",
            e,
        )

    await update.message.reply_text(
        "ممنون از بازخورد شما ❤️",
        reply_markup=USER_MENU,
    )


async def add_config_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["admin_action"] = "add"

    await update.message.reply_text(
        "➕ کانفیگ یا لیست کانفیگ‌ها را ارسال کن.\n\n"
        "می‌توانی چند کانفیگ را در یک پیام بفرستی.",
        reply_markup=ReplyKeyboardMarkup(
            [["❌ لغو"]],
            resize_keyboard=True,
        ),
    )


async def delete_config_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    rows = get_configs()

    if not rows:
        await update.message.reply_text(
            "⚠️ هیچ کانفیگی برای حذف وجود ندارد.",
            reply_markup=ADMIN_MENU,
        )
        return

    text = "🗑 حذف کانفیگ\n\n"

    for row in rows:
        text += (
            f"ID {row['id']} → "
            f"{row['config'][:60]}\n"
        )

    text += (
        "\n📝 آیدی کانفیگ موردنظر را ارسال کن."
    )

    context.user_data["admin_action"] = "delete"

    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(
            [["❌ لغو"]],
            resize_keyboard=True,
        ),
    )


async def delete_all_start(update, context):
    if not is_admin(update.effective_user.id):
        return

    rows = get_configs()

    if not rows:
        await update.message.reply_text(
            "⚠️ دیتابیس از قبل خالی است.",
            reply_markup=ADMIN_MENU,
        )
        return

    context.user_data[
        "admin_action"
    ] = "delete_all_confirm"

    await update.message.reply_text(
        f"⚠️ تعداد {len(rows)} کانفیگ حذف خواهد شد.\n\n"
        "برای تأیید بنویس:\n"
        "تایید حذف",
        reply_markup=ReplyKeyboardMarkup(
            [
                ["تایید حذف"],
                ["❌ لغو"],
            ],
            resize_keyboard=True,
        ),
    )


async def stats(update, context):
    if not is_admin(update.effective_user.id):
        return

    conn = db()

    configs = conn.execute(
        "SELECT COUNT(*) AS count FROM configs"
    ).fetchone()["count"]

    users = conn.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()["count"]

    connected = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        WHERE last_status = '🟢 وصل شد'
        """
    ).fetchone()["count"]

    not_connected = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM users
        WHERE last_status = '🔴 وصل نشد'
        """
    ).fetchone()["count"]

    conn.close()

    await update.message.reply_text(
        "📊 آمار بات\n\n"
        f"📦 کانفیگ‌ها: {configs}\n"
        f"👥 کاربران: {users}\n"
        f"🟢 وصل شد: {connected}\n"
        f"🔴 وصل نشد: {not_connected}",
        reply_markup=ADMIN_MENU,
    )


async def handle_admin_action(update, context):
    if not is_admin(update.effective_user.id):
        return False

    action = context.user_data.get(
        "admin_action"
    )

    if not action:
        return False

    text = update.message.text.strip()

    if text == "❌ لغو":
        context.user_data.pop(
            "admin_action",
            None,
        )

        await update.message.reply_text(
            "❌ عملیات لغو شد.",
            reply_markup=ADMIN_MENU,
        )

        return True

    if action == "add":
        configs = extract_configs(text)

        if not configs:
            await update.message.reply_text(
                "⚠️ هیچ کانفیگ معتبری پیدا نشد."
            )
            return True

        added, duplicate = add_configs(
            configs
        )

        context.user_data.pop(
            "admin_action",
            None,
        )

        await update.message.reply_text(
            "✅ کانفیگ‌ها ثبت شدند.\n\n"
            f"➕ اضافه‌شده: {added}\n"
            f"♻️ تکراری: {duplicate}\n"
            f"📦 مجموع: {len(get_configs())}",
            reply_markup=ADMIN_MENU,
        )

        return True

    if action == "delete":
        if not text.isdigit():
            await update.message.reply_text(
                "⚠️ فقط ID عددی کانفیگ را ارسال کن."
            )
            return True

        config_id = int(text)

        deleted = delete_config(
            config_id
        )

        context.user_data.pop(
            "admin_action",
            None,
        )

        if deleted:
            message = (
                f"✅ کانفیگ شماره {config_id} حذف شد."
            )
        else:
            message = (
                f"⚠️ کانفیگ شماره {config_id} پیدا نشد."
            )

        await update.message.reply_text(
            message,
            reply_markup=ADMIN_MENU,
        )

        return True

    if action == "delete_all_confirm":
        if text == "تایید حذف":
            deleted = delete_all_configs()

            context.user_data.pop(
                "admin_action",
                None,
            )

            await update.message.reply_text(
                f"🧹 {deleted} کانفیگ حذف شد.",
                reply_markup=ADMIN_MENU,
            )

            return True

        await update.message.reply_text(
            "⚠️ برای تأیید، دقیقاً بنویس:\n"
            "تایید حذف\n\n"
            "یا «❌ لغو» را بزن."
        )

        return True

    return False


async def message_handler(update, context):
    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    save_user(user)

    if is_admin(user.id):
        handled = await handle_admin_action(
            update,
            context,
        )

        if handled:
            return

        text = update.message.text.strip()

        if text == "➕ افزودن کانفیگ":
            await add_config_start(
                update,
                context,
            )
            return

        if text == "🗑 حذف کانفیگ":
            await delete_config_start(
                update,
                context,
            )
            return

        if text == "🧹 حذف همه":
            await delete_all_start(
                update,
                context,
            )
            return

        if text == "📊 آمار":
            await stats(
                update,
                context,
            )
            return

        if text == "🔙 منوی کاربر":
            await update.message.reply_text(
                "👤 منوی کاربر",
                reply_markup=USER_MENU,
            )
            return

    text = update.message.text.strip()

    if text == "📥 دریافت کانفیگ":
        if not await require_join(
            update,
            context,
        ):
            return

        await send_all_configs(
            update,
            context,
        )
        return

    if text == "📖 راهنما":
        await help_user(
            update,
            context,
        )
        return

    if text == "🟢 وصل شد":
        await status_report(
            update,
            context,
            "🟢 وصل شد",
        )
        return

    if text == "🔴 وصل نشد":
        await status_report(
            update,
            context,
            "🔴 وصل نشد",
        )
        return

    if not await require_join(
        update,
        context,
    ):
        return

    await update.message.reply_text(
        "از دکمه‌های منو استفاده کن 👇",
        reply_markup=USER_MENU,
    )


async def error_handler(update, context):
    logger.error(
        "Update error: %s",
        context.error,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "ByteTunnel Config Bot started."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
