import os
import re
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from ebooklib import epub
from flask import Flask
from threading import Thread

# --- سيرفر وهمي لتجاوز فحص المنفذ (Port) في Render المجاني ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is active 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

Thread(target=run_flask).start()
# -------------------------------------------------------------

BOT_TOKEN = "8894093871:AAF85mlx2QDVjjAv-oafaYUsoaSGCPPc7NQ"

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title)

def scrape_chapter(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return None, None

    soup = BeautifulSoup(response.text, "html.parser")
    
    # جلب العنوان
    title_tag = soup.find("h1") or soup.find("h2") or soup.find("title")
    title = title_tag.text.strip() if title_tag else "فصل رواية"

    # البحث عن الحاوية الرئيسية لنص الفصل
    content_container = (
        soup.find("div", class_=re.compile(r"(chapter-content|entry-content|text-left|epcontent|reading-content|content)", re.I))
        or soup.find("article")
        or soup.find("div", id=re.compile(r"(chapter-content|content|chapter-text)", re.I))
    )

    if content_container:
        paragraphs = content_container.find_all(["p", "div"])
    else:
        paragraphs = soup.find_all("p")

    text_list = []
    for p in paragraphs:
        text = p.text.strip()
        # تصفية النصوص القصيرة أو الإعلانات
        if text and len(text) > 5 and not text.startswith("http"):
            text_list.append(text)

    # إذا لم يجد فقرات، يأخذ كامل النص من الحاوية مباشرة
    if not text_list and content_container:
        content_text = content_container.text.strip()
    else:
        content_text = "\n\n".join(text_list)

    return title, content_text

def create_epub(title: str, content: str, filename: str):
    book = epub.EpubBook()
    book.set_title(title)
    book.set_language("ar")

    chapter = epub.EpubHtml(title=title, file_name="chap_1.xhtml", lang="ar")
    
    html_content = f"<div dir='rtl' style='text-align: right; font-family: sans-serif; font-size: 1.1em; line-height: 1.6;'>"
    html_content += f"<h1 style='text-align: center;'>{title}</h1><hr/><br/>"
    for p in content.split("\n\n"):
        html_content += f"<p>{p}</p>"
    html_content += "</div>"
    
    chapter.content = html_content
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    book.spine = ["nav", chapter]
    epub.write_epub(filename, book)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل لي رابط الفصل من موقع الروايات وسأقوم بتصديره لك كملف EPUB جاهز للقراءة.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    status_msg = await update.message.reply_text("⏳ جاري جلب الفصل وتحويله...")

    try:
        title, content = scrape_chapter(url)
        if not content or len(content) < 20:
            await status_msg.edit_text("❌ تعذر استخراج محتوى الفصل. قد يكون البناء البرمجي لهذا الموقع مختلفاً.")
            return

        safe_title = clean_filename(title)
        file_path = f"{safe_title}.epub"
        
        create_epub(title, content, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(document=file, filename=f"{safe_title}.epub")

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status_msg.edit_text(f"حدث خطأ أثناء المعالجة: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("البوت يعمل الآن...")
    app.run_polling()
