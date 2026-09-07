import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime

import edge_tts

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

DEFAULT_ARABIC_VOICE = "ar-EG-ShakirNeural"
DEFAULT_ENGLISH_VOICE = "en-US-GuyNeural"

# لا يوجد حد إجمالي للنص.
# هذا الرقم فقط لتقسيم النص داخليًا حتى تستطيع Edge TTS معالجته.
CHUNK_SIZE = 2500

# مجلد حفظ الملفات المنتجة
AUDIO_DIR = Path("audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("TelegramTTS")


# ============================================================
# USER DATA
# ============================================================

users = {}


def get_user(user_id):

    if user_id not in users:

        users[user_id] = {
            "text": "",
            "language": "auto",

            "voice": DEFAULT_ARABIC_VOICE,

            "voice_name":
                "شاكِر — مصري 🇪🇬",

            "rate": "+0%",
            "pitch": "+0Hz",
            "volume": "+0%",

            "busy": False,
        }

    return users[user_id]


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(text):

    arabic = len(
        re.findall(
            r"[\u0600-\u06FF]",
            text
        )
    )

    english = len(
        re.findall(
            r"[A-Za-z]",
            text
        )
    )

    if arabic >= english:
        return "ar"

    return "en"


def choose_auto_voice(text):

    language = detect_language(text)

    if language == "ar":

        return (
            DEFAULT_ARABIC_VOICE,
            "شاكِر — مصري 🇪🇬"
        )

    return (
        DEFAULT_ENGLISH_VOICE,
        "Guy — أمريكي 🇺🇸"
    )


# ============================================================
# SMART TEXT SPLITTER
# ============================================================

def split_text(text, max_chars=CHUNK_SIZE):

    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    chunks = []

    paragraphs = re.split(
        r"\n\s*\n",
        text
    )

    current = ""

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        # الفقرة نفسها صغيرة
        if len(paragraph) <= max_chars:

            if (
                current
                and
                len(current) + len(paragraph) + 2
                <= max_chars
            ):

                current += "\n\n" + paragraph

            else:

                if current:
                    chunks.append(current)

                current = paragraph

            continue

        # لو الفقرة كبيرة نقسمها إلى جمل
        sentences = re.split(
            r"(?<=[.!؟!?])\s+",
            paragraph
        )

        for sentence in sentences:

            sentence = sentence.strip()

            if not sentence:
                continue

            if len(sentence) > max_chars:

                # تقسيم إجباري للجملة الطويلة جدًا
                if current:
                    chunks.append(current)
                    current = ""

                for i in range(
                    0,
                    len(sentence),
                    max_chars
                ):

                    chunks.append(
                        sentence[i:i + max_chars]
                    )

                continue

            if (
                current
                and
                len(current) + len(sentence) + 1
                <= max_chars
            ):

                current += " " + sentence

            else:

                if current:
                    chunks.append(current)

                current = sentence

    if current:
        chunks.append(current)

    return chunks


# ============================================================
# PROGRESS BAR
# ============================================================

def progress_bar(current, total, width=12):

    if total <= 0:
        return "░" * width

    completed = int(
        width * current / total
    )

    completed = min(
        completed,
        width
    )

    return (
        "█" * completed
        +
        "░" * (width - completed)
    )


async def update_progress(
    message,
    current,
    total
):

    percent = int(
        (current / total) * 100
    ) if total else 0

    bar = progress_bar(
        current,
        total
    )

    try:

        await message.edit_text(

            "🎙️ *جاري إنشاء الصوت*\n\n"

            f"`{bar}` **{percent}%**\n\n"

            f"🔄 الجزء: **{current}/{total}**\n"
            f"📊 التقدم: **{percent}%**\n\n"

            "يرجى الانتظار...",

            parse_mode="Markdown"

        )

    except Exception:
        pass


# ============================================================
# MAIN MENU
# ============================================================

def main_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📝 النص",
                callback_data="text_menu"
            ),

            InlineKeyboardButton(
                "🎙️ الصوت",
                callback_data="voice_menu"
            ),
        ],

        [
            InlineKeyboardButton(
                "🌐 اللغة",
                callback_data="language_menu"
            ),

            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data="rate_menu"
            ),
        ],

        [
            InlineKeyboardButton(
                "🎚️ النبرة",
                callback_data="pitch_menu"
            ),

            InlineKeyboardButton(
                "🔊 مستوى الصوت",
                callback_data="volume_menu"
            ),
        ],

        [
            InlineKeyboardButton(
                "▶️ توليد الصوت",
                callback_data="generate"
            ),
        ],

        [
            InlineKeyboardButton(
                "⚙️ الإعدادات الحالية",
                callback_data="settings"
            ),
        ],

    ])


