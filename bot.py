import asyncio
import logging
import os
from datetime import datetime

import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ─── الإعدادات ────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID   = os.environ.get("CHAT_ID",   "YOUR_CHAT_ID_HERE")
TZ        = pytz.timezone("Asia/Riyadh")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot_ref = None   # يُعيَّن عند بدء التشغيل

# ─── مساعدات ─────────────────────────────────────────────
def now_riyadh():
    return datetime.now(TZ)

def weekday():
    """0=Mon … 6=Sun"""
    return now_riyadh().weekday()

def is_work_day():
    return weekday() not in (4, 5)   # الجمعة=4  السبت=5

def dialect_info():
    d = {
        6: ("🇸🇦", "لهجة سعودية"),
        0: ("🇸🇦", "لهجة سعودية"),
        1: ("🇲🇦", "لهجة مغربية"),
        2: ("🇲🇦", "لهجة مغربية"),
        3: ("🇬🇧", "لهجة إنجليزية"),
        4: ("🇬🇧", "لهجة إنجليزية"),
        5: ("🗣️",  "لهجة مرنة"),
    }
    return d.get(weekday(), ("🗣️", "لهجة"))

async def send(text: str):
    if bot_ref:
        await bot_ref.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")

# ─── رسائل التذكير ────────────────────────────────────────

async def morning_summary():
    days = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
            4:"الجمعة",5:"السبت",6:"الأحد"}
    day  = days[weekday()]
    flag, dial = dialect_info()
    dur  = "3 ساعات" if not is_work_day() else "90 دقيقة"
    fit  = "🛌 راحة" if not is_work_day() else "💪 45 دق"
    await send(
        f"☀️ <b>صباح الخير كريم!</b>\n\n"
        f"📅 <b>{day}</b> — {'🏢 دوام' if is_work_day() else '🌴 إجازة'}\n\n"
        f"<b>جدولك اليوم:</b>\n"
        f"10:00 💆 روتين بشرة\n"
        f"10:30 🍳 فطار\n"
        f"11:00 🎙️ تدريب صوت\n"
        f"12:00 🍎 سناك 1\n"
        f"12:30 {flag} {dial}\n"
        f"13:30 📚 مذاكرة MBA ({dur})\n"
        f"15:30 🍽️ غداء\n"
        f"18:30 🍎 سناك 2\n"
        f"21:00 🎙️ تدريب صوت\n"
        f"21:30 🍛 عشاء\n"
        f"22:00 {fit}\n"
        f"23:30 📖 مراجعة MBA\n"
        f"00:00 🌙 روتين ليلي\n\n"
        f"<i>💧 تذكير ماء كل ساعة — يلا بقوة! 🚀</i>"
    )

async def skin_morning():
    await send("💆 <b>روتين بشرة صباحي</b>\nابدأ يومك بالعناية! ✨")

async def breakfast_remind():
    await send("🍳 <b>الفطار بعد 5 دقائق</b> — الساعة 10:30 ⏰")

async def breakfast():
    await send("🍳 <b>وقت الفطار!</b> 🥗\nلا تتأخر!")

async def water():
    h = now_riyadh().hour
    cups = {10:1,11:2,12:3,13:4,14:5,15:6,16:7,17:8,18:9,19:10,20:11,21:12,22:13,23:14,0:15}
    cup = cups.get(h, "")
    await send(f"💧 <b>اشرب ماءك الآن</b> — 330 مل 🥤\n<i>كوب رقم {cup} من 15</i>")

async def voice_morning():
    await send("🎙️ <b>تدريب الصوت الصباحي</b> — 15 دقيقة\nصوتك أصفى ما يكون الآن 🎵")

async def snack1():
    await send("🍎 <b>سناك 1</b> — وجبة خفيفة صحية 😋")

async def dialect():
    flag, name = dialect_info()
    await send(f"{flag} <b>تدريب {name}</b> — 20 دقيقة\n💬 تكلّم بها الآن!")

async def study_remind():
    dur = "3 ساعات" if not is_work_day() else "90 دقيقة"
    await send(f"📚 <b>المذاكرة بعد 5 دقائق</b> — {dur} ⏰")

async def study():
    dur = "3 ساعات" if not is_work_day() else "90 دقيقة"
    await send(f"📚 <b>وقت مذاكرة MBA!</b> — {dur}\n🧠 ركّز وابدأ الآن!")

async def lunch_remind():
    await send("🍽️ <b>الغداء بعد 5 دقائق</b> — الساعة 3:30م ⏰")

async def lunch():
    await send("🍽️ <b>وقت الغداء!</b> 🍛")

async def jaw1():
    await send("💆 <b>تمارين الفكين — الجلسة الأولى</b>\n10 دقائق 😬")

async def snack2():
    await send("🍎 <b>سناك 2</b> — بين الغداء والعشاء 🍌")

async def voice_evening():
    await send("🎙️ <b>تدريب الصوت المسائي</b> — 15 دقيقة 🎙️")

async def dinner_remind():
    await send("🍛 <b>العشاء بعد 5 دقائق</b> — الساعة 9:30م ⏰")

async def dinner():
    await send("🍛 <b>وقت العشاء!</b> 🌙")

async def fitness():
    if is_work_day():
        await send("💪 <b>تذكير اللياقة!</b> — 45 دقيقة\n🏋️ حان وقت التمرين المسائي!")

