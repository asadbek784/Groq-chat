import os
import re
import logging
import base64
import tempfile
import asyncio
import threading
import httpx
from flask import Flask, send_from_directory
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"
PORT           = int(os.environ.get("PORT", 5000))

# ─── Flask web server (Render uchun) ──────────────────────────────────────────
flask_app = Flask(__name__, static_folder="static")

@flask_app.route("/")
def index():
    return send_from_directory("static", "index.html")

@flask_app.route("/health")
def health():
    return {"status": "ok", "bot": "running"}, 200

@flask_app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# ─── Conversation history ──────────────────────────────────────────────────────
conversation_history: dict = {}
MAX_HISTORY = 20

SYSTEM_PROMPT = """Sen yordamchi AI assistantsan.
- O'zbek, Rus va Ingliz tillarini bilasan
- Foydalanuvchi qaysi tilda yozsa, o'sha tilda javob ber
- Rasmlarni tahlil qila olasan
- HTML, CSS, JS, Python kodlarini yoza olasan
- HTML kod so'ralsa, faqat to'liq ishlaydigan HTML yoz (CSS va JS ichida)
- Har doim foydali va aniq javob ber"""


# ─── Groq API ──────────────────────────────────────────────────────────────────
async def get_groq_response(chat_id: int, new_message: dict) -> str:
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append(new_message)

    if len(conversation_history[chat_id]) > MAX_HISTORY:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY:]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-70b-versatile",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[chat_id],
        "max_tokens": 4096,
        "temperature": 0.7
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(GROQ_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data  = resp.json()
            reply = data["choices"][0]["message"]["content"]
            conversation_history[chat_id].append({"role": "assistant", "content": reply})
            return reply
    except httpx.HTTPStatusError as e:
        logger.error(f"Groq xatosi: {e.response.status_code} - {e.response.text}")
        return f"Groq API xatosi: {e.response.status_code}"
    except Exception as e:
        logger.error(f"Xato: {e}")
        return f"Xato yuz berdi: {str(e)}"


# ─── HTML yordamchi ────────────────────────────────────────────────────────────
def extract_html(text: str):
    m = re.search(r"```(?:html)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        code = m.group(1).strip()
        if "<html" in code.lower() or "<!doctype" in code.lower():
            return code
    m2 = re.search(r"(<!DOCTYPE[\s\S]*?</html>|<html[\s\S]*?</html>)", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None


async def send_html_file(update: Update, html_content: str, filename: str = "page.html"):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", encoding="utf-8", delete=False
    ) as f:
        f.write(html_content)
        tmp_path = f.name
    try:
        with open(tmp_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="HTML fayl tayyor! Brauzerda oching."
            )
    finally:
        os.unlink(tmp_path)


async def send_long(update: Update, text: str):
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i+4096])


# ─── /start ────────────────────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversation_history[update.effective_chat.id] = []
    web_url = os.environ.get("RENDER_EXTERNAL_URL", "")

    msg = (
        f"Salom, {user.first_name}!\n\n"
        "Men Groq AI (Llama 3.1) bilan ishlayman.\n\n"
        "Imkoniyatlarim:\n"
        "- Suhbat tarixi\n"
        "- Rasmlarni tahlil qilish\n"
        "- HTML fayl qabul qilish va tahlil\n"
        "- HTML fayl yaratib yuborish\n"
        "- Kod yozish (HTML / CSS / JS / Python)\n\n"
        "Buyruqlar:\n"
        "/html [tavsif] - HTML fayl yaratish\n"
        "/clear         - Tarixni tozalash\n"
        "/help          - Yordam\n"
    )
    if web_url:
        msg += f"\nWeb interfeys: {web_url}"

    await update.message.reply_text(msg)