# ============================================================
# START BUTTON
# ============================================================

def start_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🚀 بدء البوت",
                callback_data="start_bot"
            )
        ]

    ])


# ============================================================
# START COMMAND
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🎙️ *Telegram TTS Pro*\n\n"

        "مرحبًا بك 👋\n\n"

        "هذا البوت يحوّل النص إلى صوت باستخدام "
        "تقنية Edge TTS.\n\n"

        "📌 *طريقة الاستخدام:*\n\n"

        "1️⃣ اضغط «🚀 بدء البوت».\n"
        "2️⃣ أرسل النص الذي تريد تحويله.\n"
        "3️⃣ اختر الصوت المناسب.\n"
        "4️⃣ اختر اللغة أو اتركها تلقائية.\n"
        "5️⃣ تحكم في السرعة والنبرة ومستوى الصوت.\n"
        "6️⃣ اضغط «▶️ توليد الصوت».\n"
        "7️⃣ انتظر حتى يكتمل شريط الإنجاز.\n"
        "8️⃣ سيصلك ملف MP3.\n\n"

        "🤖 *اللغة التلقائية:* "
        "يمكن للبوت اختيار صوت عربي أو إنجليزي "
        "بحسب النص.\n\n"

        "♾️ *النصوص الطويلة:* "
        "لا يوجد حد إجمالي لعدد الأحرف؛ "
        "يتم تقسيم النص داخليًا ومعالجته على أجزاء.\n\n"

        "📁 الملفات المنتجة يتم الاحتفاظ بها على السيرفر.",

        reply_markup=start_keyboard(),

        parse_mode="Markdown"

    )


# ============================================================
# START BOT
# ============================================================

async def open_bot_menu(query):

    await query.message.edit_text(

        "🚀 *تم تشغيل البوت*\n\n"

        "📝 أرسل النص الذي تريد تحويله إلى صوت.\n\n"

        "بعد إرسال النص ستظهر لك إعدادات "
        "الصوت والتحكم.\n\n"

        "ابدأ الآن 👇",

        reply_markup=main_keyboard(),

        parse_mode="Markdown"

    )


# ============================================================
# RECEIVE TEXT
# ============================================================

async def receive_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if not text:
        return

    user = get_user(
        update.effective_user.id
    )

    if user["busy"]:

        await update.message.reply_text(
            "⏳ هناك عملية تحويل جارية حاليًا.\n"
            "انتظر حتى تنتهي ثم أرسل نصًا جديدًا."
        )

        return

    user["text"] = text

    if user["language"] == "auto":

        voice, name = choose_auto_voice(
            text
        )

        user["voice"] = voice
        user["voice_name"] = name

    language = detect_language(text)

    language_name = (
        "العربية 🇪🇬"
        if language == "ar"
        else
        "English 🇺🇸"
    )

    await update.message.reply_text(

        "✅ *تم استلام النص*\n\n"

        f"📊 عدد الأحرف: **{len(text):,}**\n"
        f"🌐 اللغة المكتشفة: **{language_name}**\n"
        f"🎙️ الصوت: **{user['voice_name']}**\n\n"

        "يمكنك الآن تعديل الإعدادات أو "
        "الضغط على «▶️ توليد الصوت».",

        reply_markup=main_keyboard(),

        parse_mode="Markdown"

    )


