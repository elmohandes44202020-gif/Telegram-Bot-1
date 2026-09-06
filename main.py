import os
import re
import asyncio
import tempfile
import logging

import edge_tts

from dotenv import load_dotenv
from langdetect import detect

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


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# =========================================================
# VOICES
# =========================================================

ARABIC_VOICES = {

    "EG_MALE": {
        "name": "محمد - مصري 🇪🇬",
        "voice": "ar-EG-ShakirNeural"
    },

    "EG_FEMALE": {
        "name": "سلمى - مصرية 🇪🇬",
        "voice": "ar-EG-SalmaNeural"
    },

    "SA_MALE": {
        "name": "هامد - سعودي 🇸🇦",
        "voice": "ar-SA-HamedNeural"
    },

    "SA_FEMALE": {
        "name": "زاري - سعودية 🇸🇦",
        "voice": "ar-SA-ZariyahNeural"
    },

    "AE_MALE": {
        "name": "حمدان - إماراتي 🇦🇪",
        "voice": "ar-AE-HamdanNeural"
    },

    "AE_FEMALE": {
        "name": "فاطمة - إماراتية 🇦🇪",
        "voice": "ar-AE-FatimaNeural"
    },

    "IQ_MALE": {
        "name": "بسام - عراقي 🇮🇶",
        "voice": "ar-IQ-BasselNeural"
    },

    "IQ_FEMALE": {
        "name": "رنا - عراقية 🇮🇶",
        "voice": "ar-IQ-RanaNeural"
    },

    "JO_MALE": {
        "name": "تيسير - أردني 🇯🇴",
        "voice": "ar-JO-TaimNeural"
    },

    "JO_FEMALE": {
        "name": "سناء - أردنية 🇯🇴",
        "voice": "ar-JO-SanaNeural"
    },

    "KW_MALE": {
        "name": "فهد - كويتي 🇰🇼",
        "voice": "ar-KW-FahedNeural"
    },

    "KW_FEMALE": {
        "name": "نورة - كويتية 🇰🇼",
        "voice": "ar-KW-NouraNeural"
    },

    "LB_MALE": {
        "name": "رود - لبناني 🇱🇧",
        "voice": "ar-LB-RodaNeural"
    },

    "LB_FEMALE": {
        "name": "ليلى - لبنانية 🇱🇧",
        "voice": "ar-LB-LaylaNeural"
    },

    "LY_MALE": {
        "name": "عمر - ليبي 🇱🇾",
        "voice": "ar-LY-OmarNeural"
    },

    "LY_FEMALE": {
        "name": "إيمان - ليبية 🇱🇾",
        "voice": "ar-LY-ImanNeural"
    },

    "MA_MALE": {
        "name": "جواد - مغربي 🇲🇦",
        "voice": "ar-MA-JamalNeural"
    },

    "MA_FEMALE": {
        "name": "منى - مغربية 🇲🇦",
        "voice": "ar-MA-MounaNeural"
    },

    "OM_MALE": {
        "name": "عبدالله - عماني 🇴🇲",
        "voice": "ar-OM-AbdullahNeural"
    },

    "OM_FEMALE": {
        "name": "أمينة - عمانية 🇴🇲",
        "voice": "ar-OM-AminaNeural"
    },

    "QA_MALE": {
        "name": "مؤيد - قطري 🇶🇦",
        "voice": "ar-QA-MoazNeural"
    },

    "QA_FEMALE": {
        "name": "أمل - قطرية 🇶🇦",
        "voice": "ar-QA-AmalNeural"
    },

    "SY_MALE": {
        "name": "باسل - سوري 🇸🇾",
        "voice": "ar-SY-LaithNeural"
    },

    "SY_FEMALE": {
        "name": "أمينة - سورية 🇸🇾",
        "voice": "ar-SY-AmanyNeural"
    },

    "TN_MALE": {
        "name": "حاتم - تونسي 🇹🇳",
        "voice": "ar-TN-HediNeural"
    },

    "TN_FEMALE": {
        "name": "ريم - تونسية 🇹🇳",
        "voice": "ar-TN-ReemNeural"
    },

    "YE_MALE": {
        "name": "صالح - يمني 🇾🇪",
        "voice": "ar-YE-SalehNeural"
    },

    "YE_FEMALE": {
        "name": "مريم - يمنية 🇾🇪",
        "voice": "ar-YE-MaryamNeural"
    }

}


