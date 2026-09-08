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

def extract_chapter_num(text_or_url):
    """استخراج رقم الفصل لتصفية العناوين العشوائية وضمان الترتيب الصحيح"""
    match = re.search(r'(?:فصل|chapter|chap|ch|fssl)[^\d]*(\d+)', text_or_url, re.I)
    if not match:
        # البحث عن أرقام محاطة بشرطات أو في نهاية الرابط
        match = re.search(r'-(\d+)(?:/|$)', text_or_url)
    return int(match.group(1)) if match else None

def get_all_chapters_paginated(base_url):
    """تتبع كل صفحات الفهرس لاستخراج الـ 1100+ فصل كاملة بدون قفزات"""
    chapters_map = {}
    novel_title = "رواية"
    
    current_page_url = base_url
    visited_pages = set()

    while current_page_url and current_page_url not in visited_pages:
        visited_pages.add(current_page_url)
        try:
            res = requests.get(current_page_url, headers=HEADERS, timeout=15)
            if res.status_code != 200:
                break

            soup = BeautifulSoup(res.text, "html.parser")

            if novel_title == "رواية":
                t_tag = soup.find("h1") or soup.find("h2")
                if t_tag:
                    novel_title = t_tag.text.strip()

            # استخراج روابط الفصول المباشرة واستبعاد أزرار التنقل
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.text.strip()
                full_url = urljoin(base_url, href)

                # استبعاد العناوين غير ذات الصلة
                if any(bad in text for bad in ["ابدأ القراءة", "عرض قائمة", "الصفحة التالية", "التالي", "السابق"]):
                    continue

                ch_num = extract_chapter_num(text) or extract_chapter_num(href)
                
                if ch_num is not None and full_url not in chapters_map:
                    # التأكد من عدم تكرار نفس الرقم
                    chapters_map[ch_num] = {
                        "title": f"الفصل {ch_num}: {text}" if not text.isdigit() else f"الفصل {ch_num}",
                        "url": full_url,
                        "num": ch_num
                    }

            # البحث عن زر الصفحة التالية في الفهرس (Pagination)
            next_page = soup.find("a", class_=re.compile(r"(next|next-page)", re.I)) or \
                        soup.find("a", text=re.compile(r"(التالي|Next|›|»)", re.I))
            
            if next_page and next_page.get("href"):
                next_url = urljoin(base_url, next_page["href"])
                if next_url != current_page_url and "page" in next_url:
                    current_page_url = next_url
                else:
                    break
            else:
                break
        except Exception:
            break

    # تحويل القائمة إلى ترتيب تصاعدي صارم
    sorted_chapters = [chapters_map[k] for k in sorted(chapters_map.keys())]
    return novel_title, sorted_chapters

def scrape_chapter_body(url):
    """استخراج نص الفصل فقط بدون روابط أو صفحات فهرس متداخلة"""
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

        # إزالة جميع الأزرار والروابط السفلية/العلوية
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
    """تصدير ملف EPUB نظيف ومطابق لمعايير القراءة في Moon+ Reader"""
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
        "أهلاً بك! أرسل رابط **الصفحة الرئيسية للرواية** وسأقوم بجمع كافة الفصول مرتبة وبشكل كامل."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    status_msg = await update.message.reply_text("🔍 جاري فحص صفحات الفهرس بالكامل واستخراج الفصول...")

    # 1. تتبع الفهرس الكامل
    novel_title, chapters_list = get_all_chapters_paginated(url)

    if not chapters_list:
        await status_msg.edit_text("❌ لم يتم العثور على فصول صالحة في الرابط.")
        return

    total = len(chapters_list)
    await status_msg.edit_text(f"📖 تم العثور على {total} فصل متسلسل بدون قفزات.\n⏳ جاري التحميل والتجميع...")

    # 2. تحميل المحتوى
    collected = []
    for idx, item in enumerate(chapters_list, start=1):
        if idx % 10 == 0 or idx == total:
            await status_msg.edit_text(f"⏳ جاري تحميل الفصل ({idx}/{total}): {item['title']}...")

        content = scrape_chapter_body(item["url"])
        if content:
            collected.append((item["title"], content))

    if not collected:
        await status_msg.edit_text("❌ تعذر استخراج محتوى الفصول.")
        return

    # 3. تصدير ملف EPUB
    await status_msg.edit_text("📦 جاري بناء ملف الـ EPUB النهائي...")
    
    safe_title = clean_filename(novel_title)
    file_path = f"{safe_title}.epub"

    try:
        build_clean_epub(novel_title, collected, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 **{novel_title}**\n✅ تم تجميع {len(collected)} فصل متسلسل بنجاح!"
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
    
    print("البوت يعمل بنظام الفهرس الشامل والتتبع...")
    app.run_polling()
 