# ─── /help ─────────────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "YORDAM\n\n"
        "Matn:       Shunchaki yozing\n"
        "Rasm:       Rasm yuboring\n"
        "Fayl:       HTML/TXT/CSS/JS fayl yuboring\n\n"
        "HTML yaratish:\n"
        "  /html kalkulyator\n"
        "  html yoz: login sahifasi\n\n"
        "Fayl tuzatish:\n"
        "  HTML fayl + caption: tuzat\n\n"
        "/clear - Suhbatni tozalash"
    )


# ─── /clear ────────────────────────────────────────────────────────────────────
async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversation_history[update.effective_chat.id] = []
    await update.message.reply_text("Suhbat tarixi tozalandi!")


# ─── /html ─────────────────────────────────────────────────────────────────────
async def html_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args    = " ".join(context.args).strip()

    if not args:
        await update.message.reply_text("Tavsif kiriting.\nMasalan: /html chiroyli login sahifasi")
        return

    await update.message.chat.send_action("upload_document")

    prompt = (
        f"Quyidagi tavsif asosida to'liq, ishlaydigan bitta HTML fayl yoz:\n{args}\n\n"
        "Talablar:\n"
        "- Faqat bitta .html fayl (CSS va JS ichida)\n"
        "- Zamonaviy, chiroyli dizayn (gradient, shadow, rounded)\n"
        "- Mobil qurilmaga mos\n"
        "- ```html ... ``` bloki ichiga yoz"
    )

    reply     = await get_groq_response(chat_id, {"role": "user", "content": prompt})
    html_code = extract_html(reply)

    if html_code:
        filename = re.sub(r"[^a-z0-9_]", "_", args[:25].lower()) + ".html"
        await send_html_file(update, html_code, filename)
    else:
        await send_long(update, reply)


# ─── Matn ──────────────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id   = update.effective_chat.id
    user_text = update.message.text
    lower     = user_text.lower()

    html_triggers = ["html yoz", "html fayl", "html kod yoz", "html ber",
                     "html yarat", "сделай html", "напиши html", "make html", "create html"]
    wants_html = any(t in lower for t in html_triggers)

    await update.message.chat.send_action("upload_document" if wants_html else "typing")

    if wants_html:
        prompt = (
            f"{user_text}\n\n"
            "Bitta to'liq HTML fayl yoz (CSS va JS ichida).\n"
            "Zamonaviy, chiroyli, responsive.\n"
            "```html ... ``` bloki ichiga yoz."
        )
        reply     = await get_groq_response(chat_id, {"role": "user", "content": prompt})
        html_code = extract_html(reply)
        if html_code:
            await send_html_file(update, html_code, "page.html")
            clean = re.sub(r"```[\s\S]*?```", "", reply).strip()
            if clean and len(clean) > 10:
                await send_long(update, clean[:1500])
        else:
            await send_long(update, reply)
    else:
        reply = await get_groq_response(chat_id, {"role": "user", "content": user_text})
        await send_long(update, reply)


