import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path

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

MAX_CHARS_PER_CHUNK = 2500

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("TelegramTTS")


# ============================================================
# USER SETTINGS
# ============================================================

users = {}


def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "text": "",
            "language": "auto",
            "voice": DEFAULT_ARABIC_VOICE,
            "voice_name": "شاكِر — مصري 🇪🇬",
            "rate": "+0%",
            "pitch": "+0Hz",
            "volume": "+0%",
        }

    return users[user_id]


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(text):

    arabic = len(
        re.findall(r"[\u0600-\u06FF]", text)
    )

    english = len(
        re.findall(r"[A-Za-z]", text)
    )

    if arabic > english:
        return "ar"

    if english > arabic:
        return "en"

    return "ar"


# ============================================================
# SMART VOICE
# ============================================================

def choose_auto_voice(text):

    language = detect_language(text)

    if language == "ar":
        return DEFAULT_ARABIC_VOICE, "شاكِر — مصري 🇪🇬"

    return DEFAULT_ENGLISH_VOICE, "Guy — أمريكي 🇺🇸"


# ============================================================
# TEXT CHUNKING
# ============================================================

def split_text(text, max_chars=MAX_CHARS_PER_CHUNK):

    text = text.strip()

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

        if len(current) + len(paragraph) + 2 <= max_chars:

            current += (
                ("\n\n" if current else "")
                + paragraph
            )

        else:

            if current:
                chunks.append(current)

            if len(paragraph) <= max_chars:

                current = paragraph

            else:

                sentences = re.split(
                    r"(?<=[.!؟!?])\s+",
                    paragraph
                )

                current = ""

                for sentence in sentences:

                    if len(current) + len(sentence) + 1 <= max_chars:

                        current += (
                            (" " if current else "")
                            + sentence
                        )

                    else:

                        if current:
                            chunks.append(current)

                        current = sentence

    if current:
        chunks.append(current)

    return chunks


# ============================================================
# MAIN KEYBOARD
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
                "🔊 الصوت",
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
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = get_user(
        update.effective_user.id
    )

    await update.message.reply_text(

        "🎙️ *Telegram TTS Pro*\n\n"

        "حوّل النص إلى صوت باستخدام Edge TTS.\n\n"

        "📝 أرسل النص مباشرة للبوت، "
        "ثم استخدم الأزرار للتحكم في الصوت.\n\n"

        f"🎙️ الصوت الحالي: {user['voice_name']}\n"
        f"⚡ السرعة: {user['rate']}\n"
        f"🎚️ النبرة: {user['pitch']}\n\n"

        "ابدأ بإرسال النص 👇",

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

    user["text"] = text

    if user["language"] == "auto":

        voice, name = choose_auto_voice(text)

        user["voice"] = voice
        user["voice_name"] = name

    detected = detect_language(text)

    language_name = (
        "العربية 🇪🇬"
        if detected == "ar"
        else "English 🇺🇸"
    )

    await update.message.reply_text(

        "✅ *تم حفظ النص*\n\n"

        f"📊 الأحرف: {len(text)}\n"
        f"🌐 اللغة المكتشفة: {language_name}\n"
        f"🎙️ الصوت: {user['voice_name']}\n\n"

        "يمكنك الآن الضغط على ▶️ توليد الصوت.",

        reply_markup=main_keyboard(),

        parse_mode="Markdown"
    )


# ============================================================
# TEXT MENU
# ============================================================

def text_keyboard():

    return InlineKeyboardMarkup([

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
        ],

    ])


# ============================================================
# VOICE MENU
# ============================================================

def voice_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🇪🇬 أصوات عربية",
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


# ============================================================
# ARABIC VOICES
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

    "ar-QA-SayedNeural":
        "سيد — قطري 🇶🇦",

    "ar-SY-LaithNeural":
        "ليث — سوري 🇸🇾",

    "ar-SY-AmanyNeural":
        "أماني — سورية 🇸🇾",

    "ar-TN-HediNeural":
        "هادي — تونسي 🇹🇳",

    "ar-TN-ReemNeural":
        "ريم — تونسية 🇹🇳",

}


# ============================================================
# ENGLISH VOICES
# ============================================================

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


# ============================================================
# PAGINATED VOICES
# ============================================================

