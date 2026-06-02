import logging, os, json, random
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, ContextTypes, filters)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ─── إعدادات ──────────────────────────────────────────────
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "YOUR_TOKEN")
CHAT_ID    = os.environ.get("CHAT_ID",   "YOUR_ID")
TZ         = pytz.timezone("Asia/Riyadh")
NOTES_FILE = "notes.json"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── حالة البوت ──────────────────────────────────────────
paused_plans  = set()
last_task     = {"name": ""}
awaiting_note = {}
_bot_ref      = None   # مرجع البوت للمُجدوِل

PLAN_NAMES = {
    "study":   "📚 مذاكرة MBA",
    "voice":   "🎙️ تدريب صوت",
    "dialect": "🗣️ لهجات",
    "routine": "💆 روتين جسم",
    "fitness": "💪 لياقة",
    "water":   "💧 ماء",
    "meals":   "🍽️ وجبات",
}

# ─── رسائل متنوعة ────────────────────────────────────────
MSGS = {
    "water": [
        "💧 وقت الماء! اشرب 330 مل الآن 🥤",
        "💧 جسمك يحتاجك! كوب ماء بسرعة 🌊",
        "💧 ماء = طاقة + تركيز! لا تنسَ 🥤",
        "💧 330 مل — جسمك يشكرك لاحقاً 🌿",
    ],
    "voice_morning": [
        "🎙️ الصوت أصفى ما يكون الآن!\nابدأ تدريبك الصباحي — 15 دقيقة ✨",
        "🎙️ وقت الصوت الصباحي!\nصوتك سلاحك — اشحنه الآن ⚡",
        "🎙️ 15 دقيقة تصنع فرقاً كبيراً!\nصوت + نفس = ثقة 💪",
    ],
    "voice_evening": [
        "🎙️ تدريب صوت مسائي — 15 دقيقة\nاختم يومك بقوة! 🌙",
        "🎙️ الجلسة المسائية للصوت\nالثبات يصنع الاحتراف 🎯",
        "🎙️ صوتك ينتظر تدريبه المسائي!\nلا تخذله الليلة 🌟",
    ],
    "study": [
        "📚 وقت مذاكرة MBA!\nالعلم لا يأتي بدون جهد — يلا كريم 🚀",
        "📚 جلسة المذاكرة الآن!\nكل ساعة تقربك من هدفك 🎯",
        "📚 MBA لا ينتظر!\nاغلق كل شيء وافتح الكتاب 💡",
    ],
    "dialect_sa": [
        "🇸🇦 تدريب اللهجة السعودية — 20 دقيقة\nاسمع، كرر، اتقن! 👂",
        "🇸🇦 السعودية اليوم!\nحاول تفكر وتكلم فيها طول اليوم 💬",
    ],
    "dialect_ma": [
        "🇲🇦 تدريب الدارجة المغربية — 20 دقيقة\nواش راك كريم؟ 😄",
        "🇲🇦 الدارجة اليوم!\nكل كلمة تتعلمها = سلاح جديد 🗝️",
    ],
    "dialect_en": [
        "🇬🇧 English training — 20 minutes\nSpeak it, live it, own it! 💯",
        "🇬🇧 Today is English day!\nPractice makes perfect, Kareem 🎯",
    ],
    "dialect_flex": [
        "🗣️ يوم اللهجة المرنة!\nاختر أي لهجة وتمرن عليها 20 دقيقة 🎭",
    ],
    "jaw": [
        "💆 تمارين الفكين — 10 دقائق\nاستثمار صغير لنتيجة كبيرة 💪",
        "💆 وقت الفكين!\nعشر دقائق تحدث فرقاً حقيقياً 🎯",
    ],
    "fitness": [
        "💪 وقت التمرين المسائي — 45 دقيقة\nالجسم يبنى بالثبات لا بالتردد! 🏋️",
        "💪 يلا كريم! جلسة اللياقة الآن\nكل تمرين يقربك من نسختك الأفضل 🔥",
        "💪 45 دقيقة تغير يومك!\nاحما أولاً ثم ابدأ التمرين 🚀",
    ],
    "skin": [
        "💆 روتين البشرة الصباحي\nبشرتك تستحق الاهتمام يومياً ✨",
        "💆 وقت البشرة!\nالثبات هو السر الحقيقي للنتائج 🌿",
    ],
    "night_routine": [
        "🌙 روتين الليل\n💆 شعر + بشرة + أسنان\n💧 آخر كوب ماء!\n\n✨ <i>أحسنت اليوم كريم، نم قرير العين! 🌟</i>",
        "🌙 ختام اليوم\n💆 لا تنسَ شعرك وبشرتك وأسنانك\n💧 اشرب آخر كوب!\n\n🌟 <i>يوم منجز آخر — افتخر بنفسك! 💪</i>",
    ],
}
def pick(key): return random.choice(MSGS.get(key, [key]))

