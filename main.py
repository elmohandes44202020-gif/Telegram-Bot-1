import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime

import edge_tts
import av
from av.audio.resampler import AudioResampler

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

CHUNK_SIZE = 2500

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
# VOICES
# ============================================================

ARABIC_VOICES = {

    "ar-EG-ShakirNeural": "شاكِر — مصري 🇪🇬",
    "ar-EG-SalmaNeural": "سلمى — مصرية 🇪🇬",

    "ar-SA-HamedNeural": "حامد — سعودي 🇸🇦",
    "ar-SA-ZariyahNeural": "زريّة — سعودية 🇸🇦",

    "ar-AE-HamdanNeural": "حمدان — إماراتي 🇦🇪",
    "ar-AE-FatimaNeural": "فاطمة — إماراتية 🇦🇪",

    "ar-IQ-BasselNeural": "باسل — عراقي 🇮🇶",
    "ar-IQ-RanaNeural": "رنا — عراقية 🇮🇶",

    "ar-JO-TaimNeural": "تيم — أردني 🇯🇴",
    "ar-JO-SanaNeural": "سناء — أردنية 🇯🇴",

    "ar-KW-FahedNeural": "فهد — كويتي 🇰🇼",
    "ar-KW-NouraNeural": "نورة — كويتية 🇰🇼",

    "ar-LB-RamiNeural": "رامي — لبناني 🇱🇧",
    "ar-LB-LaylaNeural": "ليلى — لبنانية 🇱🇧",

    "ar-MA-JamalNeural": "جمال — مغربي 🇲🇦",
    "ar-MA-MounaNeural": "منى — مغربية 🇲🇦",

    "ar-OM-AbdullahNeural": "عبدالله — عماني 🇴🇲",
    "ar-OM-AyshaNeural": "عائشة — عمانية 🇴🇲",

    "ar-QA-MoazNeural": "معاذ — قطري 🇶🇦",

    "ar-SY-LaithNeural": "ليث — سوري 🇸🇾",
    "ar-SY-AmanyNeural": "أماني — سورية 🇸🇾",

    "ar-TN-HediNeural": "هادي — تونسي 🇹🇳",
    "ar-TN-ReemNeural": "ريم — تونسية 🇹🇳",
}


ENGLISH_VOICES = {

    "en-US-GuyNeural": "Guy — أمريكي 🇺🇸",
    "en-US-AvaNeural": "Ava — أمريكية 🇺🇸",
    "en-US-AndrewNeural": "Andrew — أمريكي 🇺🇸",
    "en-US-EmmaNeural": "Emma — أمريكية 🇺🇸",

    "en-GB-RyanNeural": "Ryan — بريطاني 🇬🇧",
    "en-GB-SoniaNeural": "Sonia — بريطانية 🇬🇧",

    "en-AU-WilliamNeural": "William — أسترالي 🇦🇺",
    "en-AU-NatashaNeural": "Natasha — أسترالية 🇦🇺",

    "en-CA-LiamNeural": "Liam — كندي 🇨🇦",
    "en-CA-ClaraNeural": "Clara — كندية 🇨🇦",
}


# ============================================================
# USER DATA
# ============================================================

users = {}


def default_speaker(voice, voice_name):

    return {

        "voice": voice,
        "voice_name": voice_name,

        "rate": "+0%",
        "pitch": "+0Hz",
        "volume": "+0%",
    }


