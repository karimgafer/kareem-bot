import logging, os, json, random, uuid
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, ContextTypes, filters)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ─── إعدادات ──────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "YOUR_TOKEN")
CHAT_ID     = os.environ.get("CHAT_ID",   "YOUR_ID")
TZ          = pytz.timezone("Asia/Riyadh")
NOTES_FILE  = "notes.json"
TASKS_FILE  = "custom_tasks.json"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── حالة البوت ──────────────────────────────────────────
paused_plans  = set()
last_task     = {"name": ""}
awaiting_note = {}        # {chat_id: plan_key}
user_state    = {}        # {chat_id: {step, data}} للمهام الجديدة
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

DAYS_AR = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
           4:"الجمعة",5:"السبت",6:"الأحد"}
DAYS_SHORT = {"0":"mon","1":"tue","2":"wed","3":"thu","4":"fri","5":"sat","6":"sun"}

# ─── رسائل متنوعة ────────────────────────────────────────
MSGS = {
    "water":["💧 وقت الماء! اشرب 330 مل الآن 🥤","💧 جسمك يحتاجك! كوب ماء 🌊",
             "💧 ماء = طاقة + تركيز! 🥤","💧 330 مل — جسمك يشكرك 🌿"],
    "voice_morning":["🎙️ الصوت أصفى ما يكون الآن!\n15 دقيقة ✨",
                     "🎙️ صوتك سلاحك — اشحنه الآن ⚡","🎙️ صوت + نفس = ثقة 💪"],
    "voice_evening":["🎙️ اختم يومك بقوة! 🌙","🎙️ الثبات يصنع الاحتراف 🎯","🎙️ لا تخذله الليلة 🌟"],
    "study":["📚 العلم لا يأتي بدون جهد — يلا! 🚀","📚 كل ساعة تقربك من هدفك 🎯","📚 اغلق كل شيء وافتح الكتاب 💡"],
    "dialect_sa":["🇸🇦 اسمع، كرر، اتقن! 👂","🇸🇦 تكلم بها طول اليوم 💬"],
    "dialect_ma":["🇲🇦 واش راك كريم؟ 😄","🇲🇦 كل كلمة = سلاح جديد 🗝️"],
    "dialect_en":["🇬🇧 Speak it, live it, own it! 💯","🇬🇧 Practice makes perfect 🎯"],
    "dialect_flex":["🗣️ اختر أي لهجة وتمرن عليها 🎭"],
    "jaw":["💆 10 دقائق — استثمار صغير لنتيجة كبيرة 💪","💆 عشر دقائق تحدث فرقاً حقيقياً 🎯"],
    "fitness":["💪 الجسم يبنى بالثبات لا بالتردد! 🏋️","💪 كل تمرين يقربك من نسختك الأفضل 🔥","💪 احما أولاً ثم ابدأ 🚀"],
    "skin":["💆 بشرتك تستحق الاهتمام يومياً ✨","💆 الثبات هو السر الحقيقي 🌿"],
    "night_routine":["🌙 روتين الليل\n💆 شعر + بشرة + أسنان\n💧 آخر كوب ماء!\n\n✨ <i>أحسنت اليوم، نم قرير العين! 🌟</i>",
                     "🌙 ختام اليوم\n💆 شعر + بشرة + أسنان\n💧 آخر كوب!\n\n🌟 <i>يوم منجز — افتخر بنفسك! 💪</i>"],
}
def pick(k): return random.choice(MSGS.get(k,[k]))

# ─── ملاحظات ──────────────────────────────────────────────
def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return {k:[] for k in PLAN_NAMES}
def save_notes(n):
    with open(NOTES_FILE,"w",encoding="utf-8") as f: json.dump(n,f,ensure_ascii=False,indent=2)
notes_db = load_notes()
for k in PLAN_NAMES: notes_db.setdefault(k,[])

# ─── مهام مخصصة ──────────────────────────────────────────
def load_tasks():
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE,"r",encoding="utf-8") as f: return json.load(f)
    return []
def save_tasks(t):
    with open(TASKS_FILE,"w",encoding="utf-8") as f: json.dump(t,f,ensure_ascii=False,indent=2)

custom_tasks = load_tasks()

def days_label(days_val):
    labels = {"daily":"كل يوم","workdays":"أيام العمل","weekend":"الإجازة"}
    if days_val in labels: return labels[days_val]
    nums = days_val.split(",")
    return " · ".join(DAYS_AR.get(int(n),"?") for n in nums)