# ─── ملاحظات ──────────────────────────────────────────────
def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    return {k:[] for k in PLAN_NAMES}

def save_notes(notes):
    with open(NOTES_FILE,"w",encoding="utf-8") as f:
        json.dump(notes,f,ensure_ascii=False,indent=2)

notes_db = load_notes()
for k in PLAN_NAMES: notes_db.setdefault(k,[])

# ─── كيبورد ──────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup([
    ["📋 جدولي اليوم",  "💧 اشرب ماء الآن"],
    ["✅ تم ✓",         "⏰ أجّل 15 دقيقة"],
    ["📝 ملاحظاتي",     "📊 تقريري"],
    ["⚙️ الإعدادات"],
], resize_keyboard=True)

# ─── مساعدات ──────────────────────────────────────────────
def now_r():       return datetime.now(TZ)
def weekday():     return now_r().weekday()
def is_work():     return weekday() not in (4,5)
def is_active(p):  return p not in paused_plans

def dialect_info():
    return {6:("🇸🇦","سعودية","dialect_sa"),
            0:("🇸🇦","سعودية","dialect_sa"),
            1:("🇲🇦","مغربية","dialect_ma"),
            2:("🇲🇦","مغربية","dialect_ma"),
            3:("🇬🇧","إنجليزية","dialect_en"),
            4:("🇬🇧","إنجليزية","dialect_en"),
            5:("🗣️","مرنة","dialect_flex")}.get(weekday(),("🗣️","لهجة","dialect_flex"))

def notes_footer(plan_key):
    items = notes_db.get(plan_key,[])
    if not items: return ""
    return "\n\n📝 <b>ملاحظاتك:</b>\n" + "\n".join(f"  • {n}" for n in items)

def reminder_buttons(task_name):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تم",         callback_data=f"done|{task_name}"),
         InlineKeyboardButton("⏰ أجّل 15د",  callback_data=f"snooze15|{task_name}")],
        [InlineKeyboardButton("⏰ أجّل ساعة", callback_data=f"snooze60|{task_name}"),
         InlineKeyboardButton("❌ فاتني",      callback_data=f"missed|{task_name}")],
    ])

async def send(text, task_name=None, plan_key=None):
    """إرسال رسالة عبر البوت مباشرة"""
    global last_task
    if _bot_ref is None:
        log.warning("Bot not ready yet")
        return
    footer = notes_footer(plan_key) if plan_key else ""
    kb     = reminder_buttons(task_name) if task_name else None
    if task_name:
        last_task["name"] = task_name
    try:
        await _bot_ref.send_message(
            chat_id=CHAT_ID,
            text=text + footer,
            parse_mode="HTML",
            reply_markup=kb
        )
        log.info(f"Sent: {task_name or 'message'}")
    except Exception as e:
        log.error(f"Send error: {e}")

# ─── ملخص الصباح ─────────────────────────────────────────
async def morning_summary():
    days = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
            4:"الجمعة",5:"السبت",6:"الأحد"}
    flag, dial, _ = dialect_info()
    dur = "3 ساعات 🔥" if not is_work() else "90 دقيقة"
    fit = "🛌 راحة" if not is_work() else "💪 45 دقيقة"
    greet = random.choice(["صباح الخير","صباح النور","يوم جديد وفرصة جديدة"])
    paused_str = ""
    if paused_plans:
        paused_str = "\n\n⏸ <i>موقوفة: " + \
            " · ".join(PLAN_NAMES.get(p,"") for p in paused_plans) + "</i>"
    if _bot_ref is None: return
    await _bot_ref.send_message(chat_id=CHAT_ID, parse_mode="HTML",
        reply_markup=MAIN_KB,
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
            f"{paused_str}\n\n"
            f"<i>💧 ماء كل ساعة — يلا بقوة! 🚀</i>"
        ))

