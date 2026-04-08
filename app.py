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
# Render bepul tarifida 10000 portni afzal ko'radi
PORT           = int(os.environ.get("PORT", 10000))

# ─── Flask web server (Render o'chirib qo'ymasligi uchun) ──────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def index():
    return "Bot status: Online. Flask server is running to prevent idling.", 200

@flask_app.route("/health")
def health():
    return {"status": "ok", "message": "alive"}, 200

# ─── Conversation history ──────────────────────────────────────────────────────
conversation_history: dict = {}
MAX_HISTORY = 20

SYSTEM_PROMPT = """Sen yordamchi AI assistantsan.
- O'zbek, Rus va Ingliz tillarini mukammal bilasan.
- Foydalanuvchi qaysi tilda murojaat qilsa, o'sha tilda javob ber.
- Rasmlarni tahlil qilishda Llama-3.2-Vision imkoniyatlaridan foydalanasan.
- HTML, CSS, JS kodlarini yozishda zamonaviy UI/UX tamoyillariga amal qil.
- Har doim foydali, aniq va xushmuomala bo'l."""

# ─── Groq API Client ───────────────────────────────────────────────────────────
async def get_groq_response(chat_id: int, new_message: dict, model: str = "llama-3.1-70b-versatile") -> str:
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    # Tarixga yangi xabarni qo'shish (agar vision bo'lsa tarixga boshqacha qo'shiladi)
    if isinstance(new_message.get("content"), str):
        conversation_history[chat_id].append(new_message)

    if len(conversation_history[chat_id]) > MAX_HISTORY:
        conversation_history[chat_id] = conversation_history[chat_id][-MAX_HISTORY:]

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Vision xabarlari uchun tarixni yubormaymiz (xotira tejash uchun)
    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}]
    if "vision" in model:
        messages_payload.append(new_message)
    else:
        messages_payload.extend(conversation_history[chat_id])

    payload = {
        "model": model,
        "messages": messages_payload,
        "max_tokens": 4096,
        "temperature": 0.7
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(GROQ_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data  = resp.json()
            reply = data["choices"][0]["message"]["content"]
            
            if "vision" not in model:
                conversation_history[chat_id].append({"role": "assistant", "content": reply})
            return reply
    except Exception as e:
        logger.error(f"Groq API Error: {e}")
        return f"Kechirasiz, Groq API bilan bog'liq xato yuz berdi: {str(e)}"

# ─── HTML Helpers ──────────────────────────────────────────────────────────────
def extract_html(text: str):
    m = re.search(r"    if m:
        code = m.group(1).strip()
        if "<html" in code.lower() or "<!doctype" in code.lower():
            return code
    m2 = re.search(r"(<!DOCTYPE[\s\S]*?</html>|<html[\s\S]*?</html>)", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return None

async def send_html_file(update: Update, html_content: str, filename: str = "index.html"):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", encoding="utf-8", delete=False) as f:
        f.write(html_content)
        tmp_path = f.name
    try:
        with open(tmp_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="Siz so'ragan HTML fayl tayyor! 🚀"
            )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

async def send_long_message(update: Update, text: str):
    if len(text) <= 4096:
        await update.message.reply_text(text)
    else:
        for i in range(0, len(text), 4096):
            await update.message.reply_text(text[i:i+4096])

# ─── Bot Command Handlers ──────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    user = update.effective_user
    msg = (
        f"Assalomu alaykum, {user.first_name}!\n\n"
        "Men Groq AI (Llama 3.1 & 3.2 Vision) asosidagi botman.\n"
        "Nimalar qila olaman?\n"
        "✅ Murakkab suhbatlar qurish\n"
        "✅ Rasmlarni ko'rish va tahlil qilish\n"
        "✅ Kod yozish va HTML fayllar yaratish\n"
        "✅ Fayllarni (txt, py, html) tahlil qilish\n\n"
        "Buyruqlar:\n"
        "/clear - Tarixni tozalash\n"
        "/html [tavsif] - Tezkor HTML yaratish"
    )
    await update.message.reply_text(msg)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversation_history[update.effective_chat.id] = []
    await update.message.reply_text("Suhbat tarixi muvaffaqiyatli tozalandi. ✨")

async def html_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = " ".join(context.args).strip()
    if not args:
        await update.message.reply_text("Iltimos, HTML uchun tavsif bering. Masalan: /html login sahifasi")
        return
    
    await update.message.chat.send_action("upload_document")
    prompt = f"Quyidagi tavsif asosida bitta to'liq zamonaviy HTML/CSS fayl yarat: {args}. Kodni ```html ... ``` bloki ichida ber."
    reply = await get_groq_response(update.effective_chat.id, {"role": "user", "content": prompt})
    html_code = extract_html(reply)
    
    if html_code:
        await send_html_file(update, html_code, "generated.html")
    await send_long_message(update, reply)

# ─── Content Handlers ──────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    
    # HTML so'ralganini aniqlash
    html_keywords = ["html yoz", "html yarat", "html create", "html code"]
    is_html_request = any(kw in text.lower() for kw in html_keywords)
    
    await update.message.chat.send_action("upload_document" if is_html_request else "typing")
    
    reply = await get_groq_response(chat_id, {"role": "user", "content": text})
    html_code = extract_html(reply)
    
    if html_code:
        await send_html_file(update, html_code)
    
    await send_long_message(update, reply)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.chat.send_action("typing")
    
    photo_file = await update.message.photo[-1].get_file()
    async with httpx.AsyncClient() as client:
        resp = await client.get(photo_file.file_path)
        image_b64 = base64.b64encode(resp.content).decode("utf-8")
    
    caption = update.message.caption or "Ushbu rasmda nimalar borligini tushuntirib ber."
    vision_message = {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": caption}
        ]
    }
    
    reply = await get_groq_response(chat_id, vision_message, model="llama-3.2-11b-vision-preview")
    await send_long_message(update, reply)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    # Faqat matnli fayllarni o'qiymiz
    if any(ext in doc.file_name.lower() for ext in [".txt", ".py", ".html", ".css", ".js", ".json"]):
        await update.message.chat.send_action("typing")
        file = await doc.get_file()
        async with httpx.AsyncClient() as client:
            resp = await client.get(file.file_path)
            content = resp.text
            
        prompt = f"Fayl nomi: {doc.file_name}\n\nFayl mazmuni:\n{content[:5000]}\n\nYuqoridagi faylni tahlil qil yoki savolga javob ber: {update.message.caption or 'Tahlil ber'}"
        reply = await get_groq_response(update.effective_chat.id, {"role": "user", "content": prompt})
        await send_long_message(update, reply)
    else:
        await update.message.reply_text("Kechirasiz, faqat matnli fayllarni (txt, py, html, js...) tahlil qila olaman.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Bu yerga qo'shimcha inline tugma mantig'ini qo'shish mumkin

# ─── Execution ─────────────────────────────────────────────────────────────────
def run_flask_server():
    """Flaskni alohida thread'da ishga tushirish"""
    flask_app.run(host="0.0.0.0", port=PORT)

def main():
    if not TELEGRAM_TOKEN or not GROQ_API_KEY:
        logger.critical("Muhit o'zgaruvchilari (TOKEN/API_KEY) topilmadi!")
        return

    # Flaskni fonda ishga tushirish
    threading.Thread(target=run_flask_server, daemon=True).start()
    logger.info("Flask server background thread'da ishga tushdi.")

    # Botni yaratish (asyncio.run ishlatilmaydi, PTB o'zi boshqaradi)
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Handlerlar
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("html", html_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot polling rejimi ishga tushmoqda...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