ENGLISH_VOICES = {

    "US_MALE": {
        "name": "Guy - أمريكي 🇺🇸",
        "voice": "en-US-GuyNeural"
    },

    "US_FEMALE": {
        "name": "Ava - أمريكية 🇺🇸",
        "voice": "en-US-AvaNeural"
    },

    "US_MALE_2": {
        "name": "Andrew - أمريكي 🇺🇸",
        "voice": "en-US-AndrewNeural"
    },

    "US_FEMALE_2": {
        "name": "Emma - أمريكية 🇺🇸",
        "voice": "en-US-EmmaNeural"
    },

    "UK_MALE": {
        "name": "Ryan - بريطاني 🇬🇧",
        "voice": "en-GB-RyanNeural"
    },

    "UK_FEMALE": {
        "name": "Sonia - بريطانية 🇬🇧",
        "voice": "en-GB-SoniaNeural"
    },

    "AU_MALE": {
        "name": "William - أسترالي 🇦🇺",
        "voice": "en-AU-WilliamNeural"
    },

    "AU_FEMALE": {
        "name": "Natasha - أسترالية 🇦🇺",
        "voice": "en-AU-NatashaNeural"
    },

    "CA_MALE": {
        "name": "Liam - كندي 🇨🇦",
        "voice": "en-CA-LiamNeural"
    },

    "CA_FEMALE": {
        "name": "Clara - كندية 🇨🇦",
        "voice": "en-CA-ClaraNeural"
    }

}


# =========================================================
# USER SETTINGS
# =========================================================

USER_DATA = {}


def get_user_settings(user_id):

    if user_id not in USER_DATA:

        USER_DATA[user_id] = {

            "text": "",

            "language": "auto",

            "voice": "ar-EG-ShakirNeural",

            "voice_name": "محمد - مصري 🇪🇬",

            "rate": "+0%",

            "pitch": "+0Hz"

        }

    return USER_DATA[user_id]


# =========================================================
# DETECT LANGUAGE
# =========================================================

def detect_text_language(text):

    arabic_letters = len(
        re.findall(
            r"[\u0600-\u06FF]",
            text
        )
    )

    english_letters = len(
        re.findall(
            r"[A-Za-z]",
            text
        )
    )

    if arabic_letters > english_letters:
        return "arabic"

    if english_letters > arabic_letters:
        return "english"

    return "arabic"


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "📝 إدخال النص",
                callback_data="input_text"
            )
        ],

        [
            InlineKeyboardButton(
                "🎙️ اختيار الصوت",
                callback_data="voice_menu"
            )
        ],

        [
            InlineKeyboardButton(
                "🌐 اللغة: تلقائي",
                callback_data="language_menu"
            )
        ],

        [
            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data="rate_menu"
            ),

            InlineKeyboardButton(
                "🎚️ النبرة",
                callback_data="pitch_menu"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ تحويل إلى صوت",
                callback_data="generate"
            )
        ],

        [
            InlineKeyboardButton(
                "⚙️ الإعدادات",
                callback_data="settings"
            )
        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    get_user_settings(user_id)

    await update.message.reply_text(

        "🎙️ *مرحبًا بك في بوت تحويل النص إلى صوت*\n\n"

        "يمكنك:\n\n"

        "📝 إدخال النص\n"
        "🎙️ اختيار الصوت\n"
        "🌐 التبديل بين العربية والإنجليزية\n"
        "🤖 اكتشاف اللغة تلقائيًا\n"
        "⚡ التحكم في سرعة الصوت\n"
        "🎚️ التحكم في النبرة\n"
        "▶️ إنشاء ملف MP3\n\n"

        "اختر من القائمة:",

        reply_markup=main_menu(),

        parse_mode="Markdown"

    )


# =========================================================
# INPUT TEXT
# =========================================================

async def ask_for_text(query):

    await query.message.reply_text(

        "📝 أرسل النص الذي تريد تحويله إلى صوت.\n\n"

        "يمكنك إرسال نص عربي أو English."

    )


# =========================================================
# RECEIVE TEXT
# =========================================================

async def receive_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    settings = get_user_settings(user_id)

    text = update.message.text

    settings["text"] = text


    language = detect_text_language(text)


    if settings["language"] == "auto":

        if language == "arabic":

            settings["voice"] = "ar-EG-ShakirNeural"

            settings["voice_name"] = "محمد - مصري 🇪🇬"

        else:

            settings["voice"] = "en-US-GuyNeural"

            settings["voice_name"] = "Guy - أمريكي 🇺🇸"


    await update.message.reply_text(

        f"✅ تم حفظ النص بنجاح.\n\n"

        f"📊 عدد الأحرف: {len(text)}\n"

        f"🌐 اللغة المكتشفة: "
        f"{'العربية 🇸🇦' if language == 'arabic' else 'English 🇺🇸'}\n\n"

        f"🎙️ الصوت الحالي:\n"
        f"{settings['voice_name']}",

        reply_markup=main_menu()

    )


# =========================================================
# VOICE MENU
# =========================================================

def voice_language_menu():

    keyboard = [

        [

            InlineKeyboardButton(
                "🇦🇪 العربية",
                callback_data="arabic_voices"
            ),

            InlineKeyboardButton(
                "🇺🇸 English",
                callback_data="english_voices"
            )

        ],

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )

        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# ARABIC VOICES
# =========================================================

def arabic_voices_menu():

    keyboard = []


    for key, voice_data in ARABIC_VOICES.items():

        keyboard.append(

            [

                InlineKeyboardButton(

                    voice_data["name"],

                    callback_data=f"voice_{key}"

                )

            ]

        )


    keyboard.append(

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="voice_menu"
            )

        ]

    )


    return InlineKeyboardMarkup(keyboard)