# ─── مهام المُجدوِل (async مباشر) ────────────────────────
async def job_summary():    await morning_summary()

async def job_skin():
    if is_active("routine"):
        await send(f"╔══════════════╗\n  💆 <b>روتين بشرة صباحي</b>\n╚══════════════╝\n\n{pick('skin')}",
                   "روتين_بشرة","routine")

async def job_water(cup, bar):
    if is_active("water"):
        await send(f"💧 <b>تذكير الماء</b> — كوب {cup} من 15\n{bar}\n\n{pick('water')}",
                   f"ماء_{cup}","water")

async def job_breakfast_remind():
    await send("⏰ <b>الفطار بعد 5 دقائق!</b>\nاستعد يا كريم 🍳","فطار","meals")
async def job_breakfast():
    await send("🍳 <b>وقت الفطار!</b>\nابدأ يومك بوجبة صحية — الطاقة تبدأ من هنا ⚡","فطار","meals")

async def job_voice_morning():
    if is_active("voice"):
        await send(f"╔══════════════╗\n  🎙️ <b>تدريب صوت صباحي</b>\n╚══════════════╝\n\n{pick('voice_morning')}",
                   "صوت_صباحي","voice")

async def job_snack1():
    await send("🍎 <b>سناك 1</b>\nوجبة خفيفة صحية 😋","سناك_1","meals")

async def job_dialect():
    if is_active("dialect"):
        flag, name, msg_key = dialect_info()
        await send(f"╔══════════════╗\n  {flag} <b>لهجة {name}</b>\n╚══════════════╝\n\n{pick(msg_key)}",
                   f"لهجة_{name}","dialect")

async def job_study_remind():
    if is_active("study"):
        dur = "3 ساعات" if not is_work() else "90 دقيقة"
        await send(f"⏰ <b>المذاكرة بعد 5 دقائق!</b>\nالمدة: {dur} — جهّز نفسك 📚","مذاكرة_MBA","study")
async def job_study():
    if is_active("study"):
        dur = "3 ساعات" if not is_work() else "90 دقيقة"
        await send(f"╔══════════════╗\n  📚 <b>مذاكرة MBA</b> — {dur}\n╚══════════════╝\n\n{pick('study')}",
                   "مذاكرة_MBA","study")

async def job_lunch_remind():
    await send("⏰ <b>الغداء بعد 5 دقائق!</b>\nاحضر وجبتك 🍽️","غداء","meals")
async def job_lunch():
    await send("🍽️ <b>وقت الغداء!</b>\nاسترح وتغدَّ — الجسم يحتاج وقوده 🔋","غداء","meals")

async def job_jaw1():
    if is_active("routine"):
        await send(f"💆 <b>تمارين الفكين — جلسة أولى</b>\n\n{pick('jaw')}","فكين_1","routine")

async def job_snack2():
    await send("🍎 <b>سناك 2</b>\nوجبة خفيفة قبل المساء 🌅","سناك_2","meals")

async def job_dialect_random():
    if is_active("dialect"):
        flag, name, _ = dialect_info()
        msg = random.choice([
            f"⚡ <b>تحدٍّ سريع!</b>\nتكلّم {flag} <b>{name}</b> 5 دقائق الآن 💬",
            f"🎲 <b>تذكير عشوائي!</b>\nجرّب تفكر بـ {flag} {name} لـ 5 دقائق 🧠",
        ])
        await send(msg, f"لهجة_{name}","dialect")

async def job_voice_evening():
    if is_active("voice"):
        await send(f"╔══════════════╗\n  🎙️ <b>تدريب صوت مسائي</b>\n╚══════════════╝\n\n{pick('voice_evening')}",
                   "صوت_مسائي","voice")

async def job_dinner_remind():
    await send("⏰ <b>العشاء بعد 5 دقائق!</b>\nجهّز وجبتك 🍛","عشاء","meals")
async def job_dinner():
    await send("🍛 <b>وقت العشاء!</b>\nتغدَّ بهدوء — استحققته بعد يوم منتج 🌙","عشاء","meals")

async def job_fitness():
    if is_active("fitness") and is_work():
        await send(f"╔══════════════╗\n  💪 <b>تدريب اللياقة</b> — 45 دقيقة\n╚══════════════╝\n\n{pick('fitness')}",
                   "لياقة","fitness")

