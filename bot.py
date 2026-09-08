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
from urllib.parse import urljoin

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

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8894093871:AAF85mlx2QDVjjAv-oafaYUsoaSGCPPc7NQ")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

def extract_chapters_from_index(main_url):
    """استخراج عنوان الرواية ورابط جميع الفصول من الصفحة الرئيسية"""
    try:
        response = requests.get(main_url, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            return None, []

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. استخراج اسم الرواية
        novel_title_tag = soup.find("h1") or soup.find("h2")
        novel_title = novel_title_tag.text.strip() if novel_title_tag else "رواية"

        # 2. البحث عن الحاوية المسؤولة عن قائمة الفصول (Chapter List / Table of Contents)
        chapter_links = []
        
        # استهداف الحاويات الشائعة لفهارس الفصول في مواقع الروايات
        toc_container = (
            soup.find("div", class_=re.compile(r"(chapter-list|eplist|chapters|index|table-of-contents)", re.I))
            or soup.find("ul", class_=re.compile(r"(chapter-list|eplist|chapters)", re.I))
            or soup
        )

        for a_tag in toc_container.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.text.strip()
            
            # فلترة الروابط للتأكد من أنها روابط فصولوليست روابط أقسام أو صفحات أخرى
            if re.search(r'(chapter|fssl|فصل|\d+)', href, re.I) or re.search(r'(فصل|Chapter)', text, re.I):
                full_url = urljoin(main_url, href)
                if full_url not in [c['url'] for c in chapter_links]:
                    chapter_links.append({"title": text or "فصل", "url": full_url})

        return novel_title, chapter_links
    except Exception:
        return None, []

def scrape_single_chapter(url):
    """كشط وتنظيف نص الفصل الواحد"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        container = (
            soup.find("div", class_=re.compile(r"(entry-content|epcontent|reading-content|chapter-content|content)", re.I))
            or soup.find("article")
        )

        if not container:
            container = soup.find("body")

        # إزالة العناصر غير المرغوبة (إعلانات، أزرار، نصوص سفلية)
        for unwanted in container.find_all(["script", "style", "iframe", "ins", "button", "nav"]):
            unwanted.decompose()

        paragraphs = container.find_all("p")
        text_list = []

        if paragraphs:
            for p in paragraphs:
                txt = p.text.strip()
                if txt and len(txt) > 3 and not txt.startswith("http"):
                    text_list.append(html.escape(txt))
        else:
            raw_text = container.get_text(separator="\n")
            for line in raw_text.split("\n"):
                txt = line.strip()
                if txt and len(txt) > 5:
                    text_list.append(html.escape(txt))

        return "<br/><br/>".join(text_list)
    except Exception:
        return None

def build_full_epub(novel_title, chapters_data, output_path):
    """تجميع الفصول في ملف EPUB واحد مع جدول محتويات متكامل"""
    book = epub.EpubBook()
    book.set_title(novel_title)
    book.set_language("ar")

    epub_chapters = []
    spine = ["nav"]

    for idx, (ch_title, ch_content) in enumerate(chapters_data, start=1):
        ch_file = f"chap_{idx}.xhtml"
        chapter = epub.EpubHtml(title=ch_title, file_name=ch_file, lang="ar")
        
        html_body = f"""
        <div dir='rtl' style='text-align: right; font-family: sans-serif; line-height: 1.6;'>
            <h2 style='text-align: center;'>{html.escape(ch_title)}</h2>
            <hr/><br/>
            <div>{ch_content}</div>
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

    epub.write_epub(output_path, book)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! أرسل رابط **الصفحة الرئيسية للرواية** (صفحة الفهرس/قائمة الفصول) وسأقوم بسحب جميع الفصول وتجميعها في ملف EPUB واحد تماماً مثل WebToEpub."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    status_msg = await update.message.reply_text("🔍 جاري قراءة فهرس الرواية واستخراج قائمة الفصول...")

    # 1. جلب قائمة الفصول
    novel_title, chapters_list = extract_chapters_from_index(url)

    if not chapters_list:
        await status_msg.edit_text("❌ لم يتم العثور على قائمة الفصول في هذا الرابط. تأكد من إرسال رابط الصفحة الرئيسية للرواية.")
        return

    total_chapters = len(chapters_list)
    await status_msg.edit_text(f"📖 تم العثور على {total_chapters} فصل/فصول في «{novel_title}».\n⏳ جاري تحميل وتحويل الفصول...")

    # 2. كشط محتوى كل فصل بالتتابع
    collected_chapters = []
    for idx, item in enumerate(chapters_list, start=1):
        # تحديث الرسالة كل 5 فصول لإظهار التقدم للمستخدم
        if idx % 5 == 0 or idx == total_chapters:
            await status_msg.edit_text(f"⏳ جاري معالجة الفصل ({idx}/{total_chapters})...")

        content = scrape_single_chapter(item["url"])
        if content:
            collected_chapters.append((item["title"], content))

    if not collected_chapters:
        await status_msg.edit_text("❌ تعذر استخراج محتوى الفصول. قد تكون الصفحة محصنة أو مغلقة.")
        return

    # 3. بناء ملف EPUB
    await status_msg.edit_text("📦 جاري تجميع الرواية وإنشاء ملف الـ EPUB...")
    
    safe_title = clean_filename(novel_title)
    file_path = f"{safe_title}.epub"

    try:
        build_full_epub(novel_title, collected_chapters, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 **{novel_title}**\n✅ تم تجميع {len(collected_chapters)} فصل بنجاح!"
            )

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status_msg.edit_text(f"حدث خطأ أثناء التجميع: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("البوت يعمل بأسلوب WebToEpub...")
    app.run_polling()
 
