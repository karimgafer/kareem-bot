import logging, os, json, random, uuid, asyncio
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, ContextTypes, filters)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
import pytz

# ════════════════════════════════════════════
#  إعدادات
# ════════════════════════════════════════════
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "YOUR_TOKEN")
CHAT_ID    = int(os.environ.get("CHAT_ID", "0"))
TZ         = pytz.timezone("Asia/Riyadh")
NOTES_FILE = "notes.json"
TASKS_FILE = "custom_tasks.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ════════════════════════════════════════════
#  حالة عالمية
# ════════════════════════════════════════════
paused_plans  = set()
last_task     = {"name": ""}
awaiting_note = {}   # {cid: plan_key}
user_state    = {}   # {cid: {step, data}} لإضافة مهمة
_bot_ref      = None
_scheduler    = None

PLAN_NAMES = {
    "study":   "📚 مذاكرة MBA",
    "voice":   "🎙️ تدريب صوت",
    "dialect": "🗣️ لهجات",
    "routine": "💆 روتين جسم",
    "fitness": "💪 لياقة",
    "water":   "💧 ماء",
    "meals":   "🍽️ وجبات",
}

DAYS_AR = {
    "0": "الاثنين", "1": "الثلاثاء", "2": "الأربعاء",
    "3": "الخميس",  "4": "الجمعة",   "5": "السبت", "6": "الأحد"
}

# ════════════════════════════════════════════
#  رسائل متنوعة
# ════════════════════════════════════════════
MSGS = {
    "water":         ["💧 وقت الماء! 330 مل الآن 🥤","💧 اشرب كوباً الآن 🌊","💧 ماء = طاقة + تركيز! 🥤"],
    "voice_morning": ["🎙️ 15 دقيقة تصنع فرقاً — ابدأ الآن ✨","🎙️ صوتك سلاحك — اشحنه ⚡"],
    "voice_evening": ["🎙️ اختم يومك بقوة! 🌙","🎙️ الثبات يصنع الاحتراف 🎯"],
    "study":         ["📚 العلم لا يأتي بدون جهد — يلا! 🚀","📚 كل ساعة تقربك من هدفك 🎯"],
    "dialect_sa":    ["🇸🇦 اسمع، كرر، اتقن! 👂","🇸🇦 تكلم بها طول اليوم 💬"],
    "dialect_ma":    ["🇲🇦 واش راك كريم؟ 😄","🇲🇦 كل كلمة = سلاح جديد 🗝️"],
    "dialect_en":    ["🇬🇧 Speak it, live it, own it! 💯"],
    "dialect_flex":  ["🗣️ اختر أي لهجة وتمرن عليها 🎭"],
    "jaw":           ["💆 10 دقائق — استثمار صغير لنتيجة كبيرة 💪"],
    "fitness":       ["💪 الجسم يبنى بالثبات! 🏋️","💪 كل تمرين يقربك من نسختك الأفضل 🔥"],
    "skin":          ["💆 بشرتك تستحق الاهتمام ✨","💆 الثبات هو السر الحقيقي 🌿"],
    "night_routine": [
        "🌙 روتين الليل\n💆 شعر + بشرة + أسنان\n💧 آخر كوب ماء!\n\n<i>أحسنت اليوم كريم 🌟</i>",
        "🌙 ختام اليوم\n💆 شعر + بشرة + أسنان\n💧 آخر كوب!\n\n<i>يوم منجز — افتخر بنفسك! 💪</i>",
    ],
}
def pick(k): return random.choice(MSGS.get(k, [k]))

# ════════════════════════════════════════════
#  ملاحظات
# ════════════════════════════════════════════
def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {k: [] for k in PLAN_NAMES}

def save_notes(n):
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(n, f, ensure_ascii=False, indent=2)

notes_db = load_notes()
for k in PLAN_NAMES:
    notes_db.setdefault(k, [])

# ════════════════════════════════════════════
#  مهام مخصصة
# ════════════════════════════════════════════
def load_tasks():
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_tasks(t):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=2)

custom_tasks = load_tasks()

def days_label(val):
    m = {"daily": "كل يوم", "workdays": "أيام العمل", "weekend": "الإجازة",
         "once": "مرة واحدة", "today": "اليوم فقط (متكرر)"}
    if val in m:
        return m[val]
    return " · ".join(DAYS_AR.get(d, "؟") for d in val.split(","))

