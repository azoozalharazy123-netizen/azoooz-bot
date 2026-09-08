import os
import re
import html
import asyncio
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from ebooklib import epub
from flask import Flask
from threading import Thread
from playwright.async_api import async_playwright

# --- سيرفر وهمي لتجاوز فحص المنفذ في Render ---
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

def clean_filename(title):
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()

async def get_novel_data_with_playwright(url):
    """استخدام متصفح حقيقي لتجاوز الحماية وتحميل كافة الفصول الديناميكية"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # فتح الصفحة والانتظار حتى يتم تحميل العناصر الديناميكية
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # محاكاة التمرير لأسفل الصفحة لتحفيز تحميل الفصول (Lazy Loading)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(3)

            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")

            # استخراج العنوان
            title_tag = soup.find("h1") or soup.find("h2")
            novel_title = title_tag.text.strip() if title_tag else "رواية"

            chapters_dict = {}
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.text.strip()
                
                # استخراج أرقام الفصول
                match = re.search(r'(?:فصل|chapter|fssl)[^\d]*(\d+)', text, re.I) or re.search(r'-\d+', href)
                if match:
                    num_match = re.search(r'\d+', match.group(0))
                    if num_match:
                        ch_num = int(num_match.group(0))
                        full_url = href if href.startswith("http") else f"https://cenele.com{href}"
                        
                        if ch_num not in chapters_dict and not any(b in text for b in ["ابدأ", "عرض", "التالي"]):
                            chapters_dict[ch_num] = {
                                "title": f"الفصل {ch_num}",
                                "url": full_url,
                                "num": ch_num
                            }

            await browser.close()
            sorted_chapters = [chapters_dict[k] for k in sorted(chapters_dict.keys())]
            return novel_title, sorted_chapters

        except Exception as e:
            await browser.close()
            return "رواية", []

async def scrape_chapter_content(url):
    """جلب نص الفصل بواسطة Playwright لتجاوز السكربتات والإعلانات"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            content = await page.content()
            await browser.close()

            soup = BeautifulSoup(content, "html.parser")
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
            await browser.close()
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
        "أهلاً بك! أرسل رابط الرواية وسيتم تشغيل متصفح خفي لقراءة الفهرس كاملاً وتجميع الفصول."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().split()
    url = text[0]

    if not url.startswith("http"):
        await update.message.reply_text("يرجى إرسال رابط صحيح.")
        return

    status_msg = await update.message.reply_text("🌐 جاري تشغيل المتصفح الخفي وتجاوز حماية الصفحة...")

    novel_title, all_chapters = await get_novel_data_with_playwright(url)

    if not all_chapters:
        await status_msg.edit_text("❌ لم يتم العثور على فصول. قد يحتاج الموقع إلى إعدادات إضافية.")
        return

    total = len(all_chapters)
    await status_msg.edit_text(f"📖 تم العثور على {total} فصل متسلسل.\n⏳ جاري تحميل المحتوى...")

    collected = []
    for idx, ch in enumerate(all_chapters, start=1):
        if idx % 5 == 0 or idx == total:
            await status_msg.edit_text(f"⏳ جاري معالجة: {idx}/{total}\n{ch['title']}")

        content = await scrape_chapter_content(ch['url'])
        if content:
            collected.append((ch['title'], content))

    if not collected:
        await status_msg.edit_text("❌ تعذر استخراج المحتوى.")
        return

    await status_msg.edit_text("📦 جاري إنشاء ملف EPUB...")
    
    safe_title = clean_filename(novel_title)
    file_path = f"{safe_title}.epub"

    try:
        build_epub(novel_title, collected, file_path)

        with open(file_path, "rb") as file:
            await update.message.reply_document(
                document=file,
                filename=f"{safe_title}.epub",
                caption=f"📚 **{novel_title}**\n✅ تم التجميع بنجاح!"
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
    
    print("البوت يعمل بواسطة Playwright...")
    app.run_polling()