# ============================================================
# VOICES
# ============================================================

ARABIC_VOICES = {

    "ar-EG-ShakirNeural":
        "شاكِر — مصري 🇪🇬",

    "ar-EG-SalmaNeural":
        "سلمى — مصرية 🇪🇬",

    "ar-SA-HamedNeural":
        "حامد — سعودي 🇸🇦",

    "ar-SA-ZariyahNeural":
        "زريّة — سعودية 🇸🇦",

    "ar-AE-HamdanNeural":
        "حمدان — إماراتي 🇦🇪",

    "ar-AE-FatimaNeural":
        "فاطمة — إماراتية 🇦🇪",

    "ar-IQ-BasselNeural":
        "باسل — عراقي 🇮🇶",

    "ar-IQ-RanaNeural":
        "رنا — عراقية 🇮🇶",

    "ar-JO-TaimNeural":
        "تيم — أردني 🇯🇴",

    "ar-JO-SanaNeural":
        "سناء — أردنية 🇯🇴",

    "ar-KW-FahedNeural":
        "فهد — كويتي 🇰🇼",

    "ar-KW-NouraNeural":
        "نورة — كويتية 🇰🇼",

    "ar-LB-RamiNeural":
        "رامي — لبناني 🇱🇧",

    "ar-LB-LaylaNeural":
        "ليلى — لبنانية 🇱🇧",

    "ar-MA-JamalNeural":
        "جمال — مغربي 🇲🇦",

    "ar-MA-MounaNeural":
        "منى — مغربية 🇲🇦",

    "ar-OM-AbdullahNeural":
        "عبدالله — عماني 🇴🇲",

    "ar-OM-AyshaNeural":
        "عائشة — عمانية 🇴🇲",

    "ar-QA-MoazNeural":
        "معاذ — قطري 🇶🇦",

    "ar-SY-LaithNeural":
        "ليث — سوري 🇸🇾",

    "ar-SY-AmanyNeural":
        "أماني — سورية 🇸🇾",

    "ar-TN-HediNeural":
        "هادي — تونسي 🇹🇳",

    "ar-TN-ReemNeural":
        "ريم — تونسية 🇹🇳",

}


ENGLISH_VOICES = {

    "en-US-GuyNeural":
        "Guy — أمريكي 🇺🇸",

    "en-US-AvaNeural":
        "Ava — أمريكية 🇺🇸",

    "en-US-AndrewNeural":
        "Andrew — أمريكي 🇺🇸",

    "en-US-EmmaNeural":
        "Emma — أمريكية 🇺🇸",

    "en-GB-RyanNeural":
        "Ryan — بريطاني 🇬🇧",

    "en-GB-SoniaNeural":
        "Sonia — بريطانية 🇬🇧",

    "en-AU-WilliamNeural":
        "William — أسترالي 🇦🇺",

    "en-AU-NatashaNeural":
        "Natasha — أسترالية 🇦🇺",

    "en-CA-LiamNeural":
        "Liam — كندي 🇨🇦",

    "en-CA-ClaraNeural":
        "Clara — كندية 🇨🇦",

}


def voice_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🇪🇬 الأصوات العربية",
                callback_data="arabic_voices"
            )
        ],

        [
            InlineKeyboardButton(
                "🇺🇸 English Voices",
                callback_data="english_voices"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back"
            )
        ],

    ])


