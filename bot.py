import os
import json
import random
import datetime
from zoneinfo import ZoneInfo
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
from telegram import Update

TOKEN = os.environ.get("8894093871:AAFK8wEhpMXf5y-ofZtwqpPCEXC3QM3BkJ4", "ضع_رمزك_هنا_مؤقتاً")
RIYADH = ZoneInfo("Asia/Riyadh")
DATA_FILE = "data.json"

SCHEDULE = {
    0: "مفردات: 10 كلمات جديدة + مراجعة",
    1: "قواعد: درس قصير + تمارين",
    2: "استماع: 15 دقيقة بودكاست",
    3: "محادثة: جمل يومية",
    4: "قراءة: مقال قصير",
    5: "مراجعة أسبوعية شاملة",
    6: "راحة / فيلم إنجليزي",
}
DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

WORDS = [
    ("improve", "يُحسّن", "to make something better"),
    ("achieve", "يُحقّق", "to succeed in doing something"),
    ("effort", "جهد", "hard work to do something"),
    ("habit", "عادة", "something you do regularly"),
    ("review", "يُراجع", "to study again"),
    ("fluent", "طليق", "able to speak easily"),
    ("vocabulary", "مفردات", "words you know"),
    ("practice", "يتمرّن", "to do repeatedly to improve"),
    ("confidence", "ثقة", "belief in yourself"),
    ("goal", "هدف", "something you aim for"),
]

MOTIVATION = [
    "استمر، كل يوم خطوة أقرب للطلاقة! 💪",
    "اللغة تُبنى بالتكرار، لا بالكمال. 🌱",
    "15 دقيقة يوميًا أفضل من 3 ساعات مرة بالأسبوع. ⏳",
    "اليوم اللي تتعلم فيه كلمة جديدة، ما راح يضيع. 📖",
    "لا تقارن نفسك بالآخرين، قارن نفسك بأمس. 🚀",
]

# ---------- حفظ/تحميل البيانات ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(data, chat_id):
    cid = str(chat_id)
    if cid not in data:
        data[cid] = {
            "time": "19:00",
            "tasks": [],
            "streak": 0,
            "last_check": "",
            "start_date": datetime.datetime.now(RIYADH).strftime("%Y-%m-%d"),
            "morning": False,
        }
    return data[cid]

# ---------- المهام المجدولة ----------
async def remind_english(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    data = load_data()
    user = get_user(data, chat_id)
    today = datetime.datetime.now(RIYADH).strftime("%Y-%m-%d")

    if user["last_check"] != today:
        user["streak"] += 1
        user["last_check"] = today
        save_data(data)

    weekday = datetime.datetime.now(RIYADH).weekday()
    tasks_text = ""
    if user["tasks"]:
        tasks_text = "\n\n📌 مهامك:\n" + "\n".join(f"{i+1}. {t}" for i, t in enumerate(user["tasks"]))

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📚 حان وقت دراسة الإنجليزية!\n\n"
            f"خطة اليوم ({DAYS[weekday]}):\n{SCHEDULE[weekday]}"
            f"{tasks_text}\n\n"
            f"🔥 استمراريتك: {user['streak']} يوم"
        )
    )

async def morning_reminder(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=f"☀️ صباح الخير!\n{random.choice(MOTIVATION)}"
    )

# ---------- استعادة التذكيرات بعد إعادة التشغيل ----------
async def restore_jobs(app: Application):
    data = load_data()
    for cid, user in data.items():
        try:
            chat_id = int(cid)
        except ValueError:
            continue

        # تذكير الدراسة
        h, m = map(int, user.get("time", "19:00").split(":"))
        app.job_queue.run_daily(
            remind_english,
            time=datetime.time(hour=h, minute=m, tzinfo=RIYADH),
            chat_id=chat_id,
            name=f"daily_{chat_id}"
        )

        # التذكير الصباحي (إن كان مفعلاً)
        if user.get("morning"):
            app.job_queue.run_daily(
                morning_reminder,
                time=datetime.time(hour=8, minute=0, tzinfo=RIYADH),
                chat_id=chat_id,
                name=f"morning_{chat_id}"
            )

