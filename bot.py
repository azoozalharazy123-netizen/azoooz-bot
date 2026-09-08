import os
import re
import html
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from ebooklib import epub
from flask import Flask
from threading import Thread

# --- 1. سيرفر وهمي لتجاوز فحص المنفذ (Port) في Render المجاني ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is active 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

Thread(target=run_flask).start()
# -------------------------------------------------------------

# جلب التوكين من متغيرات البيئة في Render لأمان الحساب
BOT_TOKEN = os.environ.get("BOT_TOKEN")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def clean_filename(title):
    """تنظيف النصوص لتصلح كاسم ملف أو عنوان"""
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

def sanitize_text(text):
    """تنظيف وتشفير الرموز الخاصة لمنع تلف ملف الـ EPUB"""
    return html.escape(text.strip())

def extract_chapter_number(url_or_title):
    """استخراج رقم الفصل لترتيب الفصول بدقة"""
    match = re.search(r'(?:chapter|fssl|فصل)[^\d]*(\d+)', url_or_title, re.I)
    if not match:
        match = re.search(r'(\d+)', url_or_title)
    return int(match.group(1)) if match else 999999

def scrape_chapter_content(url):
    """استخراج نص الفصل بدون تكرار الـ div والـ p"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return None, None

        soup = BeautifulSoup(response.text, "html.parser")

        # عنوان الفصل
        title_tag = soup.find("h1") or soup.find("h2") or soup.find("title")
        ch_title = title_tag.text.strip() if title_tag else "فصل"

        # تحديد الحاوية الرئيسية بدقة
        container = (
            soup.find("div", class_=re.compile(r"(chapter-content|entry-content|epcontent|reading-content)", re.I))
            or soup.find("article")
            or soup.find("div", id=re.compile(r"(chapter-content|content|chapter-text)", re.I))
        )

        if not container:
            container = soup.find("body")

        # إزالة العناصر الضارة والإعلانات والأزرار من داخل الحاوية
        for unwanted in container.find_all(["script", "style", "iframe", "ins", "nav", "button", "a"]):
            unwanted.decompose()

        # استخراج الفقرات <p> فقط لمنع التكرار الناجم عن الـ <div> المتداخلة
        paragraphs = container.find_all("p")
        text_list = []

        if paragraphs:
            for p in paragraphs:
                txt = p.text.strip()
                # تصفية الإعلانات والنصوص القصيرة جدًا
                if txt and len(txt) > 3 and not txt.startswith("http"):
                    text_list.append(sanitize_text(txt))
        else:
            # إذا لم توجد أوسام <p>، يتم تقسيم النص بناءً على السطور
            raw_text = container.get_text(separator="\n")
            for line in raw_text.split("\n"):
                txt = line.strip()
                if txt and len(txt) > 5:
                    text_list.append(sanitize_text(txt))

        content_text = "<br/><br/>".join(text_list)
        return ch_title, content_text

    except Exception:
        return None, None

def create_epub_book(novel_title, chapters_list, output_filename):
    """إنشاء كتاب EPUB احترافي ومحمي من أخطاء الـ HTML"""
    book = epub.EpubBook()
    book.set_title(novel_title)
    book.set_language("ar")

    epub_chapters = []
    spine = ["nav"]

    for idx, (title, content, ch_num) in enumerate(chapters_list, start=1):
        ch_file = f"chap_{idx}.xhtml"
        chapter = epub.EpubHtml(title=title, file_name=ch_file, lang="ar")
        
        html_body = f"""
        <div dir='rtl' style='text-align: right; font-family: sans-serif; line-height: 1.6;'>
            <h2 style='text-align: center;'>{sanitize_text(title)}</h2>
            <hr/><br/>
            <div>{content}</div>
        </div>
        """
        chapter.content = html_body
        book.add_item(chapter)
        epub_chapters.append(chapter)
        spine.append(chapter)

    book.toc = tuple(epub_chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    epub.write_epub(output_filename, book)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! أرسل لي رابط **فصل الرواية** وسأقوم بجلب الفصول وتنسيقها في كتاب EPUB نظيف ومحدد بدون تكرار."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    status_msg = await update.message.reply_text("⏳ جاري قراءة وتجهيز الفصل...")

    # معالجة الفصل والمحتوى
    title, content = scrape_chapter_content(url)
    if not content:
        await status_msg.edit_text("❌ تعذر استخراج محتوى الفصل. قد تكون بنية الصفحة مختلفة أو محمية.")
        return

    ch_num = extract_chapter_number(url)
    safe_title = clean_filename(title)
    file_path = f"{safe_title}.epub"

    try:
        await status_msg.edit_text("📦 جاري تجميع وتنسيق ملف الـ EPUB...")
        
        # إنشاء الكتاب بحاوية نصوص منظمة
        create_epub_book(title, [(title, content, ch_num)], file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 تم تجهيز الفصل: {title}"
            )

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status_msg.edit_text(f"حدث خطأ أثناء التجميع: {str(e)}")

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("خطأ: BOT_TOKEN غير معرف في متغيرات البيئة!")
    else:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("البوت يعمل الآن بنجاح...")
        app.run_polling()
 