def days_to_cron(days_val):
    """تحويل قيمة الأيام إلى صيغة APScheduler day_of_week"""
    if days_val == "daily":    return None          # كل يوم
    if days_val == "workdays": return "0,1,2,3,6"  # أحد-خميس
    if days_val == "weekend":  return "4,5"         # جمعة+سبت
    return days_val  # مثل "0,2,4"

def register_custom_task(task: dict):
    """تسجيل مهمة مخصصة في المُجدوِل"""
    if _scheduler is None: return
    tid = task["id"]
    h, m = map(int, task["time"].split(":"))
    dow  = days_to_cron(task["days"])

    async def fire(name=task["name"]):
        await send(
            f"🔔 <b>{name}</b>\n\n"
            f"<i>مهمتك المخصصة — يلا كريم! ✅</i>",
            f"مهمة_{name}", None)

    job_id = f"custom_{tid}"
    try: _scheduler.remove_job(job_id)
    except: pass

    if dow:
        _scheduler.add_job(fire, CronTrigger(hour=h,minute=m,day_of_week=dow,timezone=TZ), id=job_id)
    else:
        _scheduler.add_job(fire, CronTrigger(hour=h,minute=m,timezone=TZ), id=job_id)
    log.info(f"Registered custom task: {task['name']} at {task['time']}")

# ─── كيبورد ──────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup([
    ["📋 جدولي اليوم",   "💧 اشرب ماء الآن"],
    ["✅ تم ✓",          "⏰ أجّل 15 دقيقة"],
    ["📝 ملاحظاتي",      "📊 تقريري"],
    ["➕ مهمة جديدة",    "📌 مهامي"],
    ["⚙️ الإعدادات"],
], resize_keyboard=True)

# ─── مساعدات ──────────────────────────────────────────────
def now_r():      return datetime.now(TZ)
def weekday():    return now_r().weekday()
def is_work():    return weekday() not in (4,5)
def is_active(p): return p not in paused_plans

def dialect_info():
    return {6:("🇸🇦","سعودية","dialect_sa"),0:("🇸🇦","سعودية","dialect_sa"),
            1:("🇲🇦","مغربية","dialect_ma"),2:("🇲🇦","مغربية","dialect_ma"),
            3:("🇬🇧","إنجليزية","dialect_en"),4:("🇬🇧","إنجليزية","dialect_en"),
            5:("🗣️","مرنة","dialect_flex")}.get(weekday(),("🗣️","لهجة","dialect_flex"))

def notes_footer(pk):
    items = notes_db.get(pk,[])
    if not items: return ""
    return "\n\n📝 <b>ملاحظاتك:</b>\n" + "\n".join(f"  • {n}" for n in items)

def reminder_buttons(task_name):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تم",        callback_data=f"done|{task_name}"),
         InlineKeyboardButton("⏰ أجّل 15د", callback_data=f"snooze15|{task_name}")],
        [InlineKeyboardButton("⏰ أجّل ساعة",callback_data=f"snooze60|{task_name}"),
         InlineKeyboardButton("❌ فاتني",     callback_data=f"missed|{task_name}")],
    ])

async def send(text, task_name=None, plan_key=None):
    global last_task
    if _bot_ref is None: return
    footer = notes_footer(plan_key) if plan_key else ""
    kb     = reminder_buttons(task_name) if task_name else None
    if task_name: last_task["name"] = task_name
    try:
        await _bot_ref.send_message(chat_id=CHAT_ID,text=text+footer,
                                    parse_mode="HTML",reply_markup=kb)
    except Exception as e:
        log.error(f"Send error: {e}")