def register_task_scheduler(task: dict):
    """تسجيل مهمة مخصصة في المُجدوِل — مع تذكير قبل 5 دقائق"""
    if _scheduler is None:
        return
    tid    = task["id"]
    job_id = f"custom_{tid}"
    job_id_pre = f"custom_pre_{tid}"
    h, m   = map(int, task["time"].split(":"))
    name   = task["name"]

    # احذف القديم إن وُجد
    for jid in (job_id, job_id_pre):
        try:
            _scheduler.remove_job(jid)
        except Exception:
            pass

    async def fire():
        log.info(f"Firing custom task: {name}")
        await safe_send(
            f"🔔 <b>{name}</b>\n\n<i>مهمتك المخصصة — يلا كريم! ✅</i>",
            task_name=f"مهمة_{name}",
            reply_markup=reminder_kb(f"مهمة_{name}")
        )

    async def fire_pre():
        log.info(f"Pre-reminder custom task: {name}")
        await safe_send(f"⏰ <b>{name}</b> — بعد 5 دقائق! 🔔")

    # احسب وقت التذكير المسبق
    pre_h, pre_m = h, m - 5
    if pre_m < 0:
        pre_m += 60
        pre_h = (pre_h - 1) % 24

    days_val = task.get("days", "daily")

    if days_val == "once":
        now = datetime.now(TZ)
        run_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)
        pre_at = run_at - timedelta(minutes=5)
        _scheduler.add_job(fire, DateTrigger(run_date=run_at, timezone=TZ),
                           id=job_id, misfire_grace_time=3600)
        if pre_at > now:
            _scheduler.add_job(fire_pre, DateTrigger(run_date=pre_at, timezone=TZ),
                               id=job_id_pre, misfire_grace_time=3600)
        log.info(f"One-time task '{name}' scheduled at {run_at}")

    elif days_val == "today":
        current_dow = str(datetime.now(TZ).weekday())
        _scheduler.add_job(fire, CronTrigger(hour=h, minute=m,
                           day_of_week=current_dow, timezone=TZ),
                           id=job_id, misfire_grace_time=3600)
        _scheduler.add_job(fire_pre, CronTrigger(hour=pre_h, minute=pre_m,
                           day_of_week=current_dow, timezone=TZ),
                           id=job_id_pre, misfire_grace_time=3600)
        log.info(f"Today-weekly task '{name}' at {h:02d}:{m:02d} dow={current_dow}")

    else:
        dow = None
        if days_val == "workdays": dow = "0,1,2,3,6"
        elif days_val == "weekend": dow = "4,5"
        elif days_val != "daily":   dow = days_val

        cron_args = dict(hour=h, minute=m, timezone=TZ)
        pre_cron_args = dict(hour=pre_h, minute=pre_m, timezone=TZ)
        if dow:
            cron_args["day_of_week"] = dow
            pre_cron_args["day_of_week"] = dow

        _scheduler.add_job(fire, CronTrigger(**cron_args),
                           id=job_id, misfire_grace_time=3600)
        _scheduler.add_job(fire_pre, CronTrigger(**pre_cron_args),
                           id=job_id_pre, misfire_grace_time=3600)
        log.info(f"Recurring task '{name}' at {h:02d}:{m:02d} dow={dow}")

# ════════════════════════════════════════════
#  كيبورد رئيسي
# ════════════════════════════════════════════
MAIN_KB = ReplyKeyboardMarkup([
    ["📋 جدولي اليوم",  "💧 اشرب ماء الآن"],
    ["✅ تم ✓",         "⏰ أجّل 15 دقيقة"],
    ["📝 ملاحظاتي",     "📊 تقريري"],
    ["➕ مهمة جديدة",   "📌 مهامي"],
    ["⚙️ الإعدادات"],
], resize_keyboard=True)

# ════════════════════════════════════════════
#  مساعدات عامة
# ════════════════════════════════════════════
def now_r():       return datetime.now(TZ)
def weekday():     return now_r().weekday()
def is_work():     return weekday() not in (4, 5)
def is_active(p):  return p not in paused_plans

def dialect_info():
    d = {
        6: ("🇸🇦", "سعودية",   "dialect_sa"),
        0: ("🇸🇦", "سعودية",   "dialect_sa"),
        1: ("🇲🇦", "مغربية",   "dialect_ma"),
        2: ("🇲🇦", "مغربية",   "dialect_ma"),
        3: ("🇬🇧", "إنجليزية", "dialect_en"),
        4: ("🇬🇧", "إنجليزية", "dialect_en"),
        5: ("🗣️",  "مرنة",     "dialect_flex"),
    }
    return d.get(weekday(), ("🗣️", "لهجة", "dialect_flex"))

def notes_footer(pk):
    items = notes_db.get(pk, [])
    if not items:
        return ""
    return "\n\n📝 <b>ملاحظاتك:</b>\n" + "\n".join(f"  • {n}" for n in items)

def reminder_kb(task_name):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تم",         callback_data=f"done|{task_name}"),
         InlineKeyboardButton("⏰ أجّل 15د",  callback_data=f"snooze15|{task_name}")],
        [InlineKeyboardButton("⏰ أجّل ساعة", callback_data=f"snooze60|{task_name}"),
         InlineKeyboardButton("❌ فاتني",      callback_data=f"missed|{task_name}")],
    ])

async def safe_send(text, task_name=None, plan_key=None, reply_markup=None):
    """إرسال آمن مع تسجيل الأخطاء"""
    global last_task
    if _bot_ref is None:
        log.error("safe_send: _bot_ref is None!")
        return
    footer = notes_footer(plan_key) if plan_key else ""
    kb     = reply_markup or (reminder_kb(task_name) if task_name else None)
    if task_name:
        last_task["name"] = task_name
    try:
        await _bot_ref.send_message(
            chat_id=CHAT_ID,
            text=text + footer,
            parse_mode="HTML",
            reply_markup=kb
        )
        log.info(f"✅ Sent: {task_name or text[:30]}")
    except Exception as e:
        log.error(f"❌ send_message failed: {e}")