# ---------- الأوامر ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = load_data()
    user = get_user(data, chat_id)
    save_data(data)

    for job in context.job_queue.get_jobs_by_name(f"daily_{chat_id}"):
        job.schedule_removal()

    h, m = map(int, user["time"].split(":"))
    context.job_queue.run_daily(
        remind_english,
        time=datetime.time(hour=h, minute=m, tzinfo=RIYADH),
        chat_id=chat_id,
        name=f"daily_{chat_id}"
    )
    await update.message.reply_text(
        f"✅ تم تفعيل التذكير اليومي الساعة {user['time']} بتوقيت السعودية.\n\n"
        "الأوامر المتاحة:\n"
        "/start - تفعيل التذكير\n"
        "/stop - إيقاف التذكير\n"
        "/schedule - عرض الخطة الأسبوعية\n"
        "/settime HH:MM - تغيير وقت التذكير\n"
        "/addtask نص - إضافة مهمة\n"
        "/tasks - عرض مهامك\n"
        "/done رقم - حذف مهمة أنجزتها\n"
        "/progress - تقدمك واستمراريتك\n"
        "/word - كلمة إنجليزية عشوائية\n"
        "/quiz - اختبار سريع\n"
        "/motivate - عبارة تحفيزية\n"
        "/morning on|off - تذكير صباحي"
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jobs = context.job_queue.get_jobs_by_name(f"daily_{chat_id}")
    if not jobs:
        await update.message.reply_text("ℹ️ لا يوجد تذكير مفعّل حالياً.")
        return
    for job in jobs:
        job.schedule_removal()
    await update.message.reply_text("⏸️ تم إيقاف التذكير اليومي. فعّله مجدداً بـ /start")

async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["📅 الخطة الأسبوعية لدراسة الإنجليزية:\n"]
    for i, day in enumerate(DAYS):
        lines.append(f"• {day}: {SCHEDULE[i]}")
    data = load_data()
    user = get_user(data, update.effective_chat.id)
    lines.append(f"\n⏰ وقت تذكيرك: {user['time']} بتوقيت السعودية.")
    await update.message.reply_text("\n".join(lines))

async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الاستخدام: /settime 20:30")
        return
    try:
        h, m = map(int, context.args[0].split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except Exception:
        await update.message.reply_text("❌ صيغة غير صحيحة. مثال: /settime 20:30")
        return

    chat_id = update.effective_chat.id
    data = load_data()
    user = get_user(data, chat_id)
    user["time"] = f"{h:02d}:{m:02d}"
    save_data(data)

    for job in context.job_queue.get_jobs_by_name(f"daily_{chat_id}"):
        job.schedule_removal()
    context.job_queue.run_daily(
        remind_english,
        time=datetime.time(hour=h, minute=m, tzinfo=RIYADH),
        chat_id=chat_id,
        name=f"daily_{chat_id}"
    )
    await update.message.reply_text(f"✅ تم ضبط التذكير على {h:02d}:{m:02d} بتوقيت السعودية.")

async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الاستخدام: /addtask مراجعة 10 كلمات")
        return
    task = " ".join(context.args)
    chat_id = update.effective_chat.id
    data = load_data()
    user = get_user(data, chat_id)
    user["tasks"].append(task)
    save_data(data)
    await update.message.reply_text(f"✅ أُضيفت المهمة: {task}\nلديك الآن {len(user['tasks'])} مهمة.")

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = get_user(data, update.effective_chat.id)
    if not user["tasks"]:
        await update.message.reply_text("📭 لا توجد مهام. أضف واحدة بـ /addtask")
        return
    lines = ["📌 مهامك:\n"] + [f"{i+1}. {t}" for i, t in enumerate(user["tasks"])]
    await update.message.reply_text("\n".join(lines))

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("الاستخدام: /done 2")
        return
    try:
        idx = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً.")
        return

    data = load_data()
    user = get_user(data, update.effective_chat.id)
    if idx < 0 or idx >= len(user["tasks"]):
        await update.message.reply_text("❌ رقم غير موجود في قائمتك.")
        return
    removed = user["tasks"].pop(idx)
    save_data(data)
    await update.message.reply_text(f"✅ أنجزت: {removed}\nبقي لديك {len(user['tasks'])} مهمة.")

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = get_user(data, update.effective_chat.id)
    start = datetime.datetime.strptime(user["start_date"], "%Y-%m-%d").date()
    days = (datetime.datetime.now(RIYADH).date() - start).days + 1
    await update.message.reply_text(
        f"📊 تقدمك:\n"
        f"🔥 الاستمرارية: {user['streak']} يوم\n"
        f"📅 منذ بدء الدراسة: {days} يوم\n"
        f"📌 المهام المتبقية: {len(user['tasks'])}\n"
        f"⏰ وقت التذكير: {user['time']}"
    )

async def word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w, ar, en = random.choice(WORDS)
    await update.message.reply_text(
        f"📖 كلمة اليوم:\n\n"
        f"🔤 {w}\n"
        f"🇸🇦 {ar}\n"
        f"🇬🇧 {en}"
    )

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    correct = random.choice(WORDS)
    others = random.sample([w for w in WORDS if w != correct], 2)
    options = [correct[1], others[0][1], others[1][1]]
    random.shuffle(options)

    # تخزين الإجابة الصحيحة والخيارات مؤقتاً
    context.user_data["quiz_answer"] = correct[1]
    context.user_data["quiz_options"] = options

    text = (
        f"❓ ما معنى كلمة: *{correct[0]}* ؟\n\n"
        + "\n".join(f"{chr(65+i)}. {opt}" for i, opt in enumerate(options))
        + "\n\nأرسل إجابتك كحرف (A/B/C)"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or context.args[0] not in ("on", "off"):
        await update.message.reply_text("الاستخدام: /morning on  أو  /morning off")
        return

    chat_id = update.effective_chat.id
    data = load_data()
    user = get_user(data, chat_id)
    state = context.args[0]

    for job in context.job_queue.get_jobs_by_name(f"morning_{chat_id}"):
        job.schedule_removal()

    if state == "on":
        context.job_queue.run_daily(
            morning_reminder,
            time=datetime.time(hour=8, minute=0, tzinfo=RIYADH),
            chat_id=chat_id,
            name=f"morning_{chat_id}"
        )
        user["morning"] = True
        save_data(data)
        await update.message.reply_text("✅ تم تفعيل التذكير الصباحي الساعة 8:00 صباحاً.")
    else:
        user["morning"] = False
        save_data(data)
        await update.message.reply_text("⏸️ تم إيقاف التذكير الصباحي.")

async def motivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(MOTIVATION))

# ---------- معالج إجابات الاختبار ----------
async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = context.user_data.get("quiz_answer")
    options = context.user_data.get("quiz_options", [])
    if not answer or not options:
        return

    letter = update.message.text.strip().upper()
    mapping = {"A": 0, "B": 1, "C": 2}
    if letter not in mapping:
        return

    chosen = options[mapping[letter]]
    if chosen == answer:
        await update.message.reply_text("✅ إجابة صحيحة! أحسنت.")
    else:
        await update.message.reply_text(f"❌ إجابة خاطئة. الصحيح: {answer}")

    context.user_data["quiz_answer"] = None
    context.user_data["quiz_options"] = []

# ---------- التشغيل ----------
app = Application.builder().token(TOKEN).post_init(restore_jobs).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(CommandHandler("schedule", schedule))
app.add_handler(CommandHandler("settime", settime))
app.add_handler(CommandHandler("addtask", addtask))
app.add_handler(CommandHandler("tasks", tasks))
app.add_handler(CommandHandler("done", done))
app.add_handler(CommandHandler("progress", progress))
app.add_handler(CommandHandler("word", word))
app.add_handler(CommandHandler("quiz", quiz))
app.add_handler(CommandHandler("motivate", motivate))
app.add_handler(CommandHandler("morning", morning))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_answer))

app.run_polling()
