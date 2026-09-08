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

def get_next_url(soup, current_url):
    """البحث عن رابط الفصل التالي"""
    # البحث عن الأزرار أو الروابط التي تحتوي على كلمة 'التالي' أو 'next'
    next_anchor = (
        soup.find("a", text=re.compile(r"(التالي|Next|فصل تالي)", re.I))
        or soup.find("a", class_=re.compile(r"(next|next-chap|next-page)", re.I))
        or soup.find("a", id=re.compile(r"(next|next-chap)", re.I))
    )
    if next_anchor and next_anchor.get("href"):
        next_href = next_anchor["href"]
        if next_href.startswith("http"):
            return next_href
        else:
            # دمج الرابط النسبي مع النطاق الأساسي
            from urllib.parse import urljoin
            return urljoin(current_url, next_href)
    return None

def scrape_chapter_data(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, None, None

        soup = BeautifulSoup(response.text, "html.parser")
        
        # العنوان
        title_tag = soup.find("h1") or soup.find("h2") or soup.find("title")
        title = title_tag.text.strip() if title_tag else "فصل"

        # نص الفصل
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
            if text and len(text) > 5 and not text.startswith("http"):
                text_list.append(text)

        content_text = "\n\n".join(text_list) if text_list else (content_container.text.strip() if content_container else "")
        next_url = get_next_url(soup, url)

        return title, content_text, next_url
    except Exception:
        return None, None, None

def create_multi_chapter_epub(book_title: str, chapters_data: list, filename: str):
    book = epub.EpubBook()
    book.set_title(book_title)
    book.set_language("ar")

    epub_chapters = []
    spine_list = ["nav"]

    for idx, (ch_title, ch_content) in enumerate(chapters_data, start=1):
        ch_file = f"chap_{idx}.xhtml"
        chapter = epub.EpubHtml(title=ch_title, file_name=ch_file, lang="ar")
        
        html_content = f"<div dir='rtl' style='text-align: right; font-family: sans-serif; font-size: 1.1em; line-height: 1.6;'>"
        html_content += f"<h2 style='text-align: center;'>{ch_title}</h2><hr/><br/>"
        for p in ch_content.split("\n\n"):
            html_content += f"<p>{p}</p>"
        html_content += "</div>"
        
        chapter.content = html_content
        book.add_item(chapter)
        epub_chapters.append(chapter)
        spine_list.append(chapter)

    book.toc = tuple(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine_list

    epub.write_epub(filename, book)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! أرسل لي رابط **الفصل الأول** وسأقوم بالانتقال بين الفصول وتجميعها لك في ملف EPUB واحد.\n\n"
        "ملاحظة: يجلب البوت حالياً حتى 20 فصل متتالي في المرة الواحدة لتجنب الحظر وزيادة السرعة."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_url = update.message.text.strip()
    if not current_url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    status_msg = await update.message.reply_text("⏳ جاري بدء جمع الفصول...")

    chapters_collected = []
    max_chapters = 20  # الحد الأقصى للفصول في الطلب الواحد
    count = 0

    while current_url and count < max_chapters:
        count += 1
        await status_msg.edit_text(f"⏳ جاري جلب الفصل ({count}/{max_chapters})...")
        
        title, content, next_url = scrape_chapter_data(current_url)
        if not content or len(content) < 20:
            break

        chapters_collected.append((title, content))
        
        if not next_url or next_url == current_url:
            break
            
        current_url = next_url

    if not chapters_collected:
        await status_msg.edit_text("❌ تعذر استخراج الفصول. يرجى التأكد من الرابط أو بنية الموقع.")
        return

    await status_msg.edit_text(f"📦 تم جمع {len(chapters_collected)} فصل/فصول. جاري تحويلها إلى ملف EPUB...")

    book_main_title = chapters_collected[0][0]
    safe_title = clean_filename(book_main_title)
    file_path = f"{safe_title}.epub"

    try:
        create_multi_chapter_epub(book_main_title, chapters_collected, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file, 
                filename=f"{safe_title}.epub",
                caption=f"📚 تم تجميع {len(chapters_collected)} فصل في ملف واحد بنجاح!"
            )

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status_msg.edit_text(f"حدث خطأ أثناء إنشاء الملف: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("البوت يعمل الآن...")
    app.run_polling()
 