# ─── ملخص الصباح ─────────────────────────────────────────
async def morning_summary():
    days  = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
             4:"الجمعة",5:"السبت",6:"الأحد"}
    flag,dial,_ = dialect_info()
    dur = "3 ساعات 🔥" if not is_work() else "90 دقيقة"
    fit = "🛌 راحة" if not is_work() else "💪 45 دقيقة"
    greet = random.choice(["صباح الخير","صباح النور","يوم جديد وفرصة جديدة"])
    paused_str = ("\n\n⏸ <i>موقوفة: " + " · ".join(PLAN_NAMES.get(p,"") for p in paused_plans) + "</i>") if paused_plans else ""

    # المهام المخصصة لهذا اليوم
    today_wd   = str(weekday())
    today_tasks = [t for t in custom_tasks if t.get("active",True) and (
        t["days"]=="daily" or
        (t["days"]=="workdays" and is_work()) or
        (t["days"]=="weekend" and not is_work()) or
        today_wd in t["days"].split(","))]
    custom_str = ""
    if today_tasks:
        custom_str = "\n\n<b>📌 مهامك المخصصة اليوم:</b>\n" + \
            "\n".join(f"🕐 {t['time']}  🔔 {t['name']}" for t in
                      sorted(today_tasks, key=lambda x: x["time"]))

    if _bot_ref is None: return
    await _bot_ref.send_message(chat_id=CHAT_ID,parse_mode="HTML",reply_markup=MAIN_KB,
        text=(f"☀️ <b>{greet} كريم!</b>\n"
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
              f"<i>💧 ماء كل ساعة — يلا بقوة! 🚀</i>"))

# ─── مهام المُجدوِل الثابتة ───────────────────────────────
async def job_summary():    await morning_summary()
async def job_skin():
    if is_active("routine"):
        await send(f"╔══════════════╗\n  💆 <b>روتين بشرة صباحي</b>\n╚══════════════╝\n\n{pick('skin')}","روتين_بشرة","routine")
async def job_water(cup,bar):
    if is_active("water"):
        await send(f"💧 <b>تذكير الماء</b> — كوب {cup} من 15\n{bar}\n\n{pick('water')}",f"ماء_{cup}","water")
async def job_breakfast_remind(): await send("⏰ <b>الفطار بعد 5 دقائق!</b>\nاستعد يا كريم 🍳","فطار","meals")
async def job_breakfast():        await send("🍳 <b>وقت الفطار!</b>\nالطاقة تبدأ من هنا ⚡","فطار","meals")
async def job_voice_morning():
    if is_active("voice"):
        await send(f"╔══════════════╗\n  🎙️ <b>تدريب صوت صباحي</b>\n╚══════════════╝\n\n{pick('voice_morning')}","صوت_صباحي","voice")
async def job_snack1(): await send("🍎 <b>سناك 1</b> 😋","سناك_1","meals")
async def job_dialect():
    if is_active("dialect"):
        flag,name,mk = dialect_info()
        await send(f"╔══════════════╗\n  {flag} <b>لهجة {name}</b>\n╚══════════════╝\n\n{pick(mk)}",f"لهجة_{name}","dialect")
async def job_study_remind():
    if is_active("study"):
        dur="3 ساعات" if not is_work() else "90 دقيقة"
        await send(f"⏰ <b>المذاكرة بعد 5 دقائق!</b> — {dur} 📚","مذاكرة_MBA","study")
async def job_study():
    if is_active("study"):
        dur="3 ساعات" if not is_work() else "90 دقيقة"
        await send(f"╔══════════════╗\n  📚 <b>مذاكرة MBA</b> — {dur}\n╚══════════════╝\n\n{pick('study')}","مذاكرة_MBA","study")
async def job_dialect_random():
    if is_active("dialect"):
        flag,name,_ = dialect_info()
        await send(random.choice([f"⚡ <b>تحدٍّ سريع!</b>\nتكلّم {flag} {name} 5 دقائق 💬",
                                   f"🎲 <b>تذكير عشوائي!</b>\nفكّر بـ {flag} {name} 5 دقائق 🧠"]),f"لهجة_{name}","dialect")
async def job_lunch_remind(): await send("⏰ <b>الغداء بعد 5 دقائق!</b> 🍽️","غداء","meals")
async def job_lunch():        await send("🍽️ <b>وقت الغداء!</b>\nاسترح وتغدَّ 🔋","غداء","meals")
async def job_jaw1():
    if is_active("routine"):
        await send(f"💆 <b>تمارين الفكين — جلسة أولى</b>\n\n{pick('jaw')}","فكين_1","routine")
async def job_snack2(): await send("🍎 <b>سناك 2</b> 🌅","سناك_2","meals")
async def job_voice_evening():
    if is_active("voice"):
        await send(f"╔══════════════╗\n  🎙️ <b>تدريب صوت مسائي</b>\n╚══════════════╝\n\n{pick('voice_evening')}","صوت_مسائي","voice")
