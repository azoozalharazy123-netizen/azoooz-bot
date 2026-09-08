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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

def get_chapters_via_wp_api(base_url):
    """جلب قائمة جميع الفصول مباشرة من الـ API الخفي للموقع بدقة 100%"""
    try:
        domain = re.match(r'https?://[^/]+', base_url).group(0)
        # استخراج اسم الرواية/الـ Slug من الرابط
        slug_match = re.search(r'/cont/([^/]+)', base_url)
        if not slug_match:
            return "رواية", []
        
        novel_slug = slug_match.group(1)
        api_url = f"{domain}/wp-json/wp/v2/posts?per_page=100&page="
        
        all_chapters = []
        page = 1
        
        while True:
            res = requests.get(f"{api_url}{page}", headers=HEADERS, timeout=10)
            if res.status_code != 200:
                break
            
            posts = res.json()
            if not posts:
                break
                
            for post in posts:
                if novel_slug in post.get('link', ''):
                    title = BeautifulSoup(post['title']['rendered'], "html.parser").text.strip()
                    num_match = re.search(r'(\d+)', title)
                    num = int(num_match.group(1)) if num_match else 9999
                    
                    all_chapters.append({
                        "title": title,
                        "url": post['link'],
                        "num": num
                    })
            page += 1

        # ترتيب الفصول من الفصل 1 تصاعدياً
        all_chapters.sort(key=lambda x: x["num"])
        novel_title = novel_slug.replace('-', ' ').title()
        
        return novel_title, all_chapters
    except Exception:
        return "رواية", []

def scrape_chapter_clean(url):
    """استخراج نص الفصل وتنظيفه تماماً من أي إعلانات أو أزرار"""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")
        container = soup.find("div", class_=re.compile(r"(entry-content|epcontent|reading-content|chapter-content)", re.I)) or soup.find("article")

        if not container:
            container = soup.find("body")

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
        "أهلاً بك! أرسل لي رابط الصفحة الرئيسية للرواية وسأستخرج قائمة الفصول كاملاً بأسلوب الـ API السريع.\n\n"
        "💡 **المميزات الجديدة:**\n"
        "1. استخراج الـ 1100+ فصل كاملة بطلب واحد.\n"
        "2. لتنزيل أجزاء محددة (مثل أول 50 فصل)، أرسل الرابط متبوعاً بـ النطاق مثلاً:\n"
        "`https://cenele.com/cont/my-longevity-simulation/ 1 50`"
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
        await update.message.reply_text("يرجى إرسال رابط صحيح.")
        return

    status_msg = await update.message.reply_text("⚡ جاري الاتصال بالـ API واستخراج قائمة الفصول كاملة...")

    novel_title, all_chapters = get_chapters_via_wp_api(url)

    if not all_chapters:
        await status_msg.edit_text("❌ لم ينجح الاتصال بالـ API الخاص بالموقع.")
        return

    # تطبيق تحديد نطاق الفصول إذا أرسله المستخدم
    if start_ch and end_ch:
        all_chapters = [c for c in all_chapters if start_ch <= c['num'] <= end_ch]

    total = len(all_chapters)
    await status_msg.edit_text(f"📖 تم جلب {total} فصل متسلسل.\n⏳ جاري التحميل وتجهيز ملف EPUB...")

    collected = []
    for idx, ch in enumerate(all_chapters, start=1):
        if idx % 10 == 0 or idx == total:
            pct = int((idx / total) * 100)
            await status_msg.edit_text(f"⏳ جاري التحميل: {pct}% ({idx}/{total})\nالفصل: {ch['title']}")

        content = scrape_chapter_clean(ch['url'])
        if content:
            collected.append((ch['title'], content))

    if not collected:
        await status_msg.edit_text("❌ تعذر استخراج المحتوى.")
        return

    await status_msg.edit_text("📦 جاري ضغط وتنسيق ملف الـ EPUB...")
    
    safe_title = clean_filename(novel_title)
    file_path = f"{safe_title}.epub"

    try:
        build_epub(novel_title, collected, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 **{novel_title}**\n✅ تم تجميع {len(collected)} فصل بنجاح بأسلوب الـ API!"
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
    
    print("البوت يعمل بالـ API الخفي...")
    app.run_polling()
 