# ════════════════════════════════════════════
#  ملخص الصباح
# ════════════════════════════════════════════
async def morning_summary():
    days = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
            4:"الجمعة",5:"السبت",6:"الأحد"}
    flag, dial, _ = dialect_info()
    dur   = "3 ساعات 🔥" if not is_work() else "90 دقيقة"
    fit   = "🛌 راحة" if not is_work() else "💪 45 دقيقة"
    greet = random.choice(["صباح الخير","صباح النور","يوم جديد وفرصة جديدة"])

    paused_str = ""
    if paused_plans:
        paused_str = "\n\n⏸ <i>موقوفة: " + \
            " · ".join(PLAN_NAMES.get(p, "") for p in paused_plans) + "</i>"

    today_wd = str(weekday())
    today_tasks = [
        t for t in custom_tasks
        if t.get("active", True) and t.get("days") != "once" and (
            t["days"] == "daily"
            or (t["days"] == "workdays" and is_work())
            or (t["days"] == "weekend"  and not is_work())
            or today_wd in t["days"].split(",")
        )
    ]
    custom_str = ""
    if today_tasks:
        custom_str = "\n\n<b>📌 مهامك المخصصة اليوم:</b>\n" + \
            "\n".join(
                f"  🕐 {t['time']}  🔔 {t['name']}"
                for t in sorted(today_tasks, key=lambda x: x["time"])
            )

    if _bot_ref is None:
        log.error("morning_summary: _bot_ref is None")
        return

    await _bot_ref.send_message(
        chat_id=CHAT_ID, parse_mode="HTML", reply_markup=MAIN_KB,
        text=(
            f"☀️ <b>{greet} كريم!</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📅 <b>{days[weekday()]}</b>  {'🏢 دوام' if is_work() else '🌴 إجازة'}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"🕙 10:00  💆 روتين بشرة\n"
            f"🕙 10:30  🍳 فطار\n"
            f"🕚 11:00  🎙️ تدريب صوت\n"
            f"🕛 12:00  🍎 سناك 1\n"
            f"🕛 12:30  {flag} لهجة {dial}\n"
            f"🕐 13:30  📚 مذاكرة — {dur}\n"
            f"🕒 15:30  🍽️ غداء\n"
            f"🕔 17:00  💆 فكين\n"
            f"🕕 18:30  🍎 سناك 2\n"
            f"🕙 21:00  🎙️ تدريب صوت\n"
            f"🕙 21:30  🍛 عشاء\n"
            f"🕙 22:00  {fit}\n"
            f"🕚 23:30  📖 مراجعة MBA\n"
            f"🕛 00:00  🌙 روتين ليلي"
            f"{custom_str}{paused_str}\n\n"
            f"<i>💧 ماء كل ساعة — يلا بقوة! 🚀</i>"
        )
    )

# ════════════════════════════════════════════
#  مهام المُجدوِل الثابتة
# ════════════════════════════════════════════
async def job_summary():          await morning_summary()

async def job_skin():
    if is_active("routine"):
        await safe_send(f"╔══════════╗\n  💆 <b>روتين بشرة صباحي</b>\n╚══════════╝\n\n{pick('skin')}",
                        "روتين_بشرة", "routine")

async def job_water(cup, bar):
    if is_active("water"):
        await safe_send(f"💧 <b>تذكير الماء</b> — كوب {cup} من 15\n{bar}\n\n{pick('water')}",
                        f"ماء_{cup}", "water")

async def job_brkfst_r():   await safe_send("⏰ <b>الفطار بعد 5 دقائق!</b> 🍳",             "فطار", "meals")
async def job_brkfst():     await safe_send("🍳 <b>وقت الفطار!</b>\nالطاقة تبدأ من هنا ⚡", "فطار", "meals")

async def job_voice_m():
    if is_active("voice"):
        await safe_send(f"╔══════════╗\n  🎙️ <b>تدريب صوت صباحي</b>\n╚══════════╝\n\n{pick('voice_morning')}",
                        "صوت_صباحي", "voice")

async def job_snack1():     await safe_send("🍎 <b>سناك 1</b> 😋", "سناك_1", "meals")

async def job_dialect():
    if is_active("dialect"):
        flag, name, mk = dialect_info()
        await safe_send(f"╔══════════╗\n  {flag} <b>لهجة {name}</b>\n╚══════════╝\n\n{pick(mk)}",
                        f"لهجة_{name}", "dialect")

async def job_study_r():
    if is_active("study"):
        dur = "3 ساعات" if not is_work() else "90 دقيقة"
        await safe_send(f"⏰ <b>المذاكرة بعد 5 دقائق!</b> — {dur} 📚", "مذاكرة_MBA", "study")

async def job_study():
    if is_active("study"):
        dur = "3 ساعات" if not is_work() else "90 دقيقة"
        await safe_send(f"╔══════════╗\n  📚 <b>مذاكرة MBA</b> — {dur}\n╚══════════╝\n\n{pick('study')}",
                        "مذاكرة_MBA", "study")

async def job_dialect_rand():
    if is_active("dialect"):
        flag, name, _ = dialect_info()
        await safe_send(f"⚡ <b>تذكير عشوائي!</b>\nتكلّم {flag} {name} 5 دقائق 💬",
                        f"لهجة_{name}", "dialect")

async def job_lunch_r():    await safe_send("⏰ <b>الغداء بعد 5 دقائق!</b> 🍽️",         "غداء", "meals")
async def job_lunch():      await safe_send("🍽️ <b>وقت الغداء!</b>\nاسترح وتغدَّ 🔋", "غداء", "meals")

