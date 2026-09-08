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

def extract_chapter_num(title_or_url):
    """استخراج رقم الفصل بدقة للترتيب التصاعدي"""
    match = re.search(r'(?:فصل|chapter|fssl)[^\d]*(\d+)', title_or_url, re.I)
    if not match:
        match = re.search(r'(\d+)', title_or_url)
    return int(match.group(1)) if match else 999999

def get_all_chapter_links(main_url):
    """استخراج قائمة جميع الفصول وترتيبها من 1 إلى الأخير"""
    try:
        response = requests.get(main_url, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            return None, []

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. عنوان الرواية
        novel_title_tag = soup.find("h1") or soup.find("h2")
        novel_title = novel_title_tag.text.strip() if novel_title_tag else "رواية"

        # 2. جمع كل الروابط الشبيهة بالفصول
        all_links = []
        seen_urls = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.text.strip()
            
            # فحص ما إذا كان الرابط يخص فصل
            if re.search(r'(فصل|chapter|fssl)', href, re.I) or re.search(r'(فصل|Chapter)', text, re.I):
                full_url = urljoin(main_url, href)
                if full_url not in seen_urls and not full_url.endswith(('/cont/', '/novel/')):
                    seen_urls.add(full_url)
                    ch_num = extract_chapter_num(text) if extract_chapter_num(text) != 999999 else extract_chapter_num(href)
                    all_links.append({
                        "title": text or f"فصل {ch_num}",
                        "url": full_url,
                        "num": ch_num
                    })

        # 3. ترتيب الفصول تصاعدياً (من الفصل 1 إلى الأخير)
        all_links.sort(key=lambda x: x["num"])

        return novel_title, all_links
    except Exception:
        return None, []

def scrape_chapter_body(url):
    """استخراج نص الفصل فقط بدون إعلانات أو روابط متداخلة"""
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

        # إزالة العناصر والأزرار والإعلانات الشائبة
        for unwanted in container.find_all(["script", "style", "iframe", "ins", "button", "nav", "a"]):
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

def build_clean_epub(novel_title, chapters_data, output_path):
    """تنسيق وإنشاء ملف EPUB بأسلوب المجلات بدون خطوط أرقام ملونة فوق النص"""
    book = epub.EpubBook()
    book.set_title(novel_title)
    book.set_language("ar")

    epub_chapters = []
    spine = ["nav"]

    for idx, (ch_title, ch_content) in enumerate(chapters_data, start=1):
        ch_file = f"chap_{idx}.xhtml"
        chapter = epub.EpubHtml(title=ch_title, file_name=ch_file, lang="ar")
        
        html_body = f"""
        <div dir='rtl' style='text-align: right; font-family: sans-serif; line-height: 1.8; font-size: 1.1em;'>
            <h2 style='text-align: center; color: #333;'>{html.escape(ch_title)}</h2>
            <hr style='border: 0; height: 1px; background: #ccc; margin-bottom: 20px;'/>
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
        "أهلاً بك! أرسل رابط **الصفحة الرئيسية للرواية** وسأقوم باستخراج جميع الفصول وتجميعها مرتبة من الفصل الأول تصاعدياً."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    status_msg = await update.message.reply_text("🔍 جاري فحص الفهرس وترتيب الفصول تصاعدياً...")

    # 1. استخراج الفصول
    novel_title, chapters_list = get_all_chapter_links(url)

    if not chapters_list:
        await status_msg.edit_text("❌ لم يتم العثور على قائمة الفصول في هذا الرابط.")
        return

    total_chapters = len(chapters_list)
    await status_msg.edit_text(f"📖 تم اكتشاف {total_chapters} فصل/فصول.\n⏳ جاري التحميل والترتيب من الفصل الأول...")

    # 2. تحميل محتوى كل فصل
    collected = []
    for idx, item in enumerate(chapters_list, start=1):
        if idx % 5 == 0 or idx == total_chapters:
            await status_msg.edit_text(f"⏳ جاري معالجة الفصل ({idx}/{total_chapters}): {item['title']}...")

        content = scrape_chapter_body(item["url"])
        if content:
            collected.append((item["title"], content))

    if not collected:
        await status_msg.edit_text("❌ تعذر جلب محتوى الفصول.")
        return

    # 3. تصدير ملف EPUB
    await status_msg.edit_text("📦 جاري تنقيح الملف وإنشاء الـ EPUB...")
    
    safe_title = clean_filename(novel_title)
    file_path = f"{safe_title}.epub"

    try:
        build_clean_epub(novel_title, collected, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 **{novel_title}**\n✅ تم التجميع بنجاح من الفصل الأول! (إجمالي {len(collected)} فصل)"
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
    
    print("البوت يعمل بالترتيب التصاعدي النظيف...")
    app.run_polling()
 