# =========================================================
# ENGLISH VOICES
# =========================================================

def english_voices_menu():

    keyboard = []


    for key, voice_data in ENGLISH_VOICES.items():

        keyboard.append(

            [

                InlineKeyboardButton(

                    voice_data["name"],

                    callback_data=f"voice_{key}"

                )

            ]

        )


    keyboard.append(

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="voice_menu"
            )

        ]

    )


    return InlineKeyboardMarkup(keyboard)


# =========================================================
# LANGUAGE MENU
# =========================================================

def language_menu():

    keyboard = [

        [

            InlineKeyboardButton(
                "🤖 تلقائي",
                callback_data="language_auto"
            )

        ],

        [

            InlineKeyboardButton(
                "🇦🇪 العربية",
                callback_data="language_arabic"
            ),

            InlineKeyboardButton(
                "🇺🇸 English",
                callback_data="language_english"
            )

        ],

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )

        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# RATE MENU
# =========================================================

def rate_menu():

    keyboard = [

        [

            InlineKeyboardButton(
                "🐢 -50%",
                callback_data="rate_-50%"
            ),

            InlineKeyboardButton(
                "🐢 -25%",
                callback_data="rate_-25%"
            )

        ],

        [

            InlineKeyboardButton(
                "⚡ طبيعي",
                callback_data="rate_+0%"
            )

        ],

        [

            InlineKeyboardButton(
                "🚀 +25%",
                callback_data="rate_+25%"
            ),

            InlineKeyboardButton(
                "🚀 +50%",
                callback_data="rate_+50%"
            )

        ],

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )

        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# PITCH MENU
# =========================================================

def pitch_menu():

    keyboard = [

        [

            InlineKeyboardButton(
                "⬇️ -10Hz",
                callback_data="pitch_-10Hz"
            ),

            InlineKeyboardButton(
                "⬇️ -5Hz",
                callback_data="pitch_-5Hz"
            )

        ],

        [

            InlineKeyboardButton(
                "🎵 طبيعي",
                callback_data="pitch_+0Hz"
            )

        ],

        [

            InlineKeyboardButton(
                "⬆️ +5Hz",
                callback_data="pitch_+5Hz"
            ),

            InlineKeyboardButton(
                "⬆️ +10Hz",
                callback_data="pitch_+10Hz"
            )

        ],

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main"
            )

        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# GENERATE AUDIO
# =========================================================