def voice_list_keyboard(
    voices,
    language,
    page=0
):

    items = list(
        voices.items()
    )

    per_page = 6

    start = page * per_page

    end = start + per_page

    current = items[start:end]

    keyboard = []

    for voice, name in current:

        keyboard.append([

            InlineKeyboardButton(
                name,
                callback_data=f"selectvoice:{voice}"
            )

        ])

    navigation = []

    if page > 0:

        navigation.append(

            InlineKeyboardButton(
                "⬅️ السابق",
                callback_data=f"voicepage:{language}:{page - 1}"
            )

        )

    if end < len(items):

        navigation.append(

            InlineKeyboardButton(
                "التالي ➡️",
                callback_data=f"voicepage:{language}:{page + 1}"
            )

        )

    if navigation:
        keyboard.append(navigation)

    keyboard.append([

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="voice_menu"
        )

    ])

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# LANGUAGE
# ============================================================

def language_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🤖 تلقائي",
                callback_data="language:auto"
            )
        ],

        [
            InlineKeyboardButton(
                "🇪🇬 العربية",
                callback_data="language:ar"
            ),

            InlineKeyboardButton(
                "🇺🇸 English",
                callback_data="language:en"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back"
            )
        ]

    ])


# ============================================================
# RATE
# ============================================================

def rate_keyboard():

    values = [

        ("🐢 -50%", "-50%"),
        ("🐢 -25%", "-25%"),
        ("▶️ طبيعي", "+0%"),
        ("⚡ +25%", "+25%"),
        ("🚀 +50%", "+50%"),

    ]

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                label,
                callback_data=f"rate:{value}"
            )
        ]

        for label, value in values

    ] + [[

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back"
        )

    ]])


# ============================================================
# PITCH
# ============================================================

def pitch_keyboard():

    values = [

        ("⬇️ -10Hz", "-10Hz"),
        ("⬇️ -5Hz", "-5Hz"),
        ("🎵 طبيعي", "+0Hz"),
        ("⬆️ +5Hz", "+5Hz"),
        ("⬆️ +10Hz", "+10Hz"),

    ]

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                label,
                callback_data=f"pitch:{value}"
            )
        ]

        for label, value in values

    ] + [[

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back"
        )

    ]])


# ============================================================
# VOLUME
# ============================================================

def volume_keyboard():

    values = [

        ("🔉 -20%", "-20%"),
        ("🔉 -10%", "-10%"),
        ("🔊 طبيعي", "+0%"),
        ("🔊 +10%", "+10%"),
        ("🔊 +20%", "+20%"),

    ]

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                label,
                callback_data=f"volume:{value}"
            )
        ]

        for label, value in values

    ] + [[

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back"
        )

    ]])


# ============================================================
# GENERATE AUDIO
# ============================================================