async def jaw2():
    await send("💆 <b>تمارين الفكين — الجلسة الثانية</b>\n10 دقائق 😬")

async def review_remind_normal():
    await send("📖 <b>مراجعة MBA بعد 5 دقائق</b> ⏰")

async def review_normal():
    await send("📖 <b>مراجعة MBA</b> — 30 دقيقة\n🧠 راجع ما درسته اليوم!")

async def review_remind_friday():
    await send("📖 <b>مراجعة MBA بعد 5 دقائق</b> — جمعة ⏰")

async def review_friday():
    await send("📖 <b>مراجعة MBA — جمعة</b>\n30 دقيقة 🧠")

async def night_routine():
    await send(
        "🌙 <b>روتين الليل</b>\n\n"
        "💆 شعر + بشرة + أسنان\n"
        "💧 آخر كوب ماء!\n\n"
        "<i>أحسنت اليوم كريم! 🌟</i>"
    )

async def random_dialect_reminder():
    flag, name = dialect_info()
    await send(f"⚡ <b>تذكير عشوائي!</b>\nتكلّم {flag} {name} الآن لمدة 5 دقائق 💬")

# ─── إعداد المُجدوِل ──────────────────────────────────────
def setup_scheduler(bot):
    global bot_ref
    bot_ref = bot
    s = AsyncIOScheduler(timezone=TZ)

    def cron(**kw): return CronTrigger(timezone=TZ, **kw)

    # ملخص الصباح
    s.add_job(morning_summary,      cron(hour=9,  minute=55))

    # روتين بشرة
    s.add_job(skin_morning,         cron(hour=10, minute=0))

    # ماء كل ساعة من 10 صباحاً حتى منتصف الليل
    for h in list(range(10, 24)) + [0]:
        s.add_job(water,            cron(hour=h,  minute=0))

    # فطار
    s.add_job(breakfast_remind,     cron(hour=10, minute=25))
    s.add_job(breakfast,            cron(hour=10, minute=30))

    # تدريب صوت صباحي
    s.add_job(voice_morning,        cron(hour=11, minute=0))

    # سناك 1
    s.add_job(snack1,               cron(hour=12, minute=0))

    # لهجة
    s.add_job(dialect,              cron(hour=12, minute=30))

    # مذاكرة
    s.add_job(study_remind,         cron(hour=13, minute=25))
    s.add_job(study,                cron(hour=13, minute=30))

    # غداء
    s.add_job(lunch_remind,         cron(hour=15, minute=25))
    s.add_job(lunch,                cron(hour=15, minute=30))

    # فكين أولى
    s.add_job(jaw1,                 cron(hour=17, minute=0))

    # سناك 2
    s.add_job(snack2,               cron(hour=18, minute=30))

    # تدريب صوت مسائي
    s.add_job(voice_evening,        cron(hour=21, minute=0))

    # عشاء
    s.add_job(dinner_remind,        cron(hour=21, minute=25))
    s.add_job(dinner,               cron(hour=21, minute=30))

    # لياقة — أيام عمل فقط (أحد-خميس)
    s.add_job(fitness,              cron(hour=22, minute=0, day_of_week="0,1,2,3,6"))

    # فكين ثانية
    s.add_job(jaw2,                 cron(hour=22, minute=0))

    # مراجعة — كل الأيام ما عدا الجمعة
    s.add_job(review_remind_normal, cron(hour=23, minute=25, day_of_week="0,1,2,3,5,6"))
    s.add_job(review_normal,        cron(hour=23, minute=30, day_of_week="0,1,2,3,5,6"))

    # مراجعة الجمعة
    s.add_job(review_remind_friday, cron(hour=22, minute=55, day_of_week="4"))
    s.add_job(review_friday,        cron(hour=23, minute=0,  day_of_week="4"))

    # روتين ليلي
    s.add_job(night_routine,        cron(hour=0,  minute=0))

    # تذكيرات لهجة عشوائية — مرتين يومياً
    s.add_job(random_dialect_reminder, cron(hour=14, minute=30))
    s.add_job(random_dialect_reminder, cron(hour=19, minute=0))

    s.start()
    log.info(f"Scheduler started — {len(s.get_jobs())} jobs")
    return s

# ─── أوامر البوت ──────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"مرحباً كريم! 👋\n\n"
        f"البوت يعمل الآن ✅\n\n"
        f"معرّف محادثتك:\n<code>{cid}</code>\n\n"
        f"ضع هذا الرقم في متغيّر CHAT_ID ثم أعد التشغيل.",
        parse_mode="HTML"
    )

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await morning_summary()

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now = now_riyadh().strftime("%H:%M — %A")
    work = "دوام ✅" if is_work_day() else "إجازة 🌴"
    flag, dial = dialect_info()
    await update.message.reply_text(
        f"✅ <b>البوت يعمل</b>\n\n"
        f"⏰ الوقت: {now}\n"
        f"📅 اليوم: {work}\n"
        f"{flag} اللهجة: {dial}",
        parse_mode="HTML"
    )

async def cmd_water(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💧 اشرب كوب ماء الآن! 330 مل 🥤")

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ <b>ممتاز!</b> تم تسجيل الإنجاز 🌟", parse_mode="HTML")

# ─── نقطة الدخول ──────────────────────────────────────────
async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("water",  cmd_water))
    app.add_handler(CommandHandler("done",   cmd_done))

    await app.initialize()
    setup_scheduler(app.bot)

    log.info("Bot is running...")
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
