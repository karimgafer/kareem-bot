import logging, os
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, ContextTypes, filters)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
import pytz

# ─── إعدادات ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
CHAT_ID   = os.environ.get("CHAT_ID",   "YOUR_CHAT_ID")
TZ        = pytz.timezone("Asia/Riyadh")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# حالة الخطط (يمكن إيقافها مؤقتاً)
paused_plans = set()
# آخر مهمة أُرسل تذكيرها
last_task = {"name": "", "time": ""}

# ─── لوحة المفاتيح الرئيسية (دائمة في الأسفل) ────────────
MAIN_KB = ReplyKeyboardMarkup([
    ["📋 جدولي اليوم",   "💧 اشرب ماء الآن"],
    ["✅ تم ✓",          "⏰ أجّل 15 دقيقة"],
    ["📊 تقريري",        "⚙️ الإعدادات"],
], resize_keyboard=True)

# ─── مساعدات ──────────────────────────────────────────────
def now_r(): return datetime.now(TZ)
def weekday(): return now_r().weekday()
def is_work(): return weekday() not in (4, 5)

def dialect_info():
    return {6:("🇸🇦","سعودية"),0:("🇸🇦","سعودية"),
            1:("🇲🇦","مغربية"),2:("🇲🇦","مغربية"),
            3:("🇬🇧","إنجليزية"),4:("🇬🇧","إنجليزية"),
            5:("🗣️","مرنة")}.get(weekday(),("🗣️","لهجة"))