async def job_jaw1():
    if is_active("routine"):
        await safe_send(f"💆 <b>تمارين الفكين — جلسة أولى</b>\n\n{pick('jaw')}", "فكين_1", "routine")

async def job_snack2():     await safe_send("🍎 <b>سناك 2</b> 🌅", "سناك_2", "meals")

async def job_voice_e():
    if is_active("voice"):
        await safe_send(f"╔══════════╗\n  🎙️ <b>تدريب صوت مسائي</b>\n╚══════════╝\n\n{pick('voice_evening')}",
                        "صوت_مسائي", "voice")

async def job_dinner_r():   await safe_send("⏰ <b>العشاء بعد 5 دقائق!</b> 🍛",              "عشاء", "meals")
async def job_dinner():     await safe_send("🍛 <b>وقت العشاء!</b>\nاستحققته بعد يوم منتج 🌙", "عشاء", "meals")

async def job_fitness():
    if is_active("fitness") and is_work():
        await safe_send(f"╔══════════╗\n  💪 <b>تدريب اللياقة</b> — 45 دقيقة\n╚══════════╝\n\n{pick('fitness')}",
                        "لياقة", "fitness")

async def job_jaw2():
    if is_active("routine"):
        await safe_send(f"💆 <b>تمارين الفكين — جلسة ثانية</b>\n\n{pick('jaw')}", "فكين_2", "routine")

async def job_review_r():
    if is_active("study"):
        await safe_send("⏰ <b>مراجعة MBA بعد 5 دقائق!</b> 📖", "مراجعة_MBA", "study")

async def job_review():
    if is_active("study"):
        await safe_send(
            "╔══════════╗\n  📖 <b>مراجعة MBA</b> — 30 دقيقة\n╚══════════╝\n\n"
            "راجع وثبّت في ذاكرتك 🧠\n<i>التكرار سر التميز!</i>",
            "مراجعة_MBA", "study")

async def job_review_fri_r():
    if is_active("study"):
        await safe_send("⏰ <b>مراجعة الجمعة بعد 5 دقائق!</b> 📖", "مراجعة_MBA", "study")

async def job_review_fri():
    if is_active("study"):
        await safe_send("📖 <b>مراجعة MBA — الجمعة</b>\n\nراجع أسبوعك بتمعّن 🌙\n<i>من راجع نجح!</i>",
                        "مراجعة_MBA", "study")

async def job_night():
    if is_active("routine"):
        await safe_send(f"━━━━━━━━━━━━━━━━\n{pick('night_routine')}", "روتين_ليلي", "routine")

# ════════════════════════════════════════════
#  إعداد المُجدوِل
# ════════════════════════════════════════════
def setup_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=TZ)
    c = lambda **kw: CronTrigger(timezone=TZ, **kw)

    _scheduler.add_job(job_summary,       c(hour=9,  minute=55))
    _scheduler.add_job(job_skin,          c(hour=10, minute=0))
    _scheduler.add_job(job_brkfst_r,      c(hour=10, minute=25))
    _scheduler.add_job(job_brkfst,        c(hour=10, minute=30))
    _scheduler.add_job(job_voice_m,       c(hour=11, minute=0))
    _scheduler.add_job(job_snack1,        c(hour=12, minute=0))
    _scheduler.add_job(job_dialect,       c(hour=12, minute=30))
    _scheduler.add_job(job_study_r,       c(hour=13, minute=25))
    _scheduler.add_job(job_study,         c(hour=13, minute=30))
    _scheduler.add_job(job_dialect_rand,  c(hour=14, minute=30))
    _scheduler.add_job(job_lunch_r,       c(hour=15, minute=25))
    _scheduler.add_job(job_lunch,         c(hour=15, minute=30))
    _scheduler.add_job(job_jaw1,          c(hour=17, minute=0))
    _scheduler.add_job(job_snack2,        c(hour=18, minute=30))
    _scheduler.add_job(job_dialect_rand,  c(hour=19, minute=0))
    _scheduler.add_job(job_voice_e,       c(hour=21, minute=0))
    _scheduler.add_job(job_dinner_r,      c(hour=21, minute=25))
    _scheduler.add_job(job_dinner,        c(hour=21, minute=30))
    _scheduler.add_job(job_fitness,       c(hour=22, minute=0, day_of_week="0,1,2,3,6"))
    _scheduler.add_job(job_jaw2,          c(hour=22, minute=0))
    _scheduler.add_job(job_review_r,      c(hour=23, minute=25, day_of_week="0,1,2,3,5,6"))
    _scheduler.add_job(job_review,        c(hour=23, minute=30, day_of_week="0,1,2,3,5,6"))
    _scheduler.add_job(job_review_fri_r,  c(hour=22, minute=55, day_of_week="4"))
    _scheduler.add_job(job_review_fri,    c(hour=23, minute=0,  day_of_week="4"))
    _scheduler.add_job(job_night,         c(hour=0,  minute=0))

    cups = {10:1,11:2,12:3,13:4,14:5,15:6,16:7,17:8,18:9,19:10,20:11,21:12,22:13,23:14,0:15}
    for h in list(range(10, 24)) + [0]:
        cup = cups.get(h, "")
        bar = ("🔵" * min(cup, 10) + "⚪" * max(0, 10 - cup)) if isinstance(cup, int) else ""
        _scheduler.add_job(job_water, c(hour=h, minute=0), args=[cup, bar])

    for t in custom_tasks:
        if t.get("active", True):
            register_task_scheduler(t)

    _scheduler.start()
    log.info(f"✅ Scheduler started — {len(_scheduler.get_jobs())} total jobs")