async def job_jaw2():
    if is_active("routine"):
        await send(f"💆 <b>تمارين الفكين — جلسة ثانية</b>\n\n{pick('jaw')}","فكين_2","routine")

async def job_review_remind():
    if is_active("study"):
        await send("⏰ <b>مراجعة MBA بعد 5 دقائق!</b>\nجهّز ملاحظاتك 📖","مراجعة_MBA","study")
async def job_review():
    if is_active("study"):
        await send("╔══════════════╗\n  📖 <b>مراجعة MBA</b> — 30 دقيقة\n╚══════════════╝\n\n"
                   "راجع ما درسته اليوم وثبّته في ذاكرتك 🧠\n<i>التكرار سر التميز!</i>",
                   "مراجعة_MBA","study")

async def job_review_fri_remind():
    if is_active("study"):
        await send("⏰ <b>مراجعة الجمعة بعد 5 دقائق!</b> 📖","مراجعة_MBA","study")
async def job_review_fri():
    if is_active("study"):
        await send("📖 <b>مراجعة MBA — الجمعة</b>\n\nأسبوع كامل من المعرفة — راجعه بتمعّن 🌙\n<i>من راجع نجح!</i>",
                   "مراجعة_MBA","study")

async def job_night():
    if is_active("routine"):
        await send(f"━━━━━━━━━━━━━━━━\n{pick('night_routine')}","روتين_ليلي","routine")

# ─── إعداد المُجدوِل ──────────────────────────────────────
def setup_scheduler():
    s = AsyncIOScheduler(timezone=TZ)
    def c(**kw): return CronTrigger(timezone=TZ,**kw)

    s.add_job(job_summary,          c(hour=9,  minute=55))
    s.add_job(job_skin,             c(hour=10, minute=0))
    s.add_job(job_breakfast_remind, c(hour=10, minute=25))
    s.add_job(job_breakfast,        c(hour=10, minute=30))
    s.add_job(job_voice_morning,    c(hour=11, minute=0))
    s.add_job(job_snack1,           c(hour=12, minute=0))
    s.add_job(job_dialect,          c(hour=12, minute=30))
    s.add_job(job_study_remind,     c(hour=13, minute=25))
    s.add_job(job_study,            c(hour=13, minute=30))
    s.add_job(job_dialect_random,   c(hour=14, minute=30))
    s.add_job(job_lunch_remind,     c(hour=15, minute=25))
    s.add_job(job_lunch,            c(hour=15, minute=30))
    s.add_job(job_jaw1,             c(hour=17, minute=0))
    s.add_job(job_snack2,           c(hour=18, minute=30))
    s.add_job(job_dialect_random,   c(hour=19, minute=0))
    s.add_job(job_voice_evening,    c(hour=21, minute=0))
    s.add_job(job_dinner_remind,    c(hour=21, minute=25))
    s.add_job(job_dinner,           c(hour=21, minute=30))
    s.add_job(job_fitness,          c(hour=22, minute=0,  day_of_week="0,1,2,3,6"))
    s.add_job(job_jaw2,             c(hour=22, minute=0))
    s.add_job(job_review_remind,    c(hour=23, minute=25, day_of_week="0,1,2,3,5,6"))
    s.add_job(job_review,           c(hour=23, minute=30, day_of_week="0,1,2,3,5,6"))
    s.add_job(job_review_fri_remind,c(hour=22, minute=55, day_of_week="4"))
    s.add_job(job_review_fri,       c(hour=23, minute=0,  day_of_week="4"))
    s.add_job(job_night,            c(hour=0,  minute=0))

    # ماء كل ساعة
    cups_map = {10:1,11:2,12:3,13:4,14:5,15:6,16:7,17:8,
                18:9,19:10,20:11,21:12,22:13,23:14,0:15}
    for h in list(range(10,24)) + [0]:
        cup = cups_map.get(h,"")
        bar = "🔵"*min(cup,10) + "⚪"*max(0,10-cup) if isinstance(cup,int) else ""
        s.add_job(job_water, c(hour=h,minute=0), args=[cup, bar])

    s.start()
    log.info(f"✅ Scheduler started — {len(s.get_jobs())} jobs")