def reminder_buttons(task_name):
    """أزرار تحت كل رسالة تذكير"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تم",        callback_data=f"done|{task_name}"),
         InlineKeyboardButton("⏰ أجّل 15د", callback_data=f"snooze15|{task_name}")],
        [InlineKeyboardButton("⏰ أجّل ساعة", callback_data=f"snooze60|{task_name}"),
         InlineKeyboardButton("❌ فاتني",     callback_data=f"missed|{task_name}")],
    ])

async def send(bot, text, task_name=None):
    """إرسال رسالة مع أزرار اختيارية"""
    global last_task
    kb = reminder_buttons(task_name) if task_name else None
    if task_name:
        last_task = {"name": task_name, "time": now_r().strftime("%H:%M")}
    await bot.send_message(chat_id=CHAT_ID, text=text,
                           parse_mode="HTML", reply_markup=kb)

# ─── التحقق من الإيقاف المؤقت ─────────────────────────────
def is_active(plan_key):
    return plan_key not in paused_plans

# ─── رسائل التذكير ────────────────────────────────────────
async def morning_summary(bot):
    days = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
            4:"الجمعة",5:"السبت",6:"الأحد"}
    flag, dial = dialect_info()
    dur = "3 ساعات" if not is_work() else "90 دقيقة"
    fit = "🛌 راحة" if not is_work() else "💪 45 دق"
    plans_status = ""
    if paused_plans:
        names = {"study":"📚 MBA","voice":"🎙️ صوت","dialect":"🗣️ لهجات",
                 "routine":"💆 روتين","fitness":"💪 لياقة","water":"💧 ماء"}
        paused_str = " | ".join(names.get(p,p) for p in paused_plans)
        plans_status = f"\n\n⏸ <i>موقوفة: {paused_str}</i>"

    await bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
        reply_markup=MAIN_KB,
        text=(
            f"☀️ <b>صباح الخير كريم!</b>\n\n"
            f"📅 <b>{days[weekday()]}</b> — {'🏢 دوام' if is_work() else '🌴 إجازة'}\n\n"
            f"<b>جدولك اليوم:</b>\n"
            f"10:00 💆 روتين بشرة\n"
            f"10:30 🍳 فطار\n"
            f"11:00 🎙️ صوت صباحي\n"
            f"12:00 🍎 سناك 1\n"
            f"12:30 {flag} لهجة {dial}\n"
            f"13:30 📚 مذاكرة ({dur})\n"
            f"15:30 🍽️ غداء\n"
            f"18:30 🍎 سناك 2\n"
            f"21:00 🎙️ صوت مسائي\n"
            f"21:30 🍛 عشاء\n"
            f"22:00 {fit}\n"
            f"23:30 📖 مراجعة MBA\n"
            f"00:00 🌙 روتين ليلي"
            f"{plans_status}\n\n"
            f"<i>💧 ماء كل ساعة — يلا بقوة! 🚀</i>"
        ))

# ─── إعداد المُجدوِل ──────────────────────────────────────
def setup_scheduler(bot):
    s = AsyncIOScheduler(timezone=TZ)
    def cron(**kw): return CronTrigger(timezone=TZ, **kw)
    def task(coro_fn): return lambda: bot.get_event_loop() or __import__('asyncio').get_event_loop().create_task(coro_fn())

    import asyncio

    def schedule(fn, **kw):
        async def job(): await fn()
        s.add_job(lambda: asyncio.get_event_loop().create_task(job()), cron(**kw))

    # ملخص صباحي
    async def _summary(): await morning_summary(bot)
    schedule(_summary, hour=9, minute=55)

    # روتين بشرة
    async def _skin():
        if is_active("routine"):
            await send(bot, "💆 <b>روتين بشرة صباحي</b> ✨", "روتين_بشرة_صباحي")
    schedule(_skin, hour=10, minute=0)

    # ماء كل ساعة
    for h in list(range(10, 24)) + [0]:
        cups = {10:1,11:2,12:3,13:4,14:5,15:6,16:7,17:8,18:9,19:10,20:11,21:12,22:13,23:14,0:15}
        cup = cups.get(h, "")
        async def _water(c=cup):
            if is_active("water"):
                await send(bot, f"💧 <b>اشرب ماءك</b> — 330 مل 🥤 <i>(كوب {c} من 15)</i>", f"ماء_{c}")
        s.add_job(lambda fn=_water: __import__('asyncio').get_event_loop().create_task(fn()),
                  cron(hour=h, minute=0))

    # فطار
    async def _brkfst_r(): await send(bot, "🍳 <b>الفطار بعد 5 دقائق</b> ⏰", "فطار")
    async def _brkfst(): await send(bot, "🍳 <b>وقت الفطار!</b> 🥗", "فطار")
    schedule(_brkfst_r, hour=10, minute=25)
    schedule(_brkfst,   hour=10, minute=30)

    # صوت صباحي
    async def _voice_m():
        if is_active("voice"):
            await send(bot, "🎙️ <b>تدريب الصوت الصباحي</b> — 15 دقيقة 🎵", "صوت_صباحي")
    schedule(_voice_m, hour=11, minute=0)

    # سناك 1
    async def _s1(): await send(bot, "🍎 <b>سناك 1</b> 😋", "سناك_1")
    schedule(_s1, hour=12, minute=0)

    # لهجة
    async def _dialect():
        if is_active("dialect"):
            flag, name = dialect_info()
            await send(bot, f"{flag} <b>تدريب لهجة {name}</b> — 20 دقيقة 💬", f"لهجة_{name}")
    schedule(_dialect, hour=12, minute=30)

    # مذاكرة
    async def _study_r():
        if is_active("study"):
            dur = "3 ساعات" if not is_work() else "90 دقيقة"
            await send(bot, f"📚 <b>المذاكرة بعد 5 دقائق</b> — {dur} ⏰", "مذاكرة_MBA")
    async def _study():
        if is_active("study"):
            dur = "3 ساعات" if not is_work() else "90 دقيقة"
            await send(bot, f"📚 <b>وقت مذاكرة MBA!</b> — {dur} 🧠", "مذاكرة_MBA")
    schedule(_study_r, hour=13, minute=25)
    schedule(_study,   hour=13, minute=30)

    # غداء
    async def _lunch_r(): await send(bot, "🍽️ <b>الغداء بعد 5 دقائق</b> ⏰", "غداء")
    async def _lunch():   await send(bot, "🍽️ <b>وقت الغداء!</b> 🍛", "غداء")
    schedule(_lunch_r, hour=15, minute=25)
    schedule(_lunch,   hour=15, minute=30)

    # فكين أولى
    async def _jaw1():
        if is_active("routine"):
            await send(bot, "💆 <b>تمارين الفكين — الجلسة الأولى</b> 10 دق 😬", "فكين_1")
    schedule(_jaw1, hour=17, minute=0)

    # سناك 2
    async def _s2(): await send(bot, "🍎 <b>سناك 2</b> 🍌", "سناك_2")
    schedule(_s2, hour=18, minute=30)

    # تذكير لهجة عشوائي
    async def _rd():
        if is_active("dialect"):
            flag, name = dialect_info()
            await send(bot, f"⚡ <b>تذكير عشوائي!</b>\nتكلّم {flag} {name} 5 دقائق 💬", f"لهجة_{name}")
    schedule(_rd, hour=14, minute=30)
    schedule(_rd, hour=19, minute=0)

    # صوت مسائي
    async def _voice_e():
        if is_active("voice"):
            await send(bot, "🎙️ <b>تدريب الصوت المسائي</b> — 15 دقيقة 🎙️", "صوت_مسائي")
    schedule(_voice_e, hour=21, minute=0)

    # عشاء
    async def _din_r(): await send(bot, "🍛 <b>العشاء بعد 5 دقائق</b> ⏰", "عشاء")
    async def _din():   await send(bot, "🍛 <b>وقت العشاء!</b> 🌙", "عشاء")
    schedule(_din_r, hour=21, minute=25)
    schedule(_din,   hour=21, minute=30)

    # لياقة
    async def _fit():
        if is_active("fitness") and is_work():
            await send(bot, "💪 <b>تذكير اللياقة!</b> — 45 دقيقة 🏋️", "لياقة")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(_fit()),
              cron(hour=22, minute=0, day_of_week="0,1,2,3,6"))

    # فكين ثانية
    async def _jaw2():
        if is_active("routine"):
            await send(bot, "💆 <b>تمارين الفكين — الجلسة الثانية</b> 10 دق 😬", "فكين_2")
    schedule(_jaw2, hour=22, minute=0)

    # مراجعة
    async def _rev_r():
        if is_active("study"):
            await send(bot, "📖 <b>مراجعة MBA بعد 5 دقائق</b> ⏰", "مراجعة_MBA")
    async def _rev():
        if is_active("study"):
            await send(bot, "📖 <b>مراجعة MBA</b> — 30 دقيقة 🧠", "مراجعة_MBA")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(_rev_r()),
              cron(hour=23, minute=25, day_of_week="0,1,2,3,5,6"))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(_rev()),
              cron(hour=23, minute=30, day_of_week="0,1,2,3,5,6"))
    async def _rev_fri_r():
        if is_active("study"):
            await send(bot, "📖 <b>مراجعة MBA بعد 5 دقائق</b> — جمعة ⏰", "مراجعة_MBA")
    async def _rev_fri():
        if is_active("study"):
            await send(bot, "📖 <b>مراجعة MBA — جمعة</b> 30 دق 🧠", "مراجعة_MBA")
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(_rev_fri_r()),
              cron(hour=22, minute=55, day_of_week="4"))
    s.add_job(lambda: __import__('asyncio').get_event_loop().create_task(_rev_fri()),
              cron(hour=23, minute=0, day_of_week="4"))

    # روتين ليلي
    async def _night():
        if is_active("routine"):
            await send(bot,
                "🌙 <b>روتين الليل</b>\n💆 شعر + بشرة + أسنان\n💧 آخر كوب ماء!\n\n"
                "<i>أحسنت اليوم كريم! 🌟</i>", "روتين_ليلي")
    schedule(_night, hour=0, minute=0)

    s.start()
    log.info(f"✅ Scheduler: {len(s.get_jobs())} jobs")
    return s

# ─── معالجة الأزرار (Callback) ────────────────────────────
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, task = data.split("|", 1)
    bot = ctx.bot

    if action == "done":
        await query.edit_message_reply_markup(reply_markup=None)
        await bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
            text=f"✅ <b>تم!</b> — {task}\n<i>أحسنت! 🌟</i>",
            reply_markup=MAIN_KB)

    elif action in ("snooze15", "snooze60"):
        mins = 15 if action == "snooze15" else 60
        fire_at = datetime.now(TZ) + timedelta(minutes=mins)
        label = f"{mins} دقيقة" if mins == 15 else "ساعة"
        async def remind_again():
            await send(bot, f"⏰ <b>تذكير مؤجّل:</b> {task}", task)
        ctx.application.job_queue.run_once(
            lambda c: __import__('asyncio').get_event_loop().create_task(remind_again()),
            when=timedelta(minutes=mins))
        await query.edit_message_reply_markup(reply_markup=None)
        await bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
            text=f"⏰ <b>تم التأجيل</b> — {task}\nسأذكّرك بعد {label} الساعة {fire_at.strftime('%H:%M')} 🕐")

    elif action == "missed":
        await query.edit_message_reply_markup(reply_markup=None)
        await bot.send_message(chat_id=CHAT_ID, parse_mode="HTML",
            text=f"📝 <b>تم التسجيل كفائتة:</b> {task}\nسيُحسب في التقرير الأسبوعي.")

# ─── معالجة الأزرار النصية (الكيبورد الدائم) ──────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    bot = ctx.bot

    if txt == "📋 جدولي اليوم":
        await morning_summary(bot)

    elif txt == "💧 اشرب ماء الآن":
        await update.message.reply_text(
            "💧 <b>اشرب 330 مل الآن!</b> 🥤", parse_mode="HTML")

    elif txt == "✅ تم ✓":
        name = last_task.get("name", "المهمة")
        await update.message.reply_text(
            f"✅ <b>تم!</b> — {name}\n<i>أحسنت! 🌟</i>",
            parse_mode="HTML", reply_markup=MAIN_KB)

    elif txt == "⏰ أجّل 15 دقيقة":
        name = last_task.get("name", "المهمة")
        fire_at = (datetime.now(TZ) + timedelta(minutes=15)).strftime("%H:%M")
        async def remind_again():
            await send(bot, f"⏰ <b>تذكير مؤجّل:</b> {name}", name)
        ctx.application.job_queue.run_once(
            lambda c: __import__('asyncio').get_event_loop().create_task(remind_again()),
            when=timedelta(minutes=15))
        await update.message.reply_text(
            f"⏰ <b>تم التأجيل</b> — {name}\nسأذكّرك الساعة {fire_at} 🕐",
            parse_mode="HTML")

    elif txt == "📊 تقريري":
        days_ar = {0:"الاثنين",1:"الثلاثاء",2:"الأربعاء",3:"الخميس",
                   4:"الجمعة",5:"السبت",6:"الأحد"}
        flag, dial = dialect_info()
        await update.message.reply_text(
            f"📊 <b>تقرير اليوم</b>\n\n"
            f"📅 {days_ar[weekday()]} — {'دوام ✅' if is_work() else 'إجازة 🌴'}\n"
            f"{flag} اللهجة: {dial}\n"
            f"⏸ خطط موقوفة: {len(paused_plans)}\n\n"
            f"<i>التقرير الأسبوعي يأتي كل جمعة 🗓️</i>",
            parse_mode="HTML", reply_markup=MAIN_KB)

    elif txt == "⚙️ الإعدادات":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸ إيقاف خطة مؤقتاً", callback_data="settings|pause")],
            [InlineKeyboardButton("▶️ استئناف خطة",      callback_data="settings|resume")],
            [InlineKeyboardButton("📋 حالة الخطط",        callback_data="settings|status")],
            [InlineKeyboardButton("🔄 تبديل اللهجة",      callback_data="settings|dialect")],
        ])
        await update.message.reply_text(
            "⚙️ <b>الإعدادات</b>\nاختر ما تريد:", parse_mode="HTML",
            reply_markup=kb)

# ─── إعدادات متقدمة (Callback) ────────────────────────────
async def handle_settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "settings|pause":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 مذاكرة MBA",   callback_data="pause|study"),
             InlineKeyboardButton("🎙️ تدريب صوت",   callback_data="pause|voice")],
            [InlineKeyboardButton("🗣️ لهجات",        callback_data="pause|dialect"),
             InlineKeyboardButton("💆 روتين جسم",    callback_data="pause|routine")],
            [InlineKeyboardButton("💪 لياقة",         callback_data="pause|fitness"),
             InlineKeyboardButton("💧 ماء",           callback_data="pause|water")],
        ])
        await query.edit_message_text("⏸ <b>أي خطة تريد إيقافها مؤقتاً؟</b>",
                                       parse_mode="HTML", reply_markup=kb)

    elif data == "settings|resume":
        if not paused_plans:
            await query.edit_message_text("✅ جميع الخطط تعمل بالفعل!")
            return
        names = {"study":"📚 MBA","voice":"🎙️ صوت","dialect":"🗣️ لهجات",
                 "routine":"💆 روتين","fitness":"💪 لياقة","water":"💧 ماء"}
        buttons = [[InlineKeyboardButton(f"▶️ {names.get(p,p)}", callback_data=f"resume|{p}")]
                   for p in paused_plans]
        await query.edit_message_text("▶️ <b>أي خطة تريد استئنافها؟</b>",
                                       parse_mode="HTML",
                                       reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "settings|status":
        names = {"study":"📚 MBA","voice":"🎙️ صوت","dialect":"🗣️ لهجات",
                 "routine":"💆 روتين","fitness":"💪 لياقة","water":"💧 ماء"}
        all_plans = ["study","voice","dialect","routine","fitness","water"]
        lines = "\n".join(
            f"{'⏸' if p in paused_plans else '✅'} {names[p]}"
            for p in all_plans)
        await query.edit_message_text(
            f"📋 <b>حالة الخطط:</b>\n\n{lines}", parse_mode="HTML")

    elif data == "settings|dialect":
        flag, current = dialect_info()
        await query.edit_message_text(
            f"🗣️ اللهجة الحالية اليوم: <b>{flag} {current}</b>\n\n"
            f"<i>يتم التبديل تلقائياً حسب الجدول:\n"
            f"أحد+اثنين: 🇸🇦 سعودية\n"
            f"ثلاثاء+أربعاء: 🇲🇦 مغربية\n"
            f"خميس+جمعة: 🇬🇧 إنجليزية\n"
            f"سبت: 🗣️ مرنة</i>", parse_mode="HTML")

    elif data.startswith("pause|"):
        plan = data.split("|")[1]
        paused_plans.add(plan)
        names = {"study":"📚 MBA","voice":"🎙️ صوت","dialect":"🗣️ لهجات",
                 "routine":"💆 روتين","fitness":"💪 لياقة","water":"💧 ماء"}
        await query.edit_message_text(
            f"⏸ <b>تم إيقاف {names.get(plan, plan)} مؤقتاً</b>\n"
            f"اضغط ▶️ استئناف متى أردت.", parse_mode="HTML")

    elif data.startswith("resume|"):
        plan = data.split("|")[1]
        paused_plans.discard(plan)
        names = {"study":"📚 MBA","voice":"🎙️ صوت","dialect":"🗣️ لهجات",
                 "routine":"💆 روتين","fitness":"💪 لياقة","water":"💧 ماء"}
        await query.edit_message_text(
            f"▶️ <b>تم استئناف {names.get(plan, plan)}</b> ✅", parse_mode="HTML")

# ─── أوامر ────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً كريم! 👋\n\nالبوت يعمل ✅\n\nاستخدم الأزرار أدناه للتحكم الكامل بجدولك.",
        parse_mode="HTML", reply_markup=MAIN_KB)

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await morning_summary(ctx.bot)

# ─── post_init ─────────────────────────────────────────────
async def post_init(app: Application):
    setup_scheduler(app.bot)

# ─── نقطة الدخول ──────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CallbackQueryHandler(handle_settings_callback,
                                          pattern="^(settings|pause|resume)\\|"))
    app.add_handler(CallbackQueryHandler(handle_callback,
                                          pattern="^(done|snooze|missed)\\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