# ════════════════════════════════════════════
#  بناء كيبورد اختيار الأيام
# ════════════════════════════════════════════
def build_days_kb(selected: list) -> InlineKeyboardMarkup:
    """كيبورد اختيار أيام محددة مع ✅ للمحدد"""
    day_order = [("6","الأحد"),("0","الاثنين"),("1","الثلاثاء"),
                 ("2","الأربعاء"),("3","الخميس"),("4","الجمعة"),("5","السبت")]
    buttons = []
    for num, label in day_order:
        mark = "✅" if num in selected else "◻️"
        buttons.append([InlineKeyboardButton(f"{mark} {label}",
                                              callback_data=f"toggle_day|{num}")])
    if selected:
        days_str = ",".join(selected)
        buttons.append([InlineKeyboardButton(
            f"✔️ تأكيد ({len(selected)} أيام)",
            callback_data=f"confirm_days|{days_str}"
        )])
    buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel_task")])
    return InlineKeyboardMarkup(buttons)

# ════════════════════════════════════════════
#  عرض ملاحظات
# ════════════════════════════════════════════
async def show_notes(query, pk, edit=False):
    items = notes_db.get(pk, [])
    title = PLAN_NAMES.get(pk, pk)
    body  = "\n".join(f"{i+1}. {n}" for i, n in enumerate(items)) if items else "<i>لا توجد ملاحظات بعد!</i>"
    text  = f"📝 <b>ملاحظات {title}</b>\n\n{body}"
    kb    = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ أضف ملاحظة / رابط", callback_data=f"addnote|{pk}")],
        [InlineKeyboardButton("🗑️ احذف ملاحظة",       callback_data=f"delnote|{pk}")],
        [InlineKeyboardButton("← رجوع",               callback_data="notes|menu")],
    ])
    if edit:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await _bot_ref.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML", reply_markup=kb)

# ════════════════════════════════════════════
#  عرض مهام مخصصة
# ════════════════════════════════════════════
async def show_my_tasks(query=None, edit=False):
    if not custom_tasks:
        text = "📌 <b>مهامي المخصصة</b>\n\n<i>لا توجد مهام بعد!\nاضغط ➕ مهمة جديدة لإضافة أول مهمة.</i>"
        kb   = InlineKeyboardMarkup([[InlineKeyboardButton("← إغلاق", callback_data="closetasks")]])
    else:
        lines = []
        for t in custom_tasks:
            status = "✅" if t.get("active", True) else "⏸"
            lines.append(f"{status} <b>{t['name']}</b>  🕐{t['time']}  📅{days_label(t['days'])}")
        text = "📌 <b>مهامي المخصصة</b>\n\n" + "\n".join(lines)
        rows = []
        for t in custom_tasks:
            tog_label = "⏸ إيقاف" if t.get("active", True) else "▶️ استئناف"
            rows.append([
                InlineKeyboardButton(f"🗑️ {t['name']}", callback_data=f"deltask|{t['id']}"),
                InlineKeyboardButton(tog_label,           callback_data=f"toggletask|{t['id']}"),
            ])
        rows.append([InlineKeyboardButton("← إغلاق", callback_data="closetasks")])
        kb = InlineKeyboardMarkup(rows)

    if query and edit:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    elif _bot_ref:
        await _bot_ref.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML", reply_markup=kb)