# ─── عرض ملاحظات ─────────────────────────────────────────
async def show_plan_notes(query, plan_key, edit=False):
    items = notes_db.get(plan_key,[])
    title = PLAN_NAMES.get(plan_key,plan_key)
    text  = (f"📝 <b>ملاحظات {title}</b>\n\n" +
             ("\n".join(f"{i+1}. {n}" for i,n in enumerate(items))
              if items else "<i>لا توجد ملاحظات — أضف أولاً!</i>"))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ أضف ملاحظة / رابط", callback_data=f"addnote|{plan_key}")],
        [InlineKeyboardButton("🗑️ احذف ملاحظة",       callback_data=f"delnote|{plan_key}")],
        [InlineKeyboardButton("← رجوع",               callback_data="notes|menu")],
    ])
    if edit: await query.edit_message_text(text,parse_mode="HTML",reply_markup=kb)
    else:    await _bot_ref.send_message(chat_id=CHAT_ID,text=text,parse_mode="HTML",reply_markup=kb)

# ─── Callback Handler ─────────────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.split("|",2)
    action = parts[0]
    task   = parts[1] if len(parts)>1 else ""

    if action=="notes":
        buttons=[[InlineKeyboardButton(n,callback_data=f"viewnotes|{k}")] for k,n in PLAN_NAMES.items()]
        await query.edit_message_text("📝 <b>ملاحظاتي</b>\n\nاختر الخطة:",
            parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons)); return

    if action=="viewnotes": await show_plan_notes(query,task,edit=True); return

    if action=="addnote":
        awaiting_note[int(CHAT_ID)]=task
        await query.edit_message_text(
            f"📝 <b>إضافة ملاحظة — {PLAN_NAMES.get(task,task)}</b>\n\n"
            f"أرسل الملاحظة أو الرابط الآن:\n\n"
            f"<i>مثال:\n• https://youtube.com/...\n• ركّز على الفصل الثالث\n• تمرين تنفس 4-7-8</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء",callback_data=f"viewnotes|{task}")]])); return

    if action=="delnote":
        items=notes_db.get(task,[])
        if not items: await query.answer("لا توجد ملاحظات",show_alert=True); return
        buttons=[[InlineKeyboardButton(f"🗑️ {i+1}. {n[:35]}{'...'if len(n)>35 else ''}",
            callback_data=f"delitem|{task}|{i}")] for i,n in enumerate(items)]
        buttons.append([InlineKeyboardButton("← رجوع",callback_data=f"viewnotes|{task}")])
        await query.edit_message_text("🗑️ <b>اختر الملاحظة للحذف:</b>",
            parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons)); return

    if action=="delitem":
        sub=task.split("|"); key=sub[0]; idx=int(sub[1]) if len(sub)>1 else -1
        if 0<=idx<len(notes_db.get(key,[])):
            notes_db[key].pop(idx); save_notes(notes_db); await query.answer("✅ تم الحذف")
        await show_plan_notes(query,key,edit=True); return

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
        ctx.application.job_queue.run_once(lambda c,fn=ra: __import__('asyncio').get_event_loop().create_task(fn()),when=timedelta(minutes=mins))
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(chat_id=CHAT_ID,parse_mode="HTML",
            text=f"⏰ <b>تأجيل {label}</b>\n{task}\nسأذكّرك الساعة <b>{fire}</b> 🕐")

    elif action=="missed":
        await query.edit_message_reply_markup(reply_markup=None)
        await ctx.bot.send_message(chat_id=CHAT_ID,parse_mode="HTML",
            text=f"📝 <b>سُجّلت كفائتة:</b> {task}\n<i>لا بأس، غداً أفضل 💪</i>")

    elif action=="settings":
        if task=="pause":
            buttons=[[InlineKeyboardButton(n,callback_data=f"pause|{k}")] for k,n in PLAN_NAMES.items()]
            await query.edit_message_text("⏸ <b>أي خطة توقفها مؤقتاً؟</b>",
                parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
        elif task=="resume":
            if not paused_plans: await query.edit_message_text("✅ جميع الخطط تعمل!",parse_mode="HTML"); return
            buttons=[[InlineKeyboardButton(PLAN_NAMES.get(p,p),callback_data=f"resume|{p}")] for p in paused_plans]
            await query.edit_message_text("▶️ <b>أي خطة تستأنفها؟</b>",
                parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
        elif task=="status":
            lines="\n".join(f"{'⏸'if k in paused_plans else '✅'}  {n}" for k,n in PLAN_NAMES.items())
            await query.edit_message_text(f"📋 <b>حالة الخطط:</b>\n\n{lines}",parse_mode="HTML")

    elif action=="pause":
        paused_plans.add(task)
        await query.edit_message_text(f"⏸ <b>تم إيقاف {PLAN_NAMES.get(task,task)}</b>\nيمكنك استئنافها من ⚙️ الإعدادات.",parse_mode="HTML")

    elif action=="resume":
        paused_plans.discard(task)
        await query.edit_message_text(f"▶️ <b>تم استئناف {PLAN_NAMES.get(task,task)}</b> ✅",parse_mode="HTML")

# ─── Text Handler ─────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt=update.message.text; cid=update.effective_chat.id

    if cid in awaiting_note:
        pk=awaiting_note.pop(cid); pn=PLAN_NAMES.get(pk,pk)
        notes_db.setdefault(pk,[]).append(txt); save_notes(notes_db)
        await update.message.reply_text(
            f"✅ <b>تمت الإضافة!</b>\n\n📌 <b>{pn}</b>\n📝 <code>{txt}</code>\n\n"
            f"<i>ستظهر مع كل تذكير لهذه الخطة 🎯</i>",
            parse_mode="HTML",reply_markup=MAIN_KB); return

    if txt=="📋 جدولي اليوم":   await morning_summary()
    elif txt=="💧 اشرب ماء الآن":
        await update.message.reply_text(f"💧 <b>اشرب 330 مل الآن!</b>\n{pick('water')} 🥤",parse_mode="HTML")
    elif txt=="✅ تم ✓":
        c=random.choice(["أحسنت! 🌟","رائع! 💪","ممتاز! 🔥"])
        await update.message.reply_text(f"✅ <b>تم!</b> — {last_task.get('name','المهمة')}\n<i>{c}</i>",
            parse_mode="HTML",reply_markup=MAIN_KB)
    elif txt=="⏰ أجّل 15 دقيقة":
        name=last_task.get("name","المهمة"); fire=(datetime.now(TZ)+timedelta(minutes=15)).strftime("%H:%M")
        async def ra(t=name): await send(f"⏰ <b>تذكير مؤجّل</b> — {t}",t)
        ctx.application.job_queue.run_once(lambda c,fn=ra:__import__('asyncio').get_event_loop().create_task(fn()),when=timedelta(minutes=15))
        await update.message.reply_text(f"⏰ <b>تأجيل 15 دقيقة</b>\n{name}\nالساعة <b>{fire}</b> 🕐",parse_mode="HTML")
    elif txt=="📝 ملاحظاتي":
        buttons=[[InlineKeyboardButton(n,callback_data=f"viewnotes|{k}")] for k,n in PLAN_NAMES.items()]
        await update.message.reply_text("📝 <b>ملاحظاتي</b>\n\nاختر الخطة:",
            parse_mode="HTML",reply_markup=InlineKeyboardMarkup(buttons))
    elif txt=="📊 تقريري":
        days_ar={0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",4:"الجمعة",5:"السبت",6:"الأحد"}
        flag,dial,_=dialect_info(); total=sum(len(v) for v in notes_db.values())
        await update.message.reply_text(
            f"📊 <b>تقرير اليوم</b>\n━━━━━━━━━━━━━━━━\n"
            f"📅 {days_ar[weekday()]}  {'🏢 دوام'if is_work() else '🌴 إجازة'}\n"
            f"{flag} اللهجة: <b>{dial}</b>\n"
            f"✅ خطط نشطة: <b>{len(PLAN_NAMES)-len(paused_plans)}</b> من {len(PLAN_NAMES)}\n"
            f"📝 ملاحظاتك: <b>{total}</b>\n━━━━━━━━━━━━━━━━\n"
            f"<i>استمر — أنت على الطريق الصح! 🚀</i>",
            parse_mode="HTML",reply_markup=MAIN_KB)
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

# ─── post_init ─────────────────────────────────────────────
async def post_init(app: Application):
    global _bot_ref
    _bot_ref = app.bot
    setup_scheduler()
    log.info("✅ Bot initialized successfully")

# ─── main ─────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
