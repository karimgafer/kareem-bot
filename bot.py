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

# ─── مساعدات ─────────────────────────────────────────────
def now_riyadh():
    return datetime.now(TZ)

def weekday():
    return now_riyadh().weekday()  # 0=Mon … 6=Sun

def is_work_day():
    return weekday() not in (4, 5)  # الجمعة=4  السبت=5

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

async def send(bot, text: str):
    await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")

# ─── رسائل التذكير ────────────────────────────────────────

async def morning_summary(bot):
    days = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
            4:"الجمعة",5:"السبت",6:"الأحد"}
    day  = days[weekday()]
    flag, dial = dialect_info()
    dur  = "3 ساعات" if not is_work_day() else "90 دقيقة"
    fit  = "🛌 راحة" if not is_work_day() else "💪 45 دق"
    await send(bot,
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

# ─── إعداد المُجدوِل ──────────────────────────────────────
def setup_scheduler(bot):
    s = AsyncIOScheduler(timezone=TZ)
    def cron(**kw): return CronTrigger(timezone=TZ, **kw)

    # ملخص الصباح 9:55
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(morning_summary(bot)),
              cron(hour=9, minute=55))

    async def msg(text): await send(bot, text)

    # روتين بشرة 10:00
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("💆 <b>روتين بشرة صباحي</b> ✨")), cron(hour=10, minute=0))

    # ماء كل ساعة 10:00 → 00:00
    for h in list(range(10, 24)) + [0]:
        cups = {10:1,11:2,12:3,13:4,14:5,15:6,16:7,17:8,18:9,19:10,20:11,21:12,22:13,23:14,0:15}
        cup = cups.get(h, "")
        s.add_job(lambda c=cup: __import__('asyncio').get_event_loop().create_task(
            msg(f"💧 <b>اشرب ماءك</b> — 330 مل 🥤 <i>(كوب {c} من 15)</i>")),
            cron(hour=h, minute=0))

    # فطار
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍳 <b>الفطار بعد 5 دقائق</b> ⏰")), cron(hour=10, minute=25))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍳 <b>وقت الفطار!</b> 🥗")), cron(hour=10, minute=30))

    # تدريب صوت صباحي
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🎙️ <b>تدريب الصوت الصباحي</b> — 15 دقيقة 🎵")), cron(hour=11, minute=0))

    # سناك 1
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍎 <b>سناك 1</b> 😋")), cron(hour=12, minute=0))

    # لهجة 12:30
    async def dialect_msg():
        flag, name = dialect_info()
        await send(bot, f"{flag} <b>تدريب {name}</b> — 20 دقيقة 💬")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(dialect_msg()),
              cron(hour=12, minute=30))

    # مذاكرة
    async def study_msg():
        dur = "3 ساعات" if not is_work_day() else "90 دقيقة"
        await send(bot, f"📚 <b>المذاكرة بعد 5 دقائق</b> — {dur} ⏰")
    async def study_start():
        dur = "3 ساعات" if not is_work_day() else "90 دقيقة"
        await send(bot, f"📚 <b>وقت مذاكرة MBA!</b> — {dur} 🧠")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(study_msg()),
              cron(hour=13, minute=25))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(study_start()),
              cron(hour=13, minute=30))

    # غداء
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍽️ <b>الغداء بعد 5 دقائق</b> ⏰")), cron(hour=15, minute=25))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍽️ <b>وقت الغداء!</b> 🍛")), cron(hour=15, minute=30))

    # فكين أولى 17:00
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("💆 <b>تمارين الفكين — الجلسة الأولى</b> 10 دق 😬")), cron(hour=17, minute=0))

    # سناك 2
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍎 <b>سناك 2</b> 🍌")), cron(hour=18, minute=30))

    # تدريب صوت مسائي
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🎙️ <b>تدريب الصوت المسائي</b> — 15 دقيقة 🎙️")), cron(hour=21, minute=0))

    # عشاء
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍛 <b>العشاء بعد 5 دقائق</b> ⏰")), cron(hour=21, minute=25))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🍛 <b>وقت العشاء!</b> 🌙")), cron(hour=21, minute=30))

    # لياقة — أيام عمل فقط (أحد-خميس)
    async def fitness_msg():
        if is_work_day():
            await send(bot, "💪 <b>تذكير اللياقة!</b> — 45 دقيقة 🏋️")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(fitness_msg()),
              cron(hour=22, minute=0, day_of_week="0,1,2,3,6"))

    # فكين ثانية
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("💆 <b>تمارين الفكين — الجلسة الثانية</b> 10 دق 😬")), cron(hour=22, minute=0))

    # مراجعة — كل الأيام ما عدا الجمعة
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("📖 <b>مراجعة MBA بعد 5 دقائق</b> ⏰")),
        cron(hour=23, minute=25, day_of_week="0,1,2,3,5,6"))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("📖 <b>مراجعة MBA</b> — 30 دقيقة 🧠")),
        cron(hour=23, minute=30, day_of_week="0,1,2,3,5,6"))

    # مراجعة الجمعة 23:00
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("📖 <b>مراجعة MBA بعد 5 دقائق</b> — جمعة ⏰")),
        cron(hour=22, minute=55, day_of_week="4"))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("📖 <b>مراجعة MBA — جمعة</b> 30 دق 🧠")),
        cron(hour=23, minute=0, day_of_week="4"))

    # روتين ليلي 00:00
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(
        msg("🌙 <b>روتين الليل</b>\n💆 شعر + بشرة + أسنان\n💧 آخر كوب ماء!\n\n<i>أحسنت اليوم كريم! 🌟</i>")),
        cron(hour=0, minute=0))

    # تذكيرات لهجة عشوائية
    async def rand_dial():
        flag, name = dialect_info()
        await send(bot, f"⚡ <b>تذكير عشوائي!</b>\nتكلّم {flag} {name} لمدة 5 دقائق 💬")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(rand_dial()),
              cron(hour=14, minute=30))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(rand_dial()),
              cron(hour=19, minute=0))

    s.start()
    log.info(f"✅ Scheduler started — {len(s.get_jobs())} jobs")

# ─── أوامر البوت ──────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"مرحباً كريم! 👋\n\nالبوت يعمل ✅\n\nمعرّف محادثتك:\n<code>{cid}</code>",
        parse_mode="HTML"
    )

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await morning_summary(ctx.bot)

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    flag, dial = dialect_info()
    await update.message.reply_text(
        f"✅ <b>البوت يعمل</b>\n"
        f"⏰ {now_riyadh().strftime('%H:%M')}\n"
        f"📅 {'دوام' if is_work_day() else 'إجازة'}\n"
        f"{flag} {dial}",
        parse_mode="HTML"
    )

async def cmd_water(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💧 اشرب كوب ماء الآن! 330 مل 🥤")

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ <b>ممتاز!</b> 🌟", parse_mode="HTML")

# ─── post_init: يشغّل المُجدوِل بعد بناء التطبيق ──────────
async def post_init(application: Application) -> None:
    setup_scheduler(application.bot)
    log.info("Bot initialized and scheduler running.")

# ─── نقطة الدخول ──────────────────────────────────────────
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("today",  cmd_today))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("water",  cmd_water))
    app.add_handler(CommandHandler("done",   cmd_done))

    log.info("Starting bot...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