# ════════════════════════════════════════════
#  Callback Handler
# ════════════════════════════════════════════
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    global custom_tasks
    query  = update.callback_query
    await query.answer()
    cid    = update.effective_chat.id
    data   = query.data
    parts  = data.split("|", 2)
    action = parts[0]
    arg    = parts[1] if len(parts) > 1 else ""

    # ── ملاحظات ────────────────────────────────────────────
    if action == "notes":
        buttons = [[InlineKeyboardButton(n, callback_data=f"viewnotes|{k}")] for k, n in PLAN_NAMES.items()]
        await query.edit_message_text("📝 <b>ملاحظاتي</b>\n\nاختر الخطة:",
                                      parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    elif action == "viewnotes":
        await show_notes(query, arg, edit=True)

    elif action == "addnote":
        awaiting_note[cid] = arg
        await query.edit_message_text(
            f"📝 <b>إضافة ملاحظة — {PLAN_NAMES.get(arg, arg)}</b>\n\n"
            "أرسل الملاحظة أو الرابط:\n\n<i>مثال:\n• https://youtube.com/...\n• ركّز على الفصل الثالث</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"viewnotes|{arg}")]]))

    elif action == "delnote":
        items = notes_db.get(arg, [])
        if not items:
            await query.answer("لا توجد ملاحظات", show_alert=True)
            return
        rows = [[InlineKeyboardButton(
            f"🗑️ {i+1}. {n[:30]}{'...' if len(n)>30 else ''}",
            callback_data=f"delitem|{arg}|{i}")] for i, n in enumerate(items)]
        rows.append([InlineKeyboardButton("← رجوع", callback_data=f"viewnotes|{arg}")])
        await query.edit_message_text("🗑️ <b>اختر الملاحظة للحذف:</b>",
                                      parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))

    elif action == "delitem":
        sub = arg.split("|")
        key = sub[0]; idx = int(sub[1]) if len(sub) > 1 else -1
        if 0 <= idx < len(notes_db.get(key, [])):
            notes_db[key].pop(idx); save_notes(notes_db)
            await query.answer("✅ تم الحذف")
        await show_notes(query, key, edit=True)

    # ── اختيار أيام المهمة المخصصة ─────────────────────────
    elif action == "toggle_day":
        st = user_state.get(cid)
        if not st or "data" not in st:
            await query.answer("❌ انتهت الجلسة، ابدأ من جديد بالضغط على ➕ مهمة جديدة", show_alert=True)
            return
        selected = list(st["data"].get("selected_days", []))
        if arg in selected:
            selected.remove(arg)
        else:
            selected.append(arg)
        st["data"]["selected_days"] = selected
        user_state[cid] = st
        new_kb = build_days_kb(selected)
        try:
            await query.edit_message_reply_markup(reply_markup=new_kb)
        except Exception as e:
            log.warning(f"edit_message_reply_markup failed: {e}")
            # fallback: edit full message
            await query.edit_message_text(
                "✏️ <b>اختر الأيام التي تريدها:</b>\n<i>اضغط على اليوم لتحديده/إلغاء تحديده</i>",
                parse_mode="HTML", reply_markup=new_kb
            )

    elif action == "confirm_days":
        st = user_state.pop(cid, {})
        if "data" not in st:
            await query.answer("انتهت الجلسة.", show_alert=True)
            return
        name = st["data"]["name"]
        time = st["data"]["time"]
        days = arg  # "0,1,2" مثلاً
        new_task = {"id": str(uuid.uuid4())[:8], "name": name,
                    "time": time, "days": days, "active": True}
        custom_tasks.append(new_task); save_tasks(custom_tasks)
        register_task_scheduler(new_task)
        await query.edit_message_text(
            f"✅ <b>تمت إضافة المهمة!</b>\n\n"
            f"🔔 <b>{name}</b>\n"
            f"🕐 الوقت: <b>{time}</b>\n"
            f"📅 الأيام: <b>{days_label(days)}</b>\n\n"
            f"<i>سأذكّرك في كل موعد 🎯</i>", parse_mode="HTML")

    elif action == "cancel_task":
        user_state.pop(cid, None)
        await query.edit_message_text("❌ <b>تم الإلغاء</b>", parse_mode="HTML")

    # ── مهام مخصصة: حذف / إيقاف ───────────────────────────
    elif action == "deltask":
        t_del = next((t for t in custom_tasks if t["id"] == arg), None)
        if t_del:
            custom_tasks = [t for t in custom_tasks if t["id"] != arg]
            save_tasks(custom_tasks)
            for jid in (f"custom_{arg}", f"custom_pre_{arg}"):
                try: _scheduler.remove_job(jid)
                except Exception: pass
            await query.answer(f"✅ تم حذف: {t_del['name']}")
        await show_my_tasks(query, edit=True)

    elif action == "toggletask":
        t_tog = next((t for t in custom_tasks if t["id"] == arg), None)
        if t_tog:
            t_tog["active"] = not t_tog.get("active", True)
            save_tasks(custom_tasks)
            if t_tog["active"]:
                register_task_scheduler(t_tog)
                await query.answer("▶️ تم الاستئناف")
            else:
                for jid in (f"custom_{arg}", f"custom_pre_{arg}"):
                    try: _scheduler.remove_job(jid)
                    except Exception: pass
                await query.answer("⏸ تم الإيقاف")
        await show_my_tasks(query, edit=True)

    elif action == "closetasks":
        await query.edit_message_reply_markup(reply_markup=None)

    # ── أزرار التذكير ───────────────────────────────────────
    elif action == "done":
        await query.edit_message_reply_markup(reply_markup=None)
        c = random.choice(["أحسنت! 🌟","رائع! 💪","ممتاز! 🔥","عظيم! ✨"])
        await ctx.bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
            text=f"✅ <b>تم!</b> — {arg}\n<i>{c}</i>", reply_markup=MAIN_KB)

    elif action in ("snooze15", "snooze60"):
        mins  = 15 if action == "snooze15" else 60
        label = "15 دقيقة" if mins == 15 else "ساعة"
        fire  = (now_r() + timedelta(minutes=mins)).strftime("%H:%M")
        run_at = datetime.now(TZ) + timedelta(minutes=mins)
        name_copy = arg

        async def fire_snooze():
            await safe_send(f"⏰ <b>تذكير مؤجّل</b> — {name_copy}", name_copy)

        _scheduler.add_job(fire_snooze, DateTrigger(run_date=run_at, timezone=TZ))
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
            text=f"⏰ <b>تأجيل {label}</b>\n{arg}\nسأذكّرك الساعة <b>{fire}</b> 🕐")

    elif action == "missed":
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
            text=f"📝 <b>سُجّلت كفائتة:</b> {arg}\n<i>لا بأس، غداً أفضل 💪</i>")

    # ── إعدادات ─────────────────────────────────────────────
    elif action == "settings":
        if arg == "pause":
            rows = [[InlineKeyboardButton(n, callback_data=f"pause|{k}")] for k, n in PLAN_NAMES.items()]
            await query.edit_message_text("⏸ <b>أي خطة توقفها؟</b>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
        elif arg == "resume":
            if not paused_plans:
                await query.edit_message_text("✅ جميع الخطط تعمل!", parse_mode="HTML"); return
            rows = [[InlineKeyboardButton(PLAN_NAMES.get(p, p), callback_data=f"resume|{p}")] for p in paused_plans]
            await query.edit_message_text("▶️ <b>أي خطة تستأنفها؟</b>",
                parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
        elif arg == "status":
            lines = "\n".join(f"{'⏸' if k in paused_plans else '✅'}  {n}" for k, n in PLAN_NAMES.items())
            await query.edit_message_text(f"📋 <b>حالة الخطط:</b>\n\n{lines}", parse_mode="HTML")

    elif action == "pause":
        paused_plans.add(arg)
        await query.edit_message_text(
            f"⏸ <b>تم إيقاف {PLAN_NAMES.get(arg, arg)}</b>\nيمكنك استئنافها من ⚙️.", parse_mode="HTML")

    elif action == "resume":
        paused_plans.discard(arg)
        await query.edit_message_text(
            f"▶️ <b>تم استئناف {PLAN_NAMES.get(arg, arg)}</b> ✅", parse_mode="HTML")

# ════════════════════════════════════════════
#  Text Handler
# ════════════════════════════════════════════
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    cid = update.effective_chat.id

    # ── استقبال ملاحظة ──────────────────────────────────────
    if cid in awaiting_note:
        pk = awaiting_note.pop(cid)
        notes_db.setdefault(pk, []).append(txt)
        save_notes(notes_db)
        await update.message.reply_text(
            f"✅ <b>تمت الإضافة!</b>\n\n📌 {PLAN_NAMES.get(pk, pk)}\n📝 <code>{txt}</code>\n\n"
            "<i>ستظهر مع كل تذكير لهذه الخطة 🎯</i>",
            parse_mode="HTML", reply_markup=MAIN_KB)
        return

    # ── مراحل إضافة مهمة جديدة ──────────────────────────────
    if cid in user_state:
        st = user_state[cid]

        if st["step"] == "waiting_name":
            name = txt.strip()
            if not name:
                await update.message.reply_text("❌ اكتب اسماً للمهمة"); return
            st["data"]["name"] = name
            st["step"] = "waiting_time"
            user_state[cid] = st
            await update.message.reply_text(
                f"✅ الاسم: <b>{name}</b>\n\n"
                "🕐 <b>ما وقت التذكير؟</b>\n<i>اكتب بصيغة HH:MM مثل: 08:30 أو 21:00</i>",
                parse_mode="HTML")
            return

        if st["step"] == "waiting_time":
            try:
                p    = txt.strip().split(":")
                h, m = int(p[0]), int(p[1])
                assert 0 <= h <= 23 and 0 <= m <= 59
                time_str = f"{h:02d}:{m:02d}"
            except Exception:
                await update.message.reply_text(
                    "❌ <b>صيغة خاطئة!</b>\nاكتب هكذا: <code>08:30</code>", parse_mode="HTML")
                return

            st["data"]["time"] = time_str
            st["data"]["selected_days"] = []
            st["step"] = "waiting_days"
            user_state[cid] = st

            await update.message.reply_text(
                f"✅ الوقت: <b>{time_str}</b>\n\n"
                "📅 <b>أي أيام تريد التذكير؟</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📆 كل يوم",                    callback_data="finaldays|daily")],
                    [InlineKeyboardButton("🏢 أيام العمل (أحد-خميس)",    callback_data="finaldays|workdays")],
                    [InlineKeyboardButton("🌴 الإجازة (جمعة+سبت)",       callback_data="finaldays|weekend")],
                    [InlineKeyboardButton("📌 نفس اليوم أسبوعياً",        callback_data="finaldays|today")],
                    [InlineKeyboardButton("🔂 مرة واحدة فقط",             callback_data="finaldays|once")],
                    [InlineKeyboardButton("✏️ اختر أيام محددة",           callback_data="finaldays|custom")],
                    [InlineKeyboardButton("❌ إلغاء",                      callback_data="cancel_task")],
                ]))
            return

    # ── أزرار الكيبورد الرئيسي ───────────────────────────────
    if txt == "📋 جدولي اليوم":
        await morning_summary()

    elif txt == "💧 اشرب ماء الآن":
        await update.message.reply_text(
            f"💧 <b>اشرب 330 مل الآن!</b>\n{pick('water')} 🥤", parse_mode="HTML")

    elif txt == "✅ تم ✓":
        c = random.choice(["أحسنت! 🌟","رائع! 💪","ممتاز! 🔥"])
        await update.message.reply_text(
            f"✅ <b>تم!</b> — {last_task.get('name','المهمة')}\n<i>{c}</i>",
            parse_mode="HTML", reply_markup=MAIN_KB)

    elif txt == "⏰ أجّل 15 دقيقة":
        name  = last_task.get("name", "المهمة")
        fire  = (now_r() + timedelta(minutes=15)).strftime("%H:%M")
        run_at = datetime.now(TZ) + timedelta(minutes=15)
        async def remind():
            await safe_send(f"⏰ <b>تذكير مؤجّل</b> — {name}", name)
        _scheduler.add_job(remind, DateTrigger(run_date=run_at, timezone=TZ))
        await update.message.reply_text(
            f"⏰ <b>تأجيل 15 دقيقة</b>\n{name}\nالساعة <b>{fire}</b> 🕐", parse_mode="HTML")

    elif txt == "📝 ملاحظاتي":
        buttons = [[InlineKeyboardButton(n, callback_data=f"viewnotes|{k}")] for k, n in PLAN_NAMES.items()]
        await update.message.reply_text(
            "📝 <b>ملاحظاتي</b>\n\nاختر الخطة:", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons))

    elif txt == "📊 تقريري":
        days_ar = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
                   4:"الجمعة",5:"السبت",6:"الأحد"}
        flag, dial, _ = dialect_info()
        total = sum(len(v) for v in notes_db.values())
        await update.message.reply_text(
            f"📊 <b>تقرير اليوم</b>\n━━━━━━━━━━━━━━━━\n"
            f"📅 {days_ar[weekday()]}  {'🏢 دوام' if is_work() else '🌴 إجازة'}\n"
            f"{flag} اللهجة: <b>{dial}</b>\n"
            f"✅ خطط نشطة: <b>{len(PLAN_NAMES)-len(paused_plans)}</b> من {len(PLAN_NAMES)}\n"
            f"📌 مهام مخصصة: <b>{len(custom_tasks)}</b>\n"
            f"📝 ملاحظاتك: <b>{total}</b>\n━━━━━━━━━━━━━━━━\n"
            f"<i>استمر — أنت على الطريق الصح! 🚀</i>",
            parse_mode="HTML", reply_markup=MAIN_KB)

    elif txt == "➕ مهمة جديدة":
        user_state[cid] = {"step": "waiting_name", "data": {}}
        await update.message.reply_text(
            "➕ <b>إضافة مهمة جديدة</b>\n\n"
            "🔤 <b>ما اسم المهمة؟</b>\n\n<i>مثال: قراءة كتاب، تمرين تمدد...</i>",
            parse_mode="HTML")

    elif txt == "📌 مهامي":
        await show_my_tasks()

    elif txt == "⚙️ الإعدادات":
        await update.message.reply_text(
            "⚙️ <b>الإعدادات</b>\n\nاختر ما تريد:", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏸ إيقاف خطة مؤقتاً",  callback_data="settings|pause")],
                [InlineKeyboardButton("▶️ استئناف خطة موقوفة", callback_data="settings|resume")],
                [InlineKeyboardButton("📋 حالة جميع الخطط",    callback_data="settings|status")],
            ]))