async def generate_audio(query):

    user_id = query.from_user.id

    settings = get_user_settings(user_id)

    text = settings["text"]


    if not text:

        await query.message.reply_text(

            "❌ لم تقم بإدخال أي نص.\n\n"

            "اضغط 📝 إدخال النص أولًا."

        )

        return


    await query.message.reply_text(

        "⏳ جاري إنشاء الصوت...\n\n"

        f"🎙️ الصوت: {settings['voice_name']}\n"

        f"⚡ السرعة: {settings['rate']}\n"

        f"🎚️ النبرة: {settings['pitch']}"

    )


    try:

        with tempfile.NamedTemporaryFile(

            delete=False,

            suffix=".mp3"

        ) as temp_file:

            output_file = temp_file.name


        communicate = edge_tts.Communicate(

            text=text,

            voice=settings["voice"],

            rate=settings["rate"],

            pitch=settings["pitch"]

        )


        await communicate.save(output_file)


        with open(

            output_file,

            "rb"

        ) as audio:

            await query.message.reply_audio(

                audio=audio,

                title="Text To Speech",

                performer="Edge TTS"

            )


        os.remove(output_file)


        await query.message.reply_text(

            "✅ تم إنشاء الصوت بنجاح!",

            reply_markup=main_menu()

        )


    except Exception as error:

        logger.error(error)


        await query.message.reply_text(

            f"❌ حدث خطأ أثناء إنشاء الصوت.\n\n"

            f"التفاصيل:\n{str(error)}"

        )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def button_handler(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    query = update.callback_query

    await query.answer()


    user_id = query.from_user.id

    settings = get_user_settings(user_id)

    data = query.data


    # ================================
    # INPUT TEXT
    # ================================

    if data == "input_text":

        await ask_for_text(query)

        return


    # ================================
    # MAIN MENU
    # ================================

    if data == "back_main":

        await query.message.edit_text(

            "🎙️ القائمة الرئيسية",

            reply_markup=main_menu()

        )

        return


    # ================================
    # VOICE MENU
    # ================================

    if data == "voice_menu":

        await query.message.edit_text(

            "🎙️ اختر اللغة:",

            reply_markup=voice_language_menu()

        )

        return


    # ================================
    # ARABIC VOICES
    # ================================

    if data == "arabic_voices":

        await query.message.edit_text(

            "🇦🇪 اختر الصوت العربي:",

            reply_markup=arabic_voices_menu()

        )

        return


    # ================================
    # ENGLISH VOICES
    # ================================

    if data == "english_voices":

        await query.message.edit_text(

            "🇺🇸 اختر الصوت الإنجليزي:",

            reply_markup=english_voices_menu()

        )

        return


    # ================================
    # SELECT VOICE
    # ================================

    if data.startswith("voice_"):

        voice_key = data.replace(

            "voice_",

            ""

        )


        voice_data = None


        if voice_key in ARABIC_VOICES:

            voice_data = ARABIC_VOICES[voice_key]


        elif voice_key in ENGLISH_VOICES:

            voice_data = ENGLISH_VOICES[voice_key]


        if voice_data:

            settings["voice"] = voice_data["voice"]

            settings["voice_name"] = voice_data["name"]


            await query.message.edit_text(

                f"✅ تم اختيار الصوت:\n\n"

                f"🎙️ {voice_data['name']}",

                reply_markup=main_menu()

            )

        return


    # ================================
    # LANGUAGE MENU
    # ================================

    if data == "language_menu":

        await query.message.edit_text(

            "🌐 اختر اللغة:",

            reply_markup=language_menu()

        )

        return


    # ================================
    # AUTO LANGUAGE
    # ================================

    if data == "language_auto":

        settings["language"] = "auto"


        await query.message.edit_text(

            "🤖 تم تفعيل اكتشاف اللغة تلقائيًا.",

            reply_markup=main_menu()

        )

        return


    # ================================
    # ARABIC LANGUAGE
    # ================================

    if data == "language_arabic":

        settings["language"] = "arabic"


        await query.message.edit_text(

            "🇦🇪 تم اختيار العربية.",

            reply_markup=main_menu()

        )

        return


    # ================================
    # ENGLISH LANGUAGE
    # ================================

    if data == "language_english":

        settings["language"] = "english"


        await query.message.edit_text(

            "🇺🇸 English selected.",

            reply_markup=main_menu()

        )

        return


    # ================================
    # RATE MENU
    # ================================

    if data == "rate_menu":

        await query.message.edit_text(

            "⚡ اختر سرعة الصوت:",

            reply_markup=rate_menu()

        )

        return


    # ================================
    # RATE
    # ================================

    if data.startswith("rate_"):

        rate = data.replace(

            "rate_",

            ""

        )


        settings["rate"] = rate


        await query.message.edit_text(

            f"⚡ تم اختيار السرعة:\n\n{rate}",

            reply_markup=main_menu()

        )

        return


    # ================================
    # PITCH MENU
    # ================================

    if data == "pitch_menu":

        await query.message.edit_text(

            "🎚️ اختر نبرة الصوت:",

            reply_markup=pitch_menu()

        )

        return


    # ================================
    # PITCH
    # ================================

    if data.startswith("pitch_"):

        pitch = data.replace(

            "pitch_",

            ""

        )


        settings["pitch"] = pitch


        await query.message.edit_text(

            f"🎚️ تم اختيار النبرة:\n\n{pitch}",

            reply_markup=main_menu()

        )

        return


    # ================================
    # GENERATE
    # ================================

    if data == "generate":

        await generate_audio(query)

        return


    # ================================
    # SETTINGS
    # ================================

    if data == "settings":

        text_status = (

            "✅ موجود"

            if settings["text"]

            else

            "❌ لا يوجد"

        )


        await query.message.edit_text(

            "⚙️ *الإعدادات الحالية*\n\n"

            f"📝 النص: {text_status}\n"

            f"🎙️ الصوت: {settings['voice_name']}\n"

            f"🌐 اللغة: {settings['language']}\n"

            f"⚡ السرعة: {settings['rate']}\n"

            f"🎚️ النبرة: {settings['pitch']}",

            reply_markup=main_menu(),

            parse_mode="Markdown"

        )

        return


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(

    update: Update,

    context: ContextTypes.DEFAULT_TYPE

):

    logger.error(

        "Exception while handling update:",

        exc_info=context.error

    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise ValueError(

            "BOT_TOKEN غير موجود في ملف .env"

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

            button_handler

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


    print(

        "🤖 Telegram TTS Bot Started..."

    )


    application.run_polling(

        allowed_updates=Update.ALL_TYPES

    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