# ─── Rasm ──────────────────────────────────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.chat.send_action("typing")

    photo = update.message.photo[-1]
    file  = await context.bot.get_file(photo.file_id)

    async with httpx.AsyncClient() as client:
        resp      = await client.get(file.file_path)
        image_b64 = base64.b64encode(resp.content).decode("utf-8")

    caption = update.message.caption or "Bu rasmni batafsil tahlil qilib ber"
    message = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": caption}
        ]
    }

    # Vision uchun alohida model
    if update.effective_chat.id not in conversation_history:
        conversation_history[update.effective_chat.id] = []
    conversation_history[update.effective_chat.id].append(message)

    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[chat_id],
        "max_tokens": 2048,
        "temperature": 0.7
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp  = await client.post(GROQ_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"]
            conversation_history[chat_id].append({"role": "assistant", "content": reply})
    except Exception as e:
        reply = f"Rasm tahlil xatosi: {e}"

    await send_long(update, reply)


# ─── Fayl ──────────────────────────────────────────────────────────────────────
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id   = update.effective_chat.id
    document  = update.message.document
    file_name = document.file_name or "fayl"
    mime_type = document.mime_type or ""
    ext       = os.path.splitext(file_name)[1].lower()

    allowed_types = ["text/html","text/plain","text/css","text/javascript",
                     "application/json","text/x-python","application/x-python-code"]
    allowed_exts  = [".html",".htm",".txt",".css",".js",".json",".py",".md"]

    if mime_type not in allowed_types and ext not in allowed_exts:
        await update.message.reply_text(
            "Qo'llab-quvvatlanmagan fayl.\nQabul: HTML, TXT, CSS, JS, JSON, PY, MD"
        )
        return

    await update.message.chat.send_action("typing")
    file = await context.bot.get_file(document.file_id)

    async with httpx.AsyncClient() as client:
        resp = await client.get(file.file_path)
        try:    content = resp.content.decode("utf-8")
        except: content = resp.content.decode("latin-1")

    if len(content) > 50000:
        content = content[:50000] + "\n\n... [qisqartirildi]"

    caption   = update.message.caption or f"Bu {ext} faylni tahlil qilib ber"
    lang      = ext[1:] if ext else "html"
    fix_words = ["tuzat","fix","исправь","o'zgartir","update","edit","to'g'irla"]
    wants_fix = any(w in caption.lower() for w in fix_words)

    if wants_fix:
        await update.message.chat.send_action("upload_document")
        prompt    = f"{caption}\n\n```{lang}\n{content}\n```\n\nTuzatilgan to'liq faylni ```html ... ``` ichida yoz."
        reply     = await get_groq_response(chat_id, {"role": "user", "content": prompt})
        html_code = extract_html(reply)
        if html_code:
            await send_html_file(update, html_code, "tuzatilgan_" + file_name)
            clean = re.sub(r"```[\s\S]*?```", "", reply).strip()
            if clean and len(clean) > 10:
                await send_long(update, clean[:1200])
        else:
            await send_long(update, reply)
    else:
        prompt    = f"{caption}\n\n```{lang}\n{content}\n```"
        reply     = await get_groq_response(chat_id, {"role": "user", "content": prompt})
        html_code = extract_html(reply)
        clean_reply = re.sub(r"```[\s\S]*?```", "", reply).strip()

        if html_code and ext in [".html", ".htm"]:
            key = f"html_{update.message.message_id}"
            context.bot_data[key] = html_code
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("HTML fayl sifatida yuklab olish",
                                     callback_data=f"sendhtml:{update.message.message_id}")
            ]])
            await send_long(update, clean_reply or "Tahlil tayyor!")
            await update.message.reply_text("Javobdan HTML fayl yaratib beraymi?", reply_markup=keyboard)
        else:
            await send_long(update, reply)


# ─── Inline tugma ──────────────────────────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("sendhtml:"):
        msg_id    = query.data.split(":")[1]
        html_code = context.bot_data.get(f"html_{msg_id}")
        if html_code:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".html", encoding="utf-8", delete=False) as f:
                f.write(html_code); tmp = f.name
            try:
                with open(tmp, "rb") as f:
                    await query.message.reply_document(document=f, filename="output.html",
                                                       caption="HTML fayl tayyor!")
            finally:
                os.unlink(tmp)
        else:
            await query.message.reply_text("Fayl topilmadi.")


# ─── Bot ishga tushirish ───────────────────────────────────────────────────────
async def run_bot():
    if not TELEGRAM_TOKEN or not GROQ_API_KEY:
        logger.error("TELEGRAM_TOKEN yoki GROQ_API_KEY topilmadi!")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  start_command))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("clear",  clear_command))
    app.add_handler(CommandHandler("html",   html_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO,        handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    logger.info("Bot ishga tushdi!")
    await app.run_polling(drop_pending_updates=True)


# ─── Flask alohida thread'da ───────────────────────────────────────────────────
def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


# ─── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Flask ni background thread'da ishga tushir
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Web server port {PORT} da ishga tushdi!")

    # Bot asosiy thread'da ishlaydi
    asyncio.run(run_bot())