def voice_list_keyboard(
    voices,
    page=0
):

    items = list(voices.items())

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
                callback_data=f"voicepage:{'ar' if voices is ARABIC_VOICES else 'en'}:{page - 1}"
            )

        )

    if end < len(items):

        navigation.append(

            InlineKeyboardButton(
                "التالي ➡️",
                callback_data=f"voicepage:{'ar' if voices is ARABIC_VOICES else 'en'}:{page + 1}"
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
# LANGUAGE KEYBOARD
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

    rates = [
        ("🐢 -50%", "-50%"),
        ("🐢 -25%", "-25%"),
        ("▶️ طبيعي", "+0%"),
        ("⚡ +25%", "+25%"),
        ("🚀 +50%", "+50%"),
    ]

    keyboard = []

    for label, value in rates:

        keyboard.append([

            InlineKeyboardButton(
                label,
                callback_data=f"rate:{value}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back"
        )

    ])

    return InlineKeyboardMarkup(keyboard)


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

    keyboard = []

    for label, value in values:

        keyboard.append([

            InlineKeyboardButton(
                label,
                callback_data=f"pitch:{value}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back"
        )

    ])

    return InlineKeyboardMarkup(keyboard)


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

    keyboard = []

    for label, value in values:

        keyboard.append([

            InlineKeyboardButton(
                label,
                callback_data=f"volume:{value}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(
            "⬅️ رجوع",
            callback_data="back"
        )

    ])

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# GENERATE AUDIO
# ============================================================

async def generate_audio(
    query
):

    user_id = query.from_user.id

    user = get_user(user_id)

    text = user["text"]

    if not text:

        await query.message.reply_text(
            "❌ لا يوجد نص.\n\nأرسل النص أولًا."
        )

        return

    await query.message.reply_text(

        "⏳ *جاري إنشاء الصوت...*\n\n"

        f"🎙️ {user['voice_name']}\n"
        f"⚡ السرعة: {user['rate']}\n"
        f"🎚️ النبرة: {user['pitch']}\n"
        f"🔊 الصوت: {user['volume']}\n\n"

        "يرجى الانتظار...",

        parse_mode="Markdown"
    )

    chunks = split_text(text)

    output_files = []

    try:

        for index, chunk in enumerate(chunks):

            await query.message.reply_text(

                f"🔄 معالجة الجزء "
                f"{index + 1}/{len(chunks)}..."

            )

            temp = tempfile.NamedTemporaryFile(
                suffix=".mp3",
                delete=False
            )

            temp.close()

            output_file = temp.name

            communicate = edge_tts.Communicate(

                chunk,

                voice=user["voice"],

                rate=user["rate"],

                pitch=user["pitch"],

                volume=user["volume"]

            )

            await communicate.save(
                output_file
            )

            output_files.append(output_file)

        # حالة النص القصير
        if len(output_files) == 1:

            with open(
                output_files[0],
                "rb"
            ) as audio:

                await query.message.reply_audio(

                    audio=audio,

                    title="Telegram TTS",

                    performer="Edge TTS"

                )

        else:

            # إرسال كل جزء للحفاظ على ترتيب النص
            for index, path in enumerate(output_files):

                with open(
                    path,
                    "rb"
                ) as audio:

                    await query.message.reply_audio(

                        audio=audio,

                        title=f"Telegram TTS - Part {index + 1}",

                        performer="Edge TTS"

                    )

        await query.message.reply_text(

            "✅ *تم إنشاء الصوت بنجاح!*",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

    except Exception as e:

        logger.exception(
            "TTS generation failed"
        )

        await query.message.reply_text(

            "❌ حدث خطأ أثناء إنشاء الصوت.\n\n"

            f"`{str(e)}`",

            parse_mode="Markdown"

        )

    finally:

        for path in output_files:

            try:

                os.remove(path)

            except OSError:

                pass


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    user = get_user(user_id)

    data = query.data


    # ------------------------------
    # MAIN
    # ------------------------------

    if data == "back":

        await query.message.edit_text(

            "🎙️ *Telegram TTS Pro*\n\n"
            "اختر العملية:",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ------------------------------
    # TEXT
    # ------------------------------

    if data == "text_menu":

        status = (
            f"✅ {len(user['text'])} حرف"
            if user["text"]
            else
            "❌ لا يوجد نص"
        )

        await query.message.edit_text(

            f"📝 *النص الحالي*\n\n{status}\n\n"
            "أرسل نصًا جديدًا لاستبداله.",

            reply_markup=text_keyboard(),

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


    # ------------------------------
    # VOICE
    # ------------------------------

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
                0
            ),

            parse_mode="Markdown"

        )

        return


    # ------------------------------
    # VOICE PAGE
    # ------------------------------

    if data.startswith("voicepage:"):

        _, language, page = data.split(":")

        page = int(page)

        voices = (
            ARABIC_VOICES
            if language == "ar"
            else ENGLISH_VOICES
        )

        await query.message.edit_text(

            "🎙️ اختر الصوت:",

            reply_markup=voice_list_keyboard(
                voices,
                page
            )

        )

        return


    # ------------------------------
    # SELECT VOICE
    # ------------------------------

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


    # ------------------------------
    # LANGUAGE
    # ------------------------------

    if data == "language_menu":

        await query.message.edit_text(

            "🌐 *طريقة اختيار اللغة*",

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


    # ------------------------------
    # RATE
    # ------------------------------

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


    # ------------------------------
    # PITCH
    # ------------------------------

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


    # ------------------------------
    # VOLUME
    # ------------------------------

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


    # ------------------------------
    # SETTINGS
    # ------------------------------

    if data == "settings":

        text_status = (
            f"{len(user['text'])} حرف"
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
            f"🔊 الصوت: {user['volume']}",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ------------------------------
    # GENERATE
    # ------------------------------

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
            filters.TEXT
            & ~filters.COMMAND,
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