# ════════════════════════════════════════════
#  معالج finaldays (اختيار نوع التكرار)
# ════════════════════════════════════════════
async def handle_finaldays(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """معالج خاص لاختيار نوع الأيام عند إضافة مهمة"""
    global custom_tasks
    query  = update.callback_query
    await query.answer()
    cid    = update.effective_chat.id
    days   = query.data.split("|")[1]
    st     = user_state.get(cid, {})

    if "data" not in st:
        await query.edit_message_text("❌ انتهت الجلسة، ابدأ من جديد.", parse_mode="HTML"); return

    if days == "custom":
        # أظهر كيبورد اختيار الأيام
        st["data"]["selected_days"] = []
        user_state[cid] = st
        await query.edit_message_text(
            "✏️ <b>اختر الأيام التي تريدها:</b>\n<i>اضغط على اليوم لتحديده/إلغاء تحديده</i>",
            parse_mode="HTML",
            reply_markup=build_days_kb([]))
        return

    # حفظ المهمة مباشرة
    name     = st["data"]["name"]
    time_str = st["data"]["time"]
    user_state.pop(cid, None)

    new_task = {"id": str(uuid.uuid4())[:8], "name": name,
                "time": time_str, "days": days, "active": True}
    custom_tasks.append(new_task); save_tasks(custom_tasks)
    register_task_scheduler(new_task)

    await query.edit_message_text(
        f"✅ <b>تمت إضافة المهمة!</b>\n\n"
        f"🔔 <b>{name}</b>\n"
        f"🕐 الوقت: <b>{time_str}</b>\n"
        f"📅 الأيام: <b>{days_label(days)}</b>\n\n"
        f"<i>سأذكّرك في كل موعد 🎯</i>", parse_mode="HTML")

# ════════════════════════════════════════════
#  أوامر
# ════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>مرحباً كريم!</b>\n\nالبوت يعمل ✅\nاستخدم الأزرار أدناه 👇",
        parse_mode="HTML", reply_markup=MAIN_KB)

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await morning_summary()

async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """أمر لاختبار الإشعارات فوراً"""
    await safe_send(
        "🧪 <b>اختبار البوت</b>\n\n"
        "✅ البوت يعمل\n"
        f"⏰ الوقت الآن: <b>{now_r().strftime('%H:%M')}</b> (توقيت الرياض)\n"
        f"📅 اليوم: <b>{['الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'][weekday()]}</b>\n"
        f"📌 مهام مخصصة: <b>{len(custom_tasks)}</b>\n"
        f"🗓 مهام مجدولة: <b>{len(_scheduler.get_jobs()) if _scheduler else 0}</b>"
    )

# ════════════════════════════════════════════
#  post_init + main
# ════════════════════════════════════════════
async def post_init(app: Application):
    global _bot_ref
    _bot_ref = app.bot
    setup_scheduler()
    log.info(f"✅ Bot ready | CHAT_ID={CHAT_ID}")

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("test",  cmd_test))
    app.add_handler(CallbackQueryHandler(handle_finaldays, pattern=r"^finaldays\|"))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