async def generate_audio(query):

    user_id = query.from_user.id

    user = get_user(user_id)

    text = user["text"]

    if not text:

        await query.message.reply_text(
            "❌ لا يوجد نص.\n\n"
            "أرسل النص أولًا."
        )

        return

    if user["busy"]:

        await query.message.reply_text(
            "⏳ توجد عملية تحويل جارية بالفعل."
        )

        return

    user["busy"] = True

    chunks = split_text(text)

    total = len(chunks)

    progress_message = await query.message.reply_text(

        "🎙️ *بدء عملية التحويل...*\n\n"
        "`░░░░░░░░░░░░` **0%**\n\n"
        f"🔄 الجزء: **0/{total}**\n"
        f"📊 الأحرف: **{len(text):,}**",

        parse_mode="Markdown"

    )

    generated_files = []

    try:

        for index, chunk in enumerate(
            chunks,
            start=1
        ):

            timestamp = datetime.now().strftime(
                "%Y%m%d_%H%M%S_%f"
            )

            filename = (
                f"tts_{user_id}_"
                f"{timestamp}_"
                f"{index:04d}.mp3"
            )

            output_path = (
                AUDIO_DIR / filename
            )

            communicate = edge_tts.Communicate(

                chunk,

                voice=user["voice"],

                rate=user["rate"],

                pitch=user["pitch"],

                volume=user["volume"]

            )

            await communicate.save(
                str(output_path)
            )

            generated_files.append(
                output_path
            )

            await update_progress(
                progress_message,
                index,
                total
            )

        # إرسال الملفات بعد اكتمال التوليد
        for index, path in enumerate(
            generated_files,
            start=1
        ):

            with open(
                path,
                "rb"
            ) as audio:

                await query.message.reply_audio(

                    audio=audio,

                    title=(
                        "Telegram TTS"
                        if total == 1
                        else
                        f"Telegram TTS — الجزء {index}"
                    ),

                    performer="Edge TTS"

                )

        # رسالة النجاح النهائية
        await progress_message.edit_text(

            "✅ *اكتملت عملية التحويل بنجاح!*\n\n"

            f"📊 إجمالي الأحرف: **{len(text):,}**\n"
            f"📦 عدد الملفات: **{total}**\n"
            f"🎙️ الصوت: **{user['voice_name']}**\n"
            f"⚡ السرعة: **{user['rate']}**\n"
            f"🎚️ النبرة: **{user['pitch']}**\n\n"

            "📁 تم الاحتفاظ بالملفات على السيرفر.",

            parse_mode="Markdown"

        )

    except Exception as error:

        logger.exception(
            "TTS generation failed"
        )

        await progress_message.edit_text(

            "❌ *فشل إنشاء الصوت*\n\n"

            f"`{str(error)}`",

            parse_mode="Markdown"

        )

    finally:

        # مهم:
        # لا نحذف الملفات هنا.
        # الملفات تظل محفوظة داخل AUDIO_DIR.

        user["busy"] = False


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    data = query.data


    # ----------------------------
    # START BOT
    # ----------------------------

    if data == "start_bot":

        await open_bot_menu(query)

        return


    # ----------------------------
    # BACK
    # ----------------------------

    if data == "back":

        await query.message.edit_text(

            "🎙️ *Telegram TTS Pro*\n\n"
            "اختر العملية:",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ----------------------------
    # TEXT
    # ----------------------------

    if data == "text_menu":

        status = (

            f"✅ {len(user['text']):,} حرف"

            if user["text"]

            else

            "❌ لا يوجد نص"

        )

        await query.message.edit_text(

            "📝 *النص الحالي*\n\n"

            f"{status}\n\n"

            "أرسل نصًا جديدًا لاستبداله.",

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "🗑️ حذف النص",
                        callback_data="clear_text"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "⬅️ رجوع",
                        callback_data="back"
                    )
                ]

            ]),

            parse_mode="Markdown"

        )

        return


    if data == "clear_text":

        user["text"] = ""

        await query.message.edit_text(

            "🗑️ تم حذف النص.",

            reply_markup=main_keyboard()

        )

        return


    # ----------------------------
    # VOICE MENU
    # ----------------------------

    if data == "voice_menu":

        await query.message.edit_text(

            "🎙️ *اختيار الصوت*\n\n"
            "اختر مجموعة الأصوات:",

            reply_markup=voice_keyboard(),

            parse_mode="Markdown"

        )

        return


    if data == "arabic_voices":

        await query.message.edit_text(

            "🇪🇬 *الأصوات العربية*",

            reply_markup=voice_list_keyboard(
                ARABIC_VOICES,
                "ar",
                0
            ),

            parse_mode="Markdown"

        )

        return


    if data == "english_voices":

        await query.message.edit_text(

            "🇺🇸 *English Voices*",

            reply_markup=voice_list_keyboard(
                ENGLISH_VOICES,
                "en",
                0
            ),

            parse_mode="Markdown"

        )

        return


    # ----------------------------
    # VOICE PAGE
    # ----------------------------

    if data.startswith("voicepage:"):

        _, language, page = data.split(":")

        page = int(page)

        voices = (
            ARABIC_VOICES
            if language == "ar"
            else
            ENGLISH_VOICES
        )

        await query.message.edit_text(

            "🎙️ اختر الصوت:",

            reply_markup=voice_list_keyboard(
                voices,
                language,
                page
            )

        )

        return


    # ----------------------------
    # SELECT VOICE
    # ----------------------------

    if data.startswith("selectvoice:"):

        voice = data.split(
            ":",
            1
        )[1]

        name = (
            ARABIC_VOICES.get(voice)
            or
            ENGLISH_VOICES.get(voice)
        )

        if name:

            user["voice"] = voice
            user["voice_name"] = name

            await query.message.edit_text(

                "✅ *تم اختيار الصوت*\n\n"
                f"🎙️ {name}",

                reply_markup=main_keyboard(),

                parse_mode="Markdown"

            )

        return


    # ----------------------------
    # LANGUAGE
    # ----------------------------

    if data == "language_menu":

        await query.message.edit_text(

            "🌐 *اختيار اللغة*",

            reply_markup=language_keyboard(),

            parse_mode="Markdown"

        )

        return


    if data.startswith("language:"):

        language = data.split(
            ":",
            1
        )[1]

        user["language"] = language

        if language == "auto":

            if user["text"]:

                voice, name = choose_auto_voice(
                    user["text"]
                )

                user["voice"] = voice
                user["voice_name"] = name

            message = (
                "🤖 تم تفعيل الاختيار التلقائي."
            )

        elif language == "ar":

            message = "🇪🇬 تم اختيار العربية."

        else:

            message = "🇺🇸 English selected."

        await query.message.edit_text(

            message,

            reply_markup=main_keyboard()

        )

        return


    # ----------------------------
    # RATE
    # ----------------------------

    if data == "rate_menu":

        await query.message.edit_text(

            "⚡ *اختر سرعة النطق:*",

            reply_markup=rate_keyboard(),

            parse_mode="Markdown"

        )

        return


    if data.startswith("rate:"):

        user["rate"] = data.split(
            ":",
            1
        )[1]

        await query.message.edit_text(

            f"⚡ السرعة: {user['rate']}",

            reply_markup=main_keyboard()

        )

        return


    # ----------------------------
    # PITCH
    # ----------------------------

    if data == "pitch_menu":

        await query.message.edit_text(

            "🎚️ *اختر النبرة:*",

            reply_markup=pitch_keyboard(),

            parse_mode="Markdown"

        )

        return


    if data.startswith("pitch:"):

        user["pitch"] = data.split(
            ":",
            1
        )[1]

        await query.message.edit_text(

            f"🎚️ النبرة: {user['pitch']}",

            reply_markup=main_keyboard()

        )

        return


    # ----------------------------
    # VOLUME
    # ----------------------------

    if data == "volume_menu":

        await query.message.edit_text(

            "🔊 *اختر مستوى الصوت:*",

            reply_markup=volume_keyboard(),

            parse_mode="Markdown"

        )

        return


    if data.startswith("volume:"):

        user["volume"] = data.split(
            ":",
            1
        )[1]

        await query.message.edit_text(

            f"🔊 مستوى الصوت: {user['volume']}",

            reply_markup=main_keyboard()

        )

        return


    # ----------------------------
    # SETTINGS
    # ----------------------------

    if data == "settings":

        text_status = (

            f"{len(user['text']):,} حرف"

            if user["text"]

            else

            "لا يوجد"

        )

        await query.message.edit_text(

            "⚙️ *الإعدادات الحالية*\n\n"

            f"📝 النص: {text_status}\n"
            f"🎙️ الصوت: {user['voice_name']}\n"
            f"🌐 اللغة: {user['language']}\n"
            f"⚡ السرعة: {user['rate']}\n"
            f"🎚️ النبرة: {user['pitch']}\n"
            f"🔊 مستوى الصوت: {user['volume']}",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ----------------------------
    # GENERATE
    # ----------------------------

    if data == "generate":

        await generate_audio(query)

        return


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    logger.exception(
        "Unhandled exception",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN غير موجود في Faable Variables"
        )

    logger.info(
        "Starting Telegram TTS Pro..."
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_text
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Telegram TTS Pro is running."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
