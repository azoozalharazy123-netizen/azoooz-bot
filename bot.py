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

# --- سيرفر وهمي لتجاوز فحص المنفذ (Port) في Render ---
web_app = Flask('')

@web_app.route('/')
def home():
    return "Bot is active 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

Thread(target=run_flask).start()
# ---------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8894093871:AAF85mlx2QDVjjAv-oafaYUsoaSGCPPc7NQ")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

def get_all_chapters_direct(main_url):
    """سحب جميع الفصول من الفهرس وتنظيف العناوين والترتيب المباشر"""
    try:
        res = requests.get(main_url, headers=HEADERS, timeout=20)
        if res.status_code != 200:
            return "رواية", []

        soup = BeautifulSoup(res.text, "html.parser")

        # عنوان الرواية
        t_tag = soup.find("h1") or soup.find("h2")
        novel_title = t_tag.text.strip() if t_tag else "رواية"

        chapters_dict = {}

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.text.strip()
            
            # فلترة الروابط لاستخراج رقم الفصل الحقيقي فقط
            match = re.search(r'(?:فصل|chapter|fssl)[^\d]*(\d+)', text, re.I) or re.search(r'(?:فصل|chapter|fssl)[^\d]*(\d+)', href, re.I)
            
            if match:
                ch_num = int(match.group(1))
                full_url = urljoin(main_url, href)
                
                # تجاهل الروابط المكررة أو أزرار التنقل العامة
                if ch_num not in chapters_dict and not any(bad in text for bad in ["ابدأ", "عرض", "التالي", "السابق"]):
                    chapters_dict[ch_num] = {
                        "title": f"الفصل {ch_num}",
                        "url": full_url,
                        "num": ch_num
                    }

        # ترتيب الفصول تصاعدياً من 1 إلى الأخير
        sorted_chapters = [chapters_dict[k] for k in sorted(chapters_dict.keys())]
        return novel_title, sorted_chapters

    except Exception:
        return "رواية", []

def scrape_chapter_content(url):
    """استخراج وجرف متن الفصل فقط دون أزرار أو روابط خارجية"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        container = (
            soup.find("div", class_=re.compile(r"(entry-content|epcontent|reading-content|chapter-content|content)", re.I))
            or soup.find("article")
        )

        if not container:
            container = soup.find("body")

        # إزالة عناصر الإعلانات والروابط والسكربتات
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

def build_epub(novel_title, chapters, output_path):
    book = epub.EpubBook()
    book.set_title(novel_title)
    book.set_language("ar")

    epub_chapters = []
    spine = ["nav"]

    for idx, (ch_title, ch_content) in enumerate(chapters, start=1):
        ch_file = f"chap_{idx}.xhtml"
        chapter = epub.EpubHtml(title=ch_title, file_name=ch_file, lang="ar")
        
        html_body = f"""
        <div dir='rtl' style='text-align: right; font-family: sans-serif; line-height: 1.8; font-size: 1.1em;'>
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
        "أهلاً بك! أرسل رابط الرواية وسيتم سحب جميع الفصول وترتيبها تلقائياً من الفصل الأول.\n\n"
        "💡 **لتحديد نطاق فصول معينة (مثال من 1 إلى 100):**\n"
        "أرسل الرابط ومعه البداية والنهاية مثل:\n"
        "`https://cenele.com/cont/my-longevity-simulation/ 1 100`"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().split()
    url = text[0]
    
    start_ch, end_ch = None, None
    if len(text) >= 3:
        try:
            start_ch = int(text[1])
            end_ch = int(text[2])
        except ValueError:
            pass

    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح يبدأ بـ http.")
        return

    status_msg = await update.message.reply_text("🔍 جاري جلب الفهرس وترتيب الفصول تصاعدياً...")

    novel_title, all_chapters = get_all_chapters_direct(url)

    if not all_chapters:
        await status_msg.edit_text("❌ تعذر العثور على روابط الفصول في الصفحة.")
        return

    # تطبيق تحديد النطاق إن وُجد
    if start_ch and end_ch:
        all_chapters = [c for c in all_chapters if start_ch <= c['num'] <= end_ch]

    total = len(all_chapters)
    await status_msg.edit_text(f"📖 تم العثور على {total} فصل.\n⏳ جاري تحميل النصوص وتجهيز الـ EPUB...")

    collected = []
    for idx, ch in enumerate(all_chapters, start=1):
        if idx % 10 == 0 or idx == total:
            pct = int((idx / total) * 100)
            await status_msg.edit_text(f"⏳ جاري التحميل: {pct}% ({idx}/{total})\n{ch['title']}")

        content = scrape_chapter_content(ch['url'])
        if content:
            collected.append((ch['title'], content))

    if not collected:
        await status_msg.edit_text("❌ تعذر استخراج المحتوى.")
        return

    await status_msg.edit_text("📦 جاري ضغط وإنشاء ملف EPUB...")
    
    safe_title = clean_filename(novel_title)
    file_path = f"{safe_title}.epub"

    try:
        build_epub(novel_title, collected, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 **{novel_title}**\n✅ تم تجميع {len(collected)} فصل بنجاح!"
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
    
    print("البوت يعمل بشكل مباشر...")
    app.run_polling()
 