async def job_dinner_remind(): await send("⏰ <b>العشاء بعد 5 دقائق!</b> 🍛","عشاء","meals")
async def job_dinner():        await send("🍛 <b>وقت العشاء!</b>\nاستحققته بعد يوم منتج 🌙","عشاء","meals")
async def job_fitness():
    if is_active("fitness") and is_work():
        await send(f"╔══════════════╗\n  💪 <b>تدريب اللياقة</b> — 45 دقيقة\n╚══════════════╝\n\n{pick('fitness')}","لياقة","fitness")
async def job_jaw2():
    if is_active("routine"):
        await send(f"💆 <b>تمارين الفكين — جلسة ثانية</b>\n\n{pick('jaw')}","فكين_2","routine")
async def job_review_remind():
    if is_active("study"): await send("⏰ <b>مراجعة MBA بعد 5 دقائق!</b> 📖","مراجعة_MBA","study")
async def job_review():
    if is_active("study"):
        await send("╔══════════════╗\n  📖 <b>مراجعة MBA</b> — 30 دقيقة\n╚══════════════╝\n\nراجع وثبّت في ذاكرتك 🧠\n<i>التكرار سر التميز!</i>","مراجعة_MBA","study")
async def job_review_fri_remind():
    if is_active("study"): await send("⏰ <b>مراجعة الجمعة بعد 5 دقائق!</b> 📖","مراجعة_MBA","study")
async def job_review_fri():
    if is_active("study"):
        await send("📖 <b>مراجعة MBA — الجمعة</b>\n\nأسبوع كامل — راجعه بتمعّن 🌙\n<i>من راجع نجح!</i>","مراجعة_MBA","study")
async def job_night():
    if is_active("routine"):
        await send(f"━━━━━━━━━━━━━━━━\n{pick('night_routine')}","روتين_ليلي","routine")

# ─── إعداد المُجدوِل ──────────────────────────────────────
def setup_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=TZ)
    def c(**kw): return CronTrigger(timezone=TZ,**kw)

    _scheduler.add_job(job_summary,          c(hour=9,  minute=55))
    _scheduler.add_job(job_skin,             c(hour=10, minute=0))
    _scheduler.add_job(job_breakfast_remind, c(hour=10, minute=25))
    _scheduler.add_job(job_breakfast,        c(hour=10, minute=30))
    _scheduler.add_job(job_voice_morning,    c(hour=11, minute=0))
    _scheduler.add_job(job_snack1,           c(hour=12, minute=0))
    _scheduler.add_job(job_dialect,          c(hour=12, minute=30))
    _scheduler.add_job(job_study_remind,     c(hour=13, minute=25))
    _scheduler.add_job(job_study,            c(hour=13, minute=30))
    _scheduler.add_job(job_dialect_random,   c(hour=14, minute=30))
    _scheduler.add_job(job_lunch_remind,     c(hour=15, minute=25))
    _scheduler.add_job(job_lunch,            c(hour=15, minute=30))
    _scheduler.add_job(job_jaw1,             c(hour=17, minute=0))
    _scheduler.add_job(job_snack2,           c(hour=18, minute=30))
    _scheduler.add_job(job_dialect_random,   c(hour=19, minute=0))
    _scheduler.add_job(job_voice_evening,    c(hour=21, minute=0))
    _scheduler.add_job(job_dinner_remind,    c(hour=21, minute=25))
    _scheduler.add_job(job_dinner,           c(hour=21, minute=30))
    _scheduler.add_job(job_fitness,          c(hour=22, minute=0, day_of_week="0,1,2,3,6"))
    _scheduler.add_job(job_jaw2,             c(hour=22, minute=0))
    _scheduler.add_job(job_review_remind,    c(hour=23, minute=25, day_of_week="0,1,2,3,5,6"))
    _scheduler.add_job(job_review,           c(hour=23, minute=30, day_of_week="0,1,2,3,5,6"))
    _scheduler.add_job(job_review_fri_remind,c(hour=22, minute=55, day_of_week="4"))
    _scheduler.add_job(job_review_fri,       c(hour=23, minute=0,  day_of_week="4"))
    _scheduler.add_job(job_night,            c(hour=0,  minute=0))

    cups_map = {10:1,11:2,12:3,13:4,14:5,15:6,16:7,17:8,18:9,19:10,20:11,21:12,22:13,23:14,0:15}
    for h in list(range(10,24))+[0]:
        cup = cups_map.get(h,"")
        bar = "🔵"*min(cup,10)+"⚪"*max(0,10-cup) if isinstance(cup,int) else ""
        _scheduler.add_job(job_water, c(hour=h,minute=0), args=[cup,bar])

    # تسجيل المهام المخصصة المحفوظة
    for task in custom_tasks:
        if task.get("active",True):
            register_custom_task(task)

    _scheduler.start()
    log.info(f"✅ Scheduler: {len(_scheduler.get_jobs())} jobs ({len(custom_tasks)} custom)")