def get_user(user_id):

    if user_id not in users:

        users[user_id] = {

            "mode": "normal",

            "text": "",

            "language": "auto",

            "voice": DEFAULT_ARABIC_VOICE,

            "voice_name": "شاكِر — مصري 🇪🇬",

            "rate": "+0%",
            "pitch": "+0Hz",
            "volume": "+0%",

            "podcast_text": "",

            "speaker1": default_speaker(
                "ar-EG-ShakirNeural",
                "شاكِر — مصري 🇪🇬"
            ),

            "speaker2": default_speaker(
                "ar-EG-SalmaNeural",
                "سلمى — مصرية 🇪🇬"
            ),

            "editing_speaker": 1,

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

        if len(paragraph) <= max_chars:

            if (
                current
                and len(current) + len(paragraph) + 2 <= max_chars
            ):

                current += "\n\n" + paragraph

            else:

                if current:
                    chunks.append(current)

                current = paragraph

            continue

        sentences = re.split(
            r"(?<=[.!؟!?])\s+",
            paragraph
        )

        for sentence in sentences:

            sentence = sentence.strip()

            if not sentence:
                continue

            if len(sentence) > max_chars:

                if current:

                    chunks.append(current)
                    current = ""

                for i in range(
                    0,
                    len(sentence),
                    max_chars
                ):

                    chunks.append(
                        sentence[
                            i:i + max_chars
                        ]
                    )

                continue

            if (
                current
                and len(current) + len(sentence) + 1 <= max_chars
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
    total,
    title="🎙️ جاري إنشاء الصوت"
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

            f"{title}\n\n"

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
                "↕️ النبرة",
                callback_data="pitch_menu"
            ),

            InlineKeyboardButton(
                "🔊 مستوى الصوت",
                callback_data="volume_menu"
            ),

        ],

        [

            InlineKeyboardButton(
                "🎧 البودكاست",
                callback_data="podcast_menu"
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
# START KEYBOARD
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
# PODCAST KEYBOARD
# ============================================================

def podcast_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🎤 المتحدث الأول",
                callback_data="speaker1_menu"
            )

        ],

        [

            InlineKeyboardButton(
                "🎤 المتحدث الثاني",
                callback_data="speaker2_menu"
            )

        ],

        [

            InlineKeyboardButton(
                "⚙️ إعدادات البودكاست",
                callback_data="podcast_settings"
            )

        ],

        [

            InlineKeyboardButton(
                "▶️ إنشاء البودكاست",
                callback_data="generate_podcast"
            )

        ],

        [

            InlineKeyboardButton(
                "📝 تغيير الحوار",
                callback_data="podcast_text"
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
# SPEAKER MENU
# ============================================================

def speaker_menu_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🎤 الصوت",
                callback_data="podcast_voice_menu"
            )

        ],

        [

            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data="podcast_rate_menu"
            )

        ],

        [

            InlineKeyboardButton(
                "↕️ النبرة",
                callback_data="podcast_pitch_menu"
            )

        ],

        [

            InlineKeyboardButton(
                "🔊 مستوى الصوت",
                callback_data="podcast_volume_menu"
            )

        ],

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="podcast_menu"
            )

        ],

    ])


# ============================================================
# VOICE MENUS
# ============================================================

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


def podcast_voice_keyboard():

    return InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "🇪🇬 الأصوات العربية",
                callback_data="podcast_arabic_voices"
            )

        ],

        [

            InlineKeyboardButton(
                "🇺🇸 English Voices",
                callback_data="podcast_english_voices"
            )

        ],

        [

            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="podcast_speaker_menu"
            )

        ],

    ])