# ─── عرض ملاحظات ─────────────────────────────────────────
async def show_plan_notes(query, pk, edit=False):
    items = notes_db.get(pk,[]); title = PLAN_NAMES.get(pk,pk)
    text  = (f"📝 <b>ملاحظات {title}</b>\n\n" +
             ("\n".join(f"{i+1}. {n}" for i,n in enumerate(items)) if items else "<i>لا توجد ملاحظات بعد!</i>"))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ أضف ملاحظة / رابط",callback_data=f"addnote|{pk}")],
        [InlineKeyboardButton("🗑️ احذف ملاحظة",      callback_data=f"delnote|{pk}")],
        [InlineKeyboardButton("← رجوع",              callback_data="notes|menu")],
    ])
    if edit: await query.edit_message_text(text,parse_mode="HTML",reply_markup=kb)
    else:    await _bot_ref.send_message(chat_id=CHAT_ID,text=text,parse_mode="HTML",reply_markup=kb)

# ─── عرض المهام المخصصة ──────────────────────────────────
async def show_custom_tasks(query=None, edit=False):
    if not custom_tasks:
        text = "📌 <b>مهامي المخصصة</b>\n\n<i>لم تضف أي مهمة بعد!\nاضغط ➕ مهمة جديدة لإضافة أول مهمة.</i>"
    else:
        lines = []
        for i,t in enumerate(custom_tasks):
            status = "✅" if t.get("active",True) else "⏸"
            lines.append(f"{status} <b>{t['name']}</b>\n    🕐 {t['time']}  |  📅 {days_label(t['days'])}")
        text = "📌 <b>مهامي المخصصة</b>\n\n" + "\n\n".join(lines)

    buttons = []
    for i,t in enumerate(custom_tasks):
        buttons.append([InlineKeyboardButton(f"🗑️ احذف: {t['name']}",callback_data=f"deltask|{t['id']}")])
        status_label = "▶️ استئناف" if not t.get("active",True) else "⏸ إيقاف"
        buttons.append([InlineKeyboardButton(f"{status_label}: {t['name']}",callback_data=f"toggletask|{t['id']}")])
    buttons.append([InlineKeyboardButton("← إغلاق",callback_data="closetasks")])
    kb = InlineKeyboardMarkup(buttons)

    if query and edit:
        await query.edit_message_text(text,parse_mode="HTML",reply_markup=kb)
    elif _bot_ref:
        await _bot_ref.send_message(chat_id=CHAT_ID,text=text,parse_mode="HTML",reply_markup=kb)