def voice_list_keyboard(
    voices,
    language,
    page=0,
    prefix="selectvoice"
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
                callback_data=f"{prefix}:{voice}"
            )

        ])

    navigation = []

    if page > 0:

        navigation.append(

            InlineKeyboardButton(
                "⬅️ السابق",
                callback_data=(
                    f"voicepage:{prefix}:{language}:{page - 1}"
                )
            )

        )

    if end < len(items):

        navigation.append(

            InlineKeyboardButton(
                "التالي ➡️",
                callback_data=(
                    f"voicepage:{prefix}:{language}:{page + 1}"
                )
            )

        )

    if navigation:
        keyboard.append(navigation)

    keyboard.append([

        InlineKeyboardButton(

            "⬅️ رجوع",

            callback_data=(
                "voice_menu"
                if prefix == "selectvoice"
                else "podcast_speaker_menu"
            )

        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


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
            ),

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

def rate_keyboard(prefix="rate"):

    values = [

        ("🐢 -50%", "-50%"),
        ("🐢 -25%", "-25%"),
        ("▶️ طبيعي", "+0%"),
        ("⚡ +25%", "+25%"),
        ("🚀 +50%", "+50%"),

    ]

    keyboard = []

    for label, value in values:

        keyboard.append([

            InlineKeyboardButton(
                label,
                callback_data=f"{prefix}:{value}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(

            "⬅️ رجوع",

            callback_data=(
                "back"
                if prefix == "rate"
                else "podcast_speaker_menu"
            )

        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# PITCH
# ============================================================

def pitch_keyboard(prefix="pitch"):

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
                callback_data=f"{prefix}:{value}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(

            "⬅️ رجوع",

            callback_data=(
                "back"
                if prefix == "pitch"
                else "podcast_speaker_menu"
            )

        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# VOLUME
# ============================================================

def volume_keyboard(prefix="volume"):

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
                callback_data=f"{prefix}:{value}"
            )

        ])

    keyboard.append([

        InlineKeyboardButton(

            "⬅️ رجوع",

            callback_data=(
                "back"
                if prefix == "volume"
                else "podcast_speaker_menu"
            )

        )

    ])

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# START
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

        "🎧 يدعم النصوص الطويلة والبودكاست "
        "بين متحدثين.",

        reply_markup=start_keyboard(),

        parse_mode="Markdown"

    )


# ============================================================
# OPEN BOT
# ============================================================

async def open_bot_menu(query):

    user = get_user(
        query.from_user.id
    )

    user["mode"] = "normal"

    await query.message.edit_text(

        "🚀 *تم تشغيل البوت*\n\n"

        "📝 أرسل النص الذي تريد تحويله إلى صوت.\n\n"

        "أو اختر 🎧 *البودكاست* لإنشاء حوار "
        "بين متحدثين.\n\n"

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
            "انتظر حتى تنتهي."

        )

        return


    # --------------------------------------------------------
    # PODCAST
    # --------------------------------------------------------

    if user["mode"] == "podcast":

        user["podcast_text"] = text

        lines = [

            line.strip()

            for line in text.splitlines()

            if line.strip()

        ]

        if not lines:

            await update.message.reply_text(
                "❌ لم يتم العثور على مداخلات."
            )

            return

        await update.message.reply_text(

            "✅ *تم استلام حوار البودكاست*\n\n"

            f"💬 عدد المداخلات: **{len(lines)}**\n\n"

            "🔄 سيتم التناوب تلقائيًا بين "
            "المتحدث الأول والثاني.\n\n"

            "⚠️ كل سطر يمثل مداخلة كاملة "
            "لمتحدث واحد.",

            reply_markup=podcast_keyboard(),

            parse_mode="Markdown"

        )

        return


    # --------------------------------------------------------
    # NORMAL
    # --------------------------------------------------------

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
# SHOW SPEAKER MENU
# ============================================================

async def show_speaker_menu(
    query,
    speaker_number
):

    user = get_user(
        query.from_user.id
    )

    speaker = (

        user["speaker1"]

        if speaker_number == 1

        else

        user["speaker2"]

    )

    user["editing_speaker"] = speaker_number

    await query.message.edit_text(

        f"🎤 *إعدادات المتحدث {speaker_number}*\n\n"

        f"🎙️ الصوت: **{speaker['voice_name']}**\n"
        f"⚡ السرعة: **{speaker['rate']}**\n"
        f"↕️ النبرة: **{speaker['pitch']}**\n"
        f"🔊 مستوى الصوت: **{speaker['volume']}**\n\n"

        "اختر الإعداد الذي تريد تعديله:",

        reply_markup=speaker_menu_keyboard(),

        parse_mode="Markdown"

    )


# ============================================================
# PODCAST SETTINGS
# ============================================================

async def show_podcast_settings(query):

    user = get_user(
        query.from_user.id
    )

    s1 = user["speaker1"]
    s2 = user["speaker2"]

    text_status = (

        f"{len(user['podcast_text']):,} حرف"

        if user["podcast_text"]

        else

        "لا يوجد حوار"

    )

    await query.message.edit_text(

        "⚙️ *إعدادات البودكاست*\n\n"

        f"📝 الحوار: **{text_status}**\n\n"

        "🎤 *المتحدث الأول*\n"
        f"🎙️ {s1['voice_name']}\n"
        f"⚡ {s1['rate']}\n"
        f"↕️ {s1['pitch']}\n"
        f"🔊 {s1['volume']}\n\n"

        "🎤 *المتحدث الثاني*\n"
        f"🎙️ {s2['voice_name']}\n"
        f"⚡ {s2['rate']}\n"
        f"↕️ {s2['pitch']}\n"
        f"🔊 {s2['volume']}",

        reply_markup=podcast_keyboard(),

        parse_mode="Markdown"

    )


# ============================================================
# PYAV AUDIO MERGER
# ============================================================
#
# مهم:
# لا نستخدم frame.reformat()
# لأن بعض إصدارات PyAV لا تدعمه.
#
# نستخدم AudioResampler.
#
# ============================================================

def merge_audio_files(
    input_files,
    output_path
):

    if not input_files:

        raise ValueError(
            "لا توجد ملفات صوتية للدمج."
        )

    output_path = Path(output_path)

    output_container = av.open(

        str(output_path),

        mode="w",

        format="mp3"

    )

    output_stream = None

    try:

        for input_path in input_files:

            input_container = None

            try:

                input_container = av.open(

                    str(input_path),

                    mode="r"

                )


                audio_stream = None

                for stream in input_container.streams:

                    if stream.type == "audio":

                        audio_stream = stream

                        break


                if audio_stream is None:

                    continue


                # --------------------------------------------
                # إنشاء ملف الإخراج
                # --------------------------------------------

                if output_stream is None:

                    sample_rate = (

                        audio_stream.rate

                        or

                        24000

                    )


                    output_stream = (

                        output_container.add_stream(

                            "libmp3lame",

                            rate=sample_rate

                        )

                    )


                    try:

                        output_stream.layout = "mono"

                    except Exception:

                        pass


                # --------------------------------------------
                # AUDIO RESAMPLER
                # --------------------------------------------

                resampler = AudioResampler(

                    format="s16",

                    layout="mono",

                    rate=output_stream.rate

                )


                # --------------------------------------------
                # DECODE AUDIO
                # --------------------------------------------

                for frame in input_container.decode(

                    audio_stream

                ):


                    converted = (

                        resampler.resample(

                            frame

                        )

                    )


                    if converted is None:

                        continue


                    # قد يرجع Frame واحد
                    if not isinstance(

                        converted,

                        list

                    ):

                        converted = [

                            converted

                        ]


                    # ----------------------------------------
                    # ENCODE
                    # ----------------------------------------

                    for converted_frame in converted:


                        for packet in output_stream.encode(

                            converted_frame

                        ):


                            output_container.mux(

                                packet

                            )


                # --------------------------------------------
                # FLUSH RESAMPLER
                # --------------------------------------------

                try:

                    remaining = (

                        resampler.resample(

                            None

                        )

                    )


                    if remaining:

                        if not isinstance(

                            remaining,

                            list

                        ):

                            remaining = [

                                remaining

                            ]


                        for remaining_frame in remaining:


                            for packet in output_stream.encode(

                                remaining_frame

                            ):


                                output_container.mux(

                                    packet

                                )

                except Exception:

                    pass


            finally:

                if input_container:

                    input_container.close()


        # ----------------------------------------------------
        # FLUSH MP3 ENCODER
        # ----------------------------------------------------

        if output_stream is None:

            raise ValueError(

                "لم يتم العثور على مسار صوتي صالح."

            )


        for packet in output_stream.encode():

            output_container.mux(

                packet

            )


    finally:

        output_container.close()


    return output_path


# ============================================================
# NORMAL AUDIO GENERATION
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

    final_path = None

    try:

        # ----------------------------------------------------
        # GENERATE CHUNKS
        # ----------------------------------------------------

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


            output_path = AUDIO_DIR / filename


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


        # ----------------------------------------------------
        # FINAL FILE
        # ----------------------------------------------------

        timestamp = datetime.now().strftime(

            "%Y%m%d_%H%M%S_%f"

        )


        final_path = (

            AUDIO_DIR

            /

            f"tts_{user_id}_{timestamp}_FINAL.mp3"

        )


        await update_progress(

            progress_message,

            total,

            total,

            "🎧 جاري دمج الأجزاء في ملف واحد"

        )


        await asyncio.to_thread(

            merge_audio_files,

            generated_files,

            final_path

        )


        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        with open(

            final_path,

            "rb"

        ) as audio:


            await query.message.reply_audio(

                audio=audio,

                title="Telegram TTS",

                performer="Edge TTS"

            )


        await progress_message.edit_text(

            "✅ *اكتملت عملية التحويل بنجاح!*\n\n"

            f"📊 إجمالي الأحرف: **{len(text):,}**\n"
            f"📦 الأجزاء الداخلية: **{total}**\n"
            f"🎙️ الصوت: **{user['voice_name']}**\n"
            f"⚡ السرعة: **{user['rate']}**\n"
            f"↕️ النبرة: **{user['pitch']}**\n"
            f"🔊 مستوى الصوت: **{user['volume']}**\n\n"

            "🎧 تم دمج جميع الأجزاء في ملف MP3 واحد.",

            parse_mode="Markdown"

        )


    except Exception as error:


        logger.exception(

            "TTS generation failed"

        )


        try:

            await progress_message.edit_text(

                "❌ *فشل إنشاء الصوت*\n\n"

                f"`{str(error)}`",

                parse_mode="Markdown"

            )

        except Exception:

            pass


    finally:

        user["busy"] = False


# ============================================================
# PODCAST GENERATION
# ============================================================

async def generate_podcast(query):

    user_id = query.from_user.id

    user = get_user(user_id)

    text = user["podcast_text"]


    if not text:

        await query.message.reply_text(

            "❌ لا يوجد حوار.\n\n"
            "اختر «📝 تغيير الحوار» ثم أرسل الحوار."

        )

        return


    if user["busy"]:

        await query.message.reply_text(

            "⏳ توجد عملية تحويل جارية بالفعل."

        )

        return


    lines = [

        line.strip()

        for line in text.splitlines()

        if line.strip()

    ]


    if not lines:

        await query.message.reply_text(

            "❌ الحوار فارغ."

        )

        return


    user["busy"] = True

    s1 = user["speaker1"]
    s2 = user["speaker2"]


    progress_message = await query.message.reply_text(

        "🎧 *بدء إنشاء البودكاست...*\n\n"

        "`░░░░░░░░░░░░` **0%**\n\n"

        f"💬 عدد المداخلات: **{len(lines)}**\n\n"

        "يرجى الانتظار...",

        parse_mode="Markdown"

    )


    all_audio_files = []


    try:

        total_lines = len(lines)


        # ----------------------------------------------------
        # GENERATE EACH LINE
        # ----------------------------------------------------

        for index, line in enumerate(

            lines,

            start=1

        ):


            # ----------------------------------------------
            # SPEAKER ALTERNATION
            # ----------------------------------------------

            if index % 2 == 1:

                speaker = s1

                speaker_number = 1

            else:

                speaker = s2

                speaker_number = 2


            # ----------------------------------------------
            # SPLIT LONG LINE
            # ----------------------------------------------

            chunks = split_text(line)


            for chunk_index, chunk in enumerate(

                chunks,

                start=1

            ):


                timestamp = datetime.now().strftime(

                    "%Y%m%d_%H%M%S_%f"

                )


                filename = (

                    f"podcast_{user_id}_"
                    f"speaker{speaker_number}_"
                    f"{index:04d}_"
                    f"{chunk_index:04d}_"
                    f"{timestamp}.mp3"

                )


                output_path = AUDIO_DIR / filename


                communicate = edge_tts.Communicate(

                    chunk,

                    voice=speaker["voice"],

                    rate=speaker["rate"],

                    pitch=speaker["pitch"],

                    volume=speaker["volume"]

                )


                await communicate.save(

                    str(output_path)

                )


                all_audio_files.append(

                    output_path

                )


            await update_progress(

                progress_message,

                index,

                total_lines,

                "🎧 جاري إنشاء البودكاست"

            )


        # ----------------------------------------------------
        # FINAL PODCAST
        # ----------------------------------------------------

        timestamp = datetime.now().strftime(

            "%Y%m%d_%H%M%S_%f"

        )


        final_path = (

            AUDIO_DIR

            /

            f"podcast_{user_id}_{timestamp}_FINAL.mp3"

        )


        await update_progress(

            progress_message,

            total_lines,

            total_lines,

            "🎧 جاري دمج البودكاست"

        )


        await asyncio.to_thread(

            merge_audio_files,

            all_audio_files,

            final_path

        )


        # ----------------------------------------------------
        # SEND PODCAST
        # ----------------------------------------------------

        with open(

            final_path,

            "rb"

        ) as audio:


            await query.message.reply_audio(

                audio=audio,

                title="Telegram Podcast",

                performer="Edge TTS"

            )


        await progress_message.edit_text(

            "✅ *تم إنشاء البودكاست بنجاح!*\n\n"

            f"💬 عدد المداخلات: **{total_lines}**\n"
            f"🎤 المتحدث الأول: **{s1['voice_name']}**\n"
            f"🎤 المتحدث الثاني: **{s2['voice_name']}**\n\n"

            f"⚡ سرعة الأول: **{s1['rate']}**\n"
            f"↕️ نبرة الأول: **{s1['pitch']}**\n"
            f"🔊 صوت الأول: **{s1['volume']}**\n\n"

            f"⚡ سرعة الثاني: **{s2['rate']}**\n"
            f"↕️ نبرة الثاني: **{s2['pitch']}**\n"
            f"🔊 صوت الثاني: **{s2['volume']}**\n\n"

            "🎧 تم دمج الحوار كاملًا في ملف MP3 واحد.",

            parse_mode="Markdown"

        )


    except Exception as error:


        logger.exception(

            "Podcast generation failed"

        )


        try:

            await progress_message.edit_text(

                "❌ *فشل إنشاء البودكاست*\n\n"

                f"`{str(error)}`",

                parse_mode="Markdown"

            )

        except Exception:

            pass


    finally:

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


    # ========================================================
    # START
    # ========================================================

    if data == "start_bot":

        await open_bot_menu(query)

        return


    # ========================================================
    # BACK
    # ========================================================

    if data == "back":

        user["mode"] = "normal"

        await query.message.edit_text(

            "🎙️ *Telegram TTS Pro*\n\n"
            "اختر العملية:",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ========================================================
    # TEXT MENU
    # ========================================================

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


    # ========================================================
    # NORMAL VOICE
    # ========================================================

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
                0,
                "selectvoice"
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
                0,
                "selectvoice"
            ),

            parse_mode="Markdown"

        )

        return


    if data.startswith("voicepage:selectvoice:"):

        _, _, language, page = data.split(":")

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
                page,
                "selectvoice"
            )

        )

        return


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


    # ========================================================
    # LANGUAGE
    # ========================================================

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


    # ========================================================
    # NORMAL RATE
    # ========================================================

    if data == "rate_menu":

        await query.message.edit_text(

            "⚡ *اختر سرعة النطق:*",

            reply_markup=rate_keyboard(
                "rate"
            ),

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


    # ========================================================
    # NORMAL PITCH
    # ========================================================

    if data == "pitch_menu":

        await query.message.edit_text(

            "↕️ *اختر النبرة:*",

            reply_markup=pitch_keyboard(
                "pitch"
            ),

            parse_mode="Markdown"

        )

        return


    if data.startswith("pitch:"):

        user["pitch"] = data.split(
            ":",
            1
        )[1]


        await query.message.edit_text(

            f"↕️ النبرة: {user['pitch']}",

            reply_markup=main_keyboard()

        )

        return


    # ========================================================
    # NORMAL VOLUME
    # ========================================================

    if data == "volume_menu":

        await query.message.edit_text(

            "🔊 *اختر مستوى الصوت:*",

            reply_markup=volume_keyboard(
                "volume"
            ),

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


    # ========================================================
    # NORMAL SETTINGS
    # ========================================================

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
            f"↕️ النبرة: {user['pitch']}\n"
            f"🔊 مستوى الصوت: {user['volume']}",

            reply_markup=main_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ========================================================
    # NORMAL GENERATE
    # ========================================================

    if data == "generate":

        user["mode"] = "normal"

        await generate_audio(query)

        return


    # ========================================================
    # PODCAST MENU
    # ========================================================

    if data == "podcast_menu":

        user["mode"] = "podcast"


        await query.message.edit_text(

            "🎧 *وضع البودكاست*\n\n"

            "أنشئ حوارًا بين متحدثين.\n\n"

            "📝 أرسل الحوار بحيث يكون كل سطر "
            "مداخلة كاملة لمتحدث واحد.\n\n"

            "🔄 التناوب يتم تلقائيًا.\n"
            "🚫 لا تكتب أسماء المتحدثين.\n"
            "🚫 لا تضع أرقامًا في بداية السطور.",

            reply_markup=podcast_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ========================================================
    # PODCAST TEXT
    # ========================================================

    if data == "podcast_text":

        user["mode"] = "podcast"


        await query.message.edit_text(

            "📝 *أرسل حوار البودكاست الآن*\n\n"

            "كل سطر = مداخلة كاملة لمتحدث واحد.\n\n"

            "السطر 1 → المتحدث الأول\n"
            "السطر 2 → المتحدث الثاني\n"
            "السطر 3 → المتحدث الأول\n"
            "السطر 4 → المتحدث الثاني",

            reply_markup=podcast_keyboard(),

            parse_mode="Markdown"

        )

        return


    # ========================================================
    # SPEAKER 1
    # ========================================================

    if data == "speaker1_menu":

        user["mode"] = "podcast"

        await show_speaker_menu(
            query,
            1
        )

        return


    # ========================================================
    # SPEAKER 2
    # ========================================================

    if data == "speaker2_menu":

        user["mode"] = "podcast"

        await show_speaker_menu(
            query,
            2
        )

        return


    # ========================================================
    # PODCAST SPEAKER BACK
    # ========================================================

    if data == "podcast_speaker_menu":

        speaker_number = user[
            "editing_speaker"
        ]


        await show_speaker_menu(
            query,
            speaker_number
        )

        return


    # ========================================================
    # PODCAST VOICE
    # ========================================================

    if data == "podcast_voice_menu":

        await query.message.edit_text(

            "🎤 *اختيار صوت المتحدث*\n\n"
            "اختر مجموعة الأصوات:",

            reply_markup=podcast_voice_keyboard(),

            parse_mode="Markdown"

        )

        return


    if data == "podcast_arabic_voices":

        await query.message.edit_text(

            "🇪🇬 *أصوات المتحدث العربية*",

            reply_markup=voice_list_keyboard(
                ARABIC_VOICES,
                "ar",
                0,
                "pvoice"
            ),

            parse_mode="Markdown"

        )

        return


    if data == "podcast_english_voices":

        await query.message.edit_text(

            "🇺🇸 *English Voices*",

            reply_markup=voice_list_keyboard(
                ENGLISH_VOICES,
                "en",
                0,
                "pvoice"
            ),

            parse_mode="Markdown"

        )

        return


    if data.startswith("voicepage:pvoice:"):

        _, _, language, page = data.split(":")

        page = int(page)


        voices = (

            ARABIC_VOICES

            if language == "ar"

            else

            ENGLISH_VOICES

        )


        await query.message.edit_text(

            "🎤 اختر صوت المتحدث:",

            reply_markup=voice_list_keyboard(
                voices,
                language,
                page,
                "pvoice"
            )

        )

        return


    if data.startswith("pvoice:"):

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

            speaker_number = user[
                "editing_speaker"
            ]


            speaker = (

                user["speaker1"]

                if speaker_number == 1

                else

                user["speaker2"]

            )


            speaker["voice"] = voice

            speaker["voice_name"] = name


            await show_speaker_menu(

                query,

                speaker_number

            )

        return


    # ========================================================
    # PODCAST RATE
    # ========================================================

    if data == "podcast_rate_menu":

        await query.message.edit_text(

            "⚡ *سرعة المتحدث*",

            reply_markup=rate_keyboard(
                "prate"
            ),

            parse_mode="Markdown"

        )

        return


    if data.startswith("prate:"):

        value = data.split(
            ":",
            1
        )[1]


        speaker_number = user[
            "editing_speaker"
        ]


        speaker = (

            user["speaker1"]

            if speaker_number == 1

            else

            user["speaker2"]

        )


        speaker["rate"] = value


        await show_speaker_menu(

            query,

            speaker_number

        )

        return


    # ========================================================
    # PODCAST PITCH
    # ========================================================

    if data == "podcast_pitch_menu":

        await query.message.edit_text(

            "↕️ *نبرة المتحدث*",

            reply_markup=pitch_keyboard(
                "ppitch"
            ),

            parse_mode="Markdown"

        )

        return


    if data.startswith("ppitch:"):

        value = data.split(
            ":",
            1
        )[1]


        speaker_number = user[
            "editing_speaker"
        ]


        speaker = (

            user["speaker1"]

            if speaker_number == 1

            else

            user["speaker2"]

        )


        speaker["pitch"] = value


        await show_speaker_menu(

            query,

            speaker_number

        )

        return


    # ========================================================
    # PODCAST VOLUME
    # ========================================================

    if data == "podcast_volume_menu":

        await query.message.edit_text(

            "🔊 *مستوى صوت المتحدث*",

            reply_markup=volume_keyboard(
                "pvolume"
            ),

            parse_mode="Markdown"

        )

        return


    if data.startswith("pvolume:"):

        value = data.split(
            ":",
            1
        )[1]


        speaker_number = user[
            "editing_speaker"
        ]


        speaker = (

            user["speaker1"]

            if speaker_number == 1

            else

            user["speaker2"]

        )


        speaker["volume"] = value


        await show_speaker_menu(

            query,

            speaker_number

        )

        return


    # ========================================================
    # PODCAST SETTINGS
    # ========================================================

    if data == "podcast_settings":

        await show_podcast_settings(
            query
        )

        return


    # ========================================================
    # GENERATE PODCAST
    # ========================================================

    if data == "generate_podcast":

        user["mode"] = "podcast"

        await generate_podcast(
            query
        )

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