# ─── Callback Handler ─────────────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split("|",2)
    action = parts[0]; task = parts[1] if len(parts)>1 else ""

    # ── ملاحظات ──
    if action=="notes":
        buttons=[[InlineKeyboardButton(n,callback_data=f"viewnotes|{k}")] for k,n in PLAN_NAMES.items()]
        await query.edit_message_text("📝 <b>ملاحظاتي</b>\n\nاختر الخطة:",parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)); return
    if action=="viewnotes": await show_plan_notes(query,task,edit=True); return
    if action=="addnote":
        awaiting_note[int(CHAT_ID)]=task
        await query.edit_message_text(
            f"📝 <b>إضافة ملاحظة — {PLAN_NAMES.get(task,task)}</b>\n\n"
            f"أرسل الملاحظة أو الرابط:\n\n<i>مثال:\n• https://youtube.com/...\n• ركّز على الفصل الثالث</i>",
            parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء",callback_data=f"viewnotes|{task}")]])); return
    if action=="delnote":
        items=notes_db.get(task,[])
        if not items: await query.answer("لا توجد ملاحظات",show_alert=True); return
        buttons=[[InlineKeyboardButton(f"🗑️ {i+1}. {n[:35]}{'...'if len(n)>35 else ''}",callback_data=f"delitem|{task}|{i}")] for i,n in enumerate(items)]
        buttons.append([InlineKeyboardButton("← رجوع",callback_data=f"viewnotes|{task}")])
        await query.edit_message_text("🗑️ <b>اختر الملاحظة للحذف:</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons)); return
    if action=="delitem":
        sub=task.split("|"); key=sub[0]; idx=int(sub[1]) if len(sub)>1 else -1
        if 0<=idx<len(notes_db.get(key,[])):
            notes_db[key].pop(idx); save_notes(notes_db); await query.answer("✅ تم الحذف")
        await show_plan_notes(query,key,edit=True); return

    # ── مهام مخصصة: اختيار الأيام ──
    if action=="taskdays":
        cid = update.effective_chat.id
        st  = user_state.get(cid,{})
        st["data"]["days"] = task
        name = st["data"].get("name","")
        time = st["data"].get("time","")
        dl   = days_label(task)
        # حفظ المهمة
        new_task = {"id": str(uuid.uuid4())[:8], "name":name, "time":time, "days":task, "active":True}
        custom_tasks.append(new_task); save_tasks(custom_tasks)
        register_custom_task(new_task)
        user_state.pop(cid,None)
        await query.edit_message_text(
            f"✅ <b>تمت إضافة المهمة!</b>\n\n"
            f"🔔 <b>{name}</b>\n"
            f"🕐 الوقت: <b>{time}</b>\n"
            f"📅 الأيام: <b>{dl}</b>\n\n"
            f"<i>سأذكّرك في كل موعد محدد 🎯</i>",
            parse_mode="HTML"); return

    if action=="taskdays_custom":
        # اختيار أيام محددة
        cid = update.effective_chat.id
        st  = user_state.get(cid,{})
        selected = st["data"].get("selected_days",[])
        day_num  = task
        if day_num in selected: selected.remove(day_num)
        else: selected.append(day_num)
        st["data"]["selected_days"] = selected
        user_state[cid] = st
        days_labels = {0:"الأحد",1:"الاثنين",2:"الثلاثاء",3:"الأربعاء",4:"الخميس",5:"الجمعة",6:"السبت"}
        buttons = []
        for d,label in days_labels.items():
            mark = "✅" if str(d) in selected else "◻️"
            buttons.append([InlineKeyboardButton(f"{mark} {label}",callback_data=f"taskdays_custom|{d}")])
        if selected:
            buttons.append([InlineKeyboardButton("✔️ تأكيد الأيام",callback_data=f"taskdays|{','.join(selected)}")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons)); return

    # ── مهام مخصصة: حذف/إيقاف ──
    if action=="deltask":
        global custom_tasks
        t_del = next((t for t in custom_tasks if t["id"]==task),None)
        if t_del:
            custom_tasks = [t for t in custom_tasks if t["id"]!=task]
            save_tasks(custom_tasks)
            try: _scheduler.remove_job(f"custom_{task}")
            except: pass
            await query.answer(f"✅ تم حذف: {t_del['name']}")
        await show_custom_tasks(query,edit=True); return

    if action=="toggletask":
        t_tog = next((t for t in custom_tasks if t["id"]==task),None)
        if t_tog:
            t_tog["active"] = not t_tog.get("active",True)
            save_tasks(custom_tasks)
            if t_tog["active"]: register_custom_task(t_tog)
            else:
                try: _scheduler.remove_job(f"custom_{task}")
                except: pass
            await query.answer("▶️ تم الاستئناف" if t_tog["active"] else "⏸ تم الإيقاف")
        await show_custom_tasks(query,edit=True); return

    if action=="closetasks":
        await query.edit_message_reply_markup(reply_markup=None); return

    # ── أزرار التذكير ──
    if action=="done":
        await query.edit_message_reply_markup(reply_markup=None)
        c=random.choice(["أحسنت! 🌟","رائع! 💪","ممتاز! 🔥","عظيم! ✨"])
        await ctx.bot.send_message(chat_id=CHAT_ID,parse_mode="HTML",
            text=f"✅ <b>تم!</b> — {task}\n<i>{c}</i>",reply_markup=MAIN_KB)
    elif action in("snooze15","snooze60"):
        mins=15 if action=="snooze15" else 60
        label="15 دقيقة" if mins==15 else "ساعة"
        fire=(datetime.now(TZ)+timedelta(minutes=mins)).strftime("%H:%M")
        async def ra(t=task): await send(f"⏰ <b>تذكير مؤجّل</b> — {t}",t)
        ctx.application.job_queue.run_once(lambda c,fn=ra:__import__('asyncio').get_event_loop().create_task(fn()),when=timedelta(minutes=mins))
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(chat_id=CHAT_ID,parse_mode="HTML",
            text=f"⏰ <b>تأجيل {label}</b>\n{task}\nسأذكّرك الساعة <b>{fire}</b> 🕐")
    elif action=="missed":
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(chat_id=CHAT_ID,parse_mode="HTML",
            text=f"📝 <b>سُجّلت كفائتة:</b> {task}\n<i>لا بأس، غداً أفضل 💪</i>")

    # ── إعدادات ──
    elif action=="settings":
        if task=="pause":
            buttons=[[InlineKeyboardButton(n,callback_data=f"pause|{k}")] for k,n in PLAN_NAMES.items()]
            await query.edit_message_text("⏸ <b>أي خطة توقفها مؤقتاً؟</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
        elif task=="resume":
            if not paused_plans: await query.edit_message_text("✅ جميع الخطط تعمل!",parse_mode="HTML"); return
            buttons=[[InlineKeyboardButton(PLAN_NAMES.get(p,p),callback_data=f"resume|{p}")] for p in paused_plans]
            await query.edit_message_text("▶️ <b>أي خطة تستأنفها؟</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
        elif task=="status":
            lines="\n".join(f"{'⏸'if k in paused_plans else '✅'}  {n}" for k,n in PLAN_NAMES.items())
            await query.edit_message_text(f"📋 <b>حالة الخطط:</b>\n\n{lines}",parse_mode="HTML")
    elif action=="pause":
        paused_plans.add(task)
        await query.edit_message_text(f"⏸ <b>تم إيقاف {PLAN_NAMES.get(task,task)}</b>\nيمكنك استئنافها من ⚙️.",parse_mode="HTML")
    elif action=="resume":
        paused_plans.discard(task)
        await query.edit_message_text(f"▶️ <b>تم استئناف {PLAN_NAMES.get(task,task)}</b> ✅",parse_mode="HTML")

# ─── Text Handler ─────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text; cid = update.effective_chat.id

    # ── استقبال ملاحظة ──
    if cid in awaiting_note:
        pk=awaiting_note.pop(cid); pn=PLAN_NAMES.get(pk,pk)
        notes_db.setdefault(pk,[]).append(txt); save_notes(notes_db)
        await update.message.reply_text(
            f"✅ <b>تمت الإضافة!</b>\n\n📌 <b>{pn}</b>\n📝 <code>{txt}</code>\n\n"
            f"<i>ستظهر مع كل تذكير لهذه الخطة 🎯</i>",
            parse_mode="HTML",reply_markup=MAIN_KB); return

    # ── مراحل إضافة مهمة جديدة ──
    if cid in user_state:
        st = user_state[cid]

        if st["step"] == "waiting_name":
            st["data"]["name"] = txt.strip()
            st["step"] = "waiting_time"
            user_state[cid] = st
            await update.message.reply_text(
                f"✅ اسم المهمة: <b>{txt}</b>\n\n"
                f"🕐 <b>ما وقت التذكير؟</b>\n"
                f"<i>اكتب الوقت بصيغة HH:MM\nمثال: 08:30 أو 20:00</i>",
                parse_mode="HTML"); return

        if st["step"] == "waiting_time":
            # التحقق من صيغة الوقت
            try:
                parts_t = txt.strip().split(":")
                h,m = int(parts_t[0]),int(parts_t[1])
                assert 0<=h<=23 and 0<=m<=59
                time_str = f"{h:02d}:{m:02d}"
            except:
                await update.message.reply_text(
                    "❌ <b>صيغة خاطئة!</b>\nاكتب الوقت هكذا: <code>08:30</code>",
                    parse_mode="HTML"); return

            st["data"]["time"] = time_str
            st["step"] = "waiting_days"
            user_state[cid] = st

            days_labels = {0:"الأحد",1:"الاثنين",2:"الثلاثاء",3:"الأربعاء",4:"الخميس",5:"الجمعة",6:"السبت"}
            custom_buttons = [[InlineKeyboardButton(f"◻️ {label}",callback_data=f"taskdays_custom|{d}")] for d,label in days_labels.items()]
            custom_buttons.append([InlineKeyboardButton("← رجوع",callback_data="cancel_task")])

            await update.message.reply_text(
                f"✅ الوقت: <b>{time_str}</b>\n\n"
                f"📅 <b>أي أيام تريد التذكير؟</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📆 كل يوم",         callback_data="taskdays|daily")],
                    [InlineKeyboardButton("🏢 أيام العمل فقط", callback_data="taskdays|workdays")],
                    [InlineKeyboardButton("🌴 الإجازة فقط",    callback_data="taskdays|weekend")],
                    [InlineKeyboardButton("✏️ اختر أيام محددة",callback_data="taskdays_custom|start")],
                ])); return

    # ── أزرار الكيبورد الرئيسي ──
    if txt=="📋 جدولي اليوم":
        await morning_summary()
    elif txt=="💧 اشرب ماء الآن":
        await update.message.reply_text(f"💧 <b>اشرب 330 مل الآن!</b>\n{pick('water')} 🥤",parse_mode="HTML")
    elif txt=="✅ تم ✓":
        c=random.choice(["أحسنت! 🌟","رائع! 💪","ممتاز! 🔥"])
        await update.message.reply_text(f"✅ <b>تم!</b> — {last_task.get('name','المهمة')}\n<i>{c}</i>",parse_mode="HTML",reply_markup=MAIN_KB)
    elif txt=="⏰ أجّل 15 دقيقة":
        name=last_task.get("name","المهمة"); fire=(datetime.now(TZ)+timedelta(minutes=15)).strftime("%H:%M")
        async def ra(t=name): await send(f"⏰ <b>تذكير مؤجّل</b> — {t}",t)
        ctx.application.job_queue.run_once(lambda c,fn=ra:__import__('asyncio').get_event_loop().create_task(fn()),when=timedelta(minutes=15))
        await update.message.reply_text(f"⏰ <b>تأجيل 15 دقيقة</b>\n{name}\nالساعة <b>{fire}</b> 🕐",parse_mode="HTML")
    elif txt=="📝 ملاحظاتي":
        buttons=[[InlineKeyboardButton(n,callback_data=f"viewnotes|{k}")] for k,n in PLAN_NAMES.items()]
        await update.message.reply_text("📝 <b>ملاحظاتي</b>\n\nاختر الخطة:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
    elif txt=="📊 تقريري":
        days_ar={0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",4:"الجمعة",5:"السبت",6:"الأحد"}
        flag,dial,_=dialect_info(); total=sum(len(v) for v in notes_db.values())
        await update.message.reply_text(
            f"📊 <b>تقرير اليوم</b>\n━━━━━━━━━━━━━━━━\n"
            f"📅 {days_ar[weekday()]}  {'🏢 دوام'if is_work() else '🌴 إجازة'}\n"
            f"{flag} اللهجة: <b>{dial}</b>\n"
            f"✅ خطط نشطة: <b>{len(PLAN_NAMES)-len(paused_plans)}</b> من {len(PLAN_NAMES)}\n"
            f"📌 مهام مخصصة: <b>{len(custom_tasks)}</b>\n"
            f"📝 ملاحظاتك: <b>{total}</b>\n━━━━━━━━━━━━━━━━\n"
            f"<i>استمر — أنت على الطريق الصح! 🚀</i>",
            parse_mode="HTML",reply_markup=MAIN_KB)

    elif txt=="➕ مهمة جديدة":
        user_state[cid] = {"step":"waiting_name","data":{}}
        await update.message.reply_text(
            "➕ <b>إضافة مهمة جديدة</b>\n\n"
            "🔤 <b>ما اسم المهمة؟</b>\n\n"
            "<i>مثال: قراءة كتاب، تمرين تمدد، مراجعة بريد...</i>",
            parse_mode="HTML")

    elif txt=="📌 مهامي":
        await show_custom_tasks()

    elif txt=="⚙️ الإعدادات":
        await update.message.reply_text("⚙️ <b>الإعدادات</b>\n\nاختر ما تريد:",parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏸ إيقاف خطة مؤقتاً",  callback_data="settings|pause")],
                [InlineKeyboardButton("▶️ استئناف خطة موقوفة", callback_data="settings|resume")],
                [InlineKeyboardButton("📋 حالة جميع الخطط",    callback_data="settings|status")],
            ]))

# ─── أوامر ────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>مرحباً كريم!</b>\n\nالبوت يعمل ✅\nاستخدم الأزرار أدناه 👇",
        parse_mode="HTML",reply_markup=MAIN_KB)

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await morning_summary()

# ─── post_init + main ──────────────────────────────────────
async def post_init(app: Application):
    global _bot_ref
    _bot_ref = app.bot
    setup_scheduler()
    log.info("✅ Bot initialized")

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("today",cmd_today))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    log.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
