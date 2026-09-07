import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime

import edge_tts
import av

from av.audio.resampler import AudioResampler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / "generated_audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

MAX_CHARS = 2500

# مدة السكتات بالمللي ثانية
PAUSE_DURATIONS = {
    "SHORT": 350,
    "MEDIUM": 700,
    "LONG": 1200,
}


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# VOICES
# =========================================================

ARABIC_VOICES = [
    ("ar-EG-ShakirNeural", "شاكر 🇪🇬"),
    ("ar-EG-SalmaNeural", "سلمى 🇪🇬"),
    ("ar-SA-HamedNeural", "حامد 🇸🇦"),
    ("ar-SA-ZariyahNeural", "زارية 🇸🇦"),
    ("ar-AE-HamdanNeural", "حمدان 🇦🇪"),
    ("ar-AE-FatimaNeural", "فاطمة 🇦🇪"),
    ("ar-IQ-BasselNeural", "باسل 🇮🇶"),
    ("ar-IQ-RanaNeural", "رنا 🇮🇶"),
    ("ar-JO-TaimNeural", "تيم 🇯🇴"),
    ("ar-JO-SanaNeural", "سناء 🇯🇴"),
    ("ar-KW-FahedNeural", "فهد 🇰🇼"),
    ("ar-KW-NouraNeural", "نورة 🇰🇼"),
    ("ar-LB-RamiNeural", "رامي 🇱🇧"),
    ("ar-LB-LaylaNeural", "ليلى 🇱🇧"),
    ("ar-MA-JamalNeural", "جمال 🇲🇦"),
    ("ar-MA-MounaNeural", "منى 🇲🇦"),
    ("ar-OM-AbdullahNeural", "عبدالله 🇴🇲"),
    ("ar-OM-AyshaNeural", "عائشة 🇴🇲"),
    ("ar-QA-MoazNeural", "معاذ 🇶🇦"),
    ("ar-SY-LaithNeural", "ليث 🇸🇾"),
    ("ar-SY-AmanyNeural", "أماني 🇸🇾"),
    ("ar-TN-HediNeural", "هادي 🇹🇳"),
    ("ar-TN-ReemNeural", "ريم 🇹🇳"),
]

ENGLISH_VOICES = [
    ("en-US-GuyNeural", "Guy 🇺🇸"),
    ("en-US-AvaNeural", "Ava 🇺🇸"),
    ("en-US-AndrewNeural", "Andrew 🇺🇸"),
    ("en-US-EmmaNeural", "Emma 🇺🇸"),
    ("en-GB-RyanNeural", "Ryan 🇬🇧"),
    ("en-GB-SoniaNeural", "Sonia 🇬🇧"),
    ("en-AU-WilliamNeural", "William 🇦🇺"),
    ("en-AU-NatashaNeural", "Natasha 🇦🇺"),
    ("en-CA-LiamNeural", "Liam 🇨🇦"),
    ("en-CA-ClaraNeural", "Clara 🇨🇦"),
]


# =========================================================
# USER STATE
# =========================================================

users = {}


def default_speaker():
    return {
        "voice": "ar-EG-ShakirNeural",
        "voice_name": "شاكر 🇪🇬",
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

            "voice": "ar-EG-ShakirNeural",
            "voice_name": "شاكر 🇪🇬",

            "rate": "+0%",
            "pitch": "+0Hz",
            "volume": "+0%",

            "podcast_text": "",

            "speaker1": default_speaker(),
            "speaker2": {
                "voice": "ar-EG-SalmaNeural",
                "voice_name": "سلمى 🇪🇬",
                "rate": "+0%",
                "pitch": "+0Hz",
                "volume": "+0%",
            },

            "editing_speaker": 1,
            "busy": False,
        }

    return users[user_id]


# =========================================================
# LANGUAGE
# =========================================================

def detect_language(text):
    arabic = len(re.findall(r"[\u0600-\u06FF]", text))
    english = len(re.findall(r"[A-Za-z]", text))

    if arabic >= english:
        return "ar"

    return "en"


def choose_auto_voice(language):
    if language == "ar":
        return "ar-EG-ShakirNeural", "شاكر 🇪🇬"

    return "en-US-GuyNeural", "Guy 🇺🇸"


# =========================================================
# TEXT SPLITTING
# =========================================================

def split_text(text, max_chars=MAX_CHARS):
    """
    تقسيم النص الطويل مع الحفاظ على ترتيب الكلام.
    """

    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n+", text)
    chunks = []

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue

        sentences = re.split(
            r"(?<=[.!؟!؛])\s+",
            paragraph
        )

        current = ""

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            if len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""

                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i:i + max_chars])

                continue

            if not current:
                current = sentence

            elif len(current) + 1 + len(sentence) <= max_chars:
                current += " " + sentence

            else:
                chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)

    return chunks


# =========================================================
# PAUSE PARSER
# =========================================================

PAUSE_PATTERN = re.compile(
    r"\[PAUSE\s*:\s*(SHORT|MEDIUM|LONG)\s*\]",
    re.IGNORECASE
)


def parse_pause_tokens(text):
    """
    يحول النص إلى أجزاء:

    ("text", "الكلام")
    ("pause", 700)
    ("text", "كلام آخر")
    """

    parts = []

    last_end = 0

    for match in PAUSE_PATTERN.finditer(text):
        before = text[last_end:match.start()]

        if before.strip():
            parts.append(
                ("text", before.strip())
            )

        pause_type = match.group(1).upper()
        duration = PAUSE_DURATIONS[pause_type]

        parts.append(
            ("pause", duration)
        )

        last_end = match.end()

    remaining = text[last_end:]

    if remaining.strip():
        parts.append(
            ("text", remaining.strip())
        )

    return parts


def remove_pause_tokens(text):
    """
    للاستخدام عند الحاجة لتنظيف النص فقط.
    """

    return PAUSE_PATTERN.sub("", text).strip()


# =========================================================
# FILE NAME
# =========================================================

def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


# =========================================================
# EDGE TTS
# =========================================================

async def synthesize_to_file(
    text,
    output_path,
    voice,
    rate="+0%",
    pitch="+0Hz",
    volume="+0%",
):
    """
    إنشاء ملف MP3 من جزء نصي واحد.
    """

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )

    await communicate.save(str(output_path))


# =========================================================
# REAL SILENCE FILE
# =========================================================

def create_silence_mp3(
    output_path,
    duration_ms,
    sample_rate=24000,
):
    """
    إنشاء ملف MP3 يحتوي على صمت حقيقي.
    """

    duration_seconds = duration_ms / 1000.0

    output_container = av.open(
        str(output_path),
        mode="w",
        format="mp3",
    )

    try:
        stream = output_container.add_stream(
            "libmp3lame",
            rate=sample_rate,
        )

        stream.layout = "mono"

        total_samples = int(
            duration_seconds * sample_rate
        )

        frame_size = 1152
        remaining = total_samples

        while remaining > 0:
            samples = min(
                frame_size,
                remaining
            )

            frame = av.AudioFrame(
                format="s16",
                layout="mono",
                samples=samples,
            )

            frame.sample_rate = sample_rate

            # الصفر = صمت رقمي حقيقي
            for plane in frame.planes:
                plane.update(
                    b"\x00" * plane.buffer_size
                )

            for packet in stream.encode(frame):
                output_container.mux(packet)

            remaining -= samples

        for packet in stream.encode():
            output_container.mux(packet)

    finally:
        output_container.close()


# =========================================================
# PYAV MERGE
# =========================================================

def merge_audio_files(
    input_files,
    output_path,
    sample_rate=24000,
):
    """
    دمج جميع ملفات MP3 باستخدام PyAV.

    لا يستخدم frame.reformat().
    يستخدم AudioResampler المتوافق مع PyAV.
    """

    if not input_files:
        raise ValueError("لا توجد ملفات صوتية للدمج.")

    output_container = av.open(
        str(output_path),
        mode="w",
        format="mp3",
    )

    output_stream = None

    try:

        for file_path in input_files:

            input_container = av.open(
                str(file_path),
                mode="r",
            )

            try:

                audio_streams = [
                    s for s in input_container.streams
                    if s.type == "audio"
                ]

                if not audio_streams:
                    continue

                input_stream = audio_streams[0]

                target_rate = sample_rate

                if output_stream is None:
                    output_stream = output_container.add_stream(
                        "libmp3lame",
                        rate=target_rate,
                    )

                    output_stream.layout = "mono"

                # =================================================
                # مهم:
                # لا نستخدم frame.reformat()
                # =================================================

                resampler = AudioResampler(
                    format="s16",
                    layout="mono",
                    rate=target_rate,
                )

                for frame in input_container.decode(
                    input_stream
                ):

                    resampled_frames = resampler.resample(
                        frame
                    )

                    if resampled_frames is None:
                        continue

                    if not isinstance(
                        resampled_frames,
                        (list, tuple)
                    ):
                        resampled_frames = [
                            resampled_frames
                        ]

                    for resampled_frame in resampled_frames:

                        for packet in output_stream.encode(
                            resampled_frame
                        ):
                            output_container.mux(packet)

                # تفريغ أي Frames معلقة داخل الـresampler
                try:
                    flushed_frames = resampler.resample(None)
                except Exception:
                    flushed_frames = []

                if flushed_frames is None:
                    flushed_frames = []

                if not isinstance(
                    flushed_frames,
                    (list, tuple)
                ):
                    flushed_frames = [
                        flushed_frames
                    ]

                for flushed_frame in flushed_frames:

                    for packet in output_stream.encode(
                        flushed_frame
                    ):
                        output_container.mux(packet)

            finally:
                input_container.close()

        if output_stream is not None:

            for packet in output_stream.encode():
                output_container.mux(packet)

    finally:
        output_container.close()


# =========================================================
# PROGRESS
# =========================================================

async def update_progress(
    message,
    current,
    total,
    prefix="جاري المعالجة",
):
    if total <= 0:
        return

    percent = int(
        (current / total) * 100
    )

    blocks = percent // 10

    bar = (
        "█" * blocks
        + "░" * (10 - blocks)
    )

    try:
        await message.edit_text(
            f"{prefix}\n\n"
            f"{bar} {percent}%\n"
            f"{current} / {total}"
        )
    except Exception:
        pass


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    user = get_user(user_id)

    user["mode"] = "normal"

    keyboard = [
        [
            InlineKeyboardButton(
                "📝 النص",
                callback_data="text_mode"
            ),
            InlineKeyboardButton(
                "🎧 البودكاست",
                callback_data="podcast_mode"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎙 الصوت",
                callback_data="voice"
            ),
            InlineKeyboardButton(
                "🌐 اللغة",
                callback_data="language"
            ),
        ],
        [
            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data="rate"
            ),
            InlineKeyboardButton(
                "↕️ النبرة",
                callback_data="pitch"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔊 مستوى الصوت",
                callback_data="volume"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎵 توليد MP3",
                callback_data="generate"
            ),
        ],
    ]

    await update.message.reply_text(
        "مرحبًا بك 👋\n\n"
        "أرسل النص الذي تريد تحويله إلى صوت، "
        "أو اختر 🎧 البودكاست لإنشاء حوار بين متحدثين.\n\n"
        "في البودكاست يمكن للنص استخدام:\n"
        "[PAUSE:SHORT]\n"
        "[PAUSE:MEDIUM]\n"
        "[PAUSE:LONG]\n\n"
        "والبرنامج يحولها إلى سكتات صوتية حقيقية.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# MENU
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📝 النص",
                callback_data="text_mode"
            ),
            InlineKeyboardButton(
                "🎧 البودكاست",
                callback_data="podcast_mode"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎙 الصوت",
                callback_data="voice"
            ),
            InlineKeyboardButton(
                "🌐 اللغة",
                callback_data="language"
            ),
        ],
        [
            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data="rate"
            ),
            InlineKeyboardButton(
                "↕️ النبرة",
                callback_data="pitch"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔊 مستوى الصوت",
                callback_data="volume"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎵 توليد MP3",
                callback_data="generate"
            ),
        ],
    ])


# =========================================================
# TEXT INPUT
# =========================================================

async def receive_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id
    user = get_user(user_id)

    text = update.message.text.strip()

    if not text:
        return

    # -----------------------------------------------------
    # PODCAST MODE
    # -----------------------------------------------------

    if user["mode"] == "podcast":

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not lines:
            await update.message.reply_text(
                "أرسل الحوار، بحيث يكون كل دور للمتحدث في سطر مستقل."
            )
            return

        user["podcast_text"] = "\n".join(lines)

        await update.message.reply_text(
            f"🎧 تم استلام الحوار.\n\n"
            f"عدد الأدوار: {len(lines)}\n\n"
            f"التناوب:\n"
            f"الدور 1 → المتحدث الأول\n"
            f"الدور 2 → المتحدث الثاني\n"
            f"الدور 3 → المتحدث الأول\n"
            f"الدور 4 → المتحدث الثاني\n"
            f"وهكذا...\n\n"
            f"السكتات المدعومة:\n"
            f"• [PAUSE:SHORT]\n"
            f"• [PAUSE:MEDIUM]\n"
            f"• [PAUSE:LONG]",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # NORMAL MODE
    # -----------------------------------------------------

    user["text"] = text

    if user["language"] == "auto":

        language = detect_language(text)

        voice, voice_name = choose_auto_voice(
            language
        )

        user["voice"] = voice
        user["voice_name"] = voice_name

    await update.message.reply_text(
        f"✅ تم حفظ النص.\n\n"
        f"عدد الأحرف: {len(text)}\n"
        f"الصوت: {user['voice_name']}",
        reply_markup=main_keyboard(),
    )


# =========================================================
# VOICE MENU
# =========================================================

async def voice_menu(
    query,
    user,
):

    voices = (
        ARABIC_VOICES
        if user["language"] in ("auto", "ar")
        else ENGLISH_VOICES
    )

    keyboard = []

    for i in range(0, len(voices), 2):

        row = []

        for voice, name in voices[i:i + 2]:

            row.append(
                InlineKeyboardButton(
                    name,
                    callback_data=f"setvoice:{voice}"
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="back"
        )
    ])

    await query.edit_message_text(
        "🎙 اختر الصوت:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# LANGUAGE MENU
# =========================================================

async def language_menu(
    query,
    user,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🇪🇬 العربية",
                callback_data="lang:ar"
            ),
            InlineKeyboardButton(
                "🇺🇸 English",
                callback_data="lang:en"
            ),
        ],
        [
            InlineKeyboardButton(
                "🤖 تلقائي",
                callback_data="lang:auto"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="back"
            )
        ],
    ]

    await query.edit_message_text(
        "🌐 اختر اللغة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# RATE MENU
# =========================================================

async def rate_menu(
    query,
    user,
):

    rates = [
        ("🐢 -30%", "-30%"),
        ("🐢 -15%", "-15%"),
        ("◀️ -5%", "-5%"),
        ("⏺ 0%", "+0%"),
        ("▶️ +5%", "+5%"),
        ("⚡ +15%", "+15%"),
        ("⚡ +30%", "+30%"),
    ]

    keyboard = []

    for title, value in rates:

        keyboard.append([
            InlineKeyboardButton(
                title,
                callback_data=f"ratevalue:{value}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="back"
        )
    ])

    await query.edit_message_text(
        "⚡ اختر سرعة النطق:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# PITCH MENU
# =========================================================

async def pitch_menu(
    query,
    user,
):

    pitches = [
        ("⬇️ منخفض جدًا", "-10Hz"),
        ("⬇️ منخفض", "-5Hz"),
        ("⏺ طبيعي", "+0Hz"),
        ("⬆️ مرتفع", "+5Hz"),
        ("⬆️ مرتفع جدًا", "+10Hz"),
    ]

    keyboard = []

    for title, value in pitches:

        keyboard.append([
            InlineKeyboardButton(
                title,
                callback_data=f"pitchvalue:{value}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="back"
        )
    ])

    await query.edit_message_text(
        "↕️ اختر النبرة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# VOLUME MENU
# =========================================================

async def volume_menu(
    query,
    user,
):

    volumes = [
        ("🔉 -20%", "-20%"),
        ("🔉 -10%", "-10%"),
        ("⏺ 0%", "+0%"),
        ("🔊 +10%", "+10%"),
        ("🔊 +20%", "+20%"),
    ]

    keyboard = []

    for title, value in volumes:

        keyboard.append([
            InlineKeyboardButton(
                title,
                callback_data=f"volumevalue:{value}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="back"
        )
    ])

    await query.edit_message_text(
        "🔊 اختر مستوى الصوت:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# PODCAST MENU
# =========================================================

async def podcast_menu(
    query,
    user,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🎙 المتحدث الأول",
                callback_data="speaker:1"
            ),
            InlineKeyboardButton(
                "🎙 المتحدث الثاني",
                callback_data="speaker:2"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎵 إنشاء البودكاست",
                callback_data="generate"
            ),
        ],
        [
            InlineKeyboardButton(
                "🗑 مسح الحوار",
                callback_data="clear_podcast"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="back"
            )
        ],
    ]

    await query.edit_message_text(
        "🎧 إعدادات البودكاست\n\n"
        "كل سطر في الحوار يمثل دورًا كاملًا لمتحدث.\n\n"
        "المتحدث الأول → السطر 1، 3، 5...\n"
        "المتحدث الثاني → السطر 2، 4، 6...\n\n"
        "يمكن للحوار استخدام السكتات:\n"
        "[PAUSE:SHORT]\n"
        "[PAUSE:MEDIUM]\n"
        "[PAUSE:LONG]",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# SPEAKER MENU
# =========================================================

async def speaker_menu(
    query,
    user,
    speaker_number,
):

    speaker = user[
        f"speaker{speaker_number}"
    ]

    user["editing_speaker"] = speaker_number

    keyboard = [
        [
            InlineKeyboardButton(
                "🎙 الصوت",
                callback_data=f"spvoice:{speaker_number}"
            ),
        ],
        [
            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data=f"sprate:{speaker_number}"
            ),
            InlineKeyboardButton(
                "↕️ النبرة",
                callback_data=f"sppitch:{speaker_number}"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔊 الصوت",
                callback_data=f"spvolume:{speaker_number}"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="podcast_menu"
            ),
        ],
    ]

    await query.edit_message_text(
        f"🎙 إعدادات المتحدث {speaker_number}\n\n"
        f"الصوت: {speaker['voice_name']}\n"
        f"السرعة: {speaker['rate']}\n"
        f"النبرة: {speaker['pitch']}\n"
        f"مستوى الصوت: {speaker['volume']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# SPEAKER VOICE
# =========================================================

async def speaker_voice_menu(
    query,
    user,
    speaker_number,
):

    voices = (
        ARABIC_VOICES
        if user["language"] in ("auto", "ar")
        else ENGLISH_VOICES
    )

    keyboard = []

    for voice, name in voices:

        keyboard.append([
            InlineKeyboardButton(
                name,
                callback_data=f"setspvoice:{speaker_number}:{voice}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=f"speaker:{speaker_number}"
        )
    ])

    await query.edit_message_text(
        f"🎙 صوت المتحدث {speaker_number}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# SPEAKER RATE
# =========================================================

async def speaker_rate_menu(
    query,
    user,
    speaker_number,
):

    values = [
        "-30%",
        "-15%",
        "-5%",
        "+0%",
        "+5%",
        "+15%",
        "+30%",
    ]

    keyboard = []

    for value in values:

        keyboard.append([
            InlineKeyboardButton(
                value,
                callback_data=f"setsprate:{speaker_number}:{value}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=f"speaker:{speaker_number}"
        )
    ])

    await query.edit_message_text(
        f"⚡ سرعة المتحدث {speaker_number}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# SPEAKER PITCH
# =========================================================

async def speaker_pitch_menu(
    query,
    user,
    speaker_number,
):

    values = [
        "-10Hz",
        "-5Hz",
        "+0Hz",
        "+5Hz",
        "+10Hz",
    ]

    keyboard = []

    for value in values:

        keyboard.append([
            InlineKeyboardButton(
                value,
                callback_data=f"setsppitch:{speaker_number}:{value}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=f"speaker:{speaker_number}"
        )
    ])

    await query.edit_message_text(
        f"↕️ نبرة المتحدث {speaker_number}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# SPEAKER VOLUME
# =========================================================

async def speaker_volume_menu(
    query,
    user,
    speaker_number,
):

    values = [
        "-20%",
        "-10%",
        "+0%",
        "+10%",
        "+20%",
    ]

    keyboard = []

    for value in values:

        keyboard.append([
            InlineKeyboardButton(
                value,
                callback_data=f"setspvolume:{speaker_number}:{value}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=f"speaker:{speaker_number}"
        )
    ])

    await query.edit_message_text(
        f"🔊 مستوى صوت المتحدث {speaker_number}:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# NORMAL AUDIO GENERATION
# =========================================================

async def generate_audio(
    update,
    context,
    user,
):

    if not user["text"].strip():

        await update.callback_query.message.reply_text(
            "❌ لم يتم إدخال أي نص."
        )

        return

    user_id = update.effective_user.id

    text = user["text"].strip()

    language = (
        detect_language(text)
        if user["language"] == "auto"
        else user["language"]
    )

    if user["language"] == "auto":

        voice, voice_name = choose_auto_voice(
            language
        )

        user["voice"] = voice
        user["voice_name"] = voice_name

    chunks = split_text(text)

    status = await update.callback_query.message.reply_text(
        "⏳ بدء تحويل النص إلى صوت..."
    )

    generated_files = []

    try:

        total = len(chunks)

        for index, chunk in enumerate(
            chunks,
            start=1
        ):

            filename = (
                f"tts_{user_id}_"
                f"{timestamp()}_"
                f"{index}.mp3"
            )

            path = AUDIO_DIR / filename

            await synthesize_to_file(
                chunk,
                path,
                user["voice"],
                user["rate"],
                user["pitch"],
                user["volume"],
            )

            generated_files.append(path)

            await update_progress(
                status,
                index,
                total,
                "🎙 تحويل النص إلى صوت",
            )

        final_path = (
            AUDIO_DIR
            / f"tts_{user_id}_{timestamp()}_FINAL.mp3"
        )

        await status.edit_text(
            "🔄 جاري دمج الأجزاء في ملف واحد..."
        )

        await asyncio.to_thread(
            merge_audio_files,
            generated_files,
            final_path,
        )

        await status.edit_text(
            "✅ تم إنشاء الملف بنجاح."
        )

        with open(final_path, "rb") as audio:

            await update.callback_query.message.reply_audio(
                audio=audio,
                filename=final_path.name,
                title="TTS Audio",
            )

    except Exception as e:

        logger.exception(
            "Normal TTS error"
        )

        await status.edit_text(
            f"❌ حدث خطأ أثناء إنشاء الصوت:\n\n"
            f"{e}"
        )


# =========================================================
# PODCAST GENERATION
# =========================================================

async def generate_podcast(
    update,
    context,
    user,
):

    if not user["podcast_text"].strip():

        await update.callback_query.message.reply_text(
            "❌ لم يتم إدخال حوار البودكاست."
        )

        return

    user_id = update.effective_user.id

    lines = [
        line.strip()
        for line in user["podcast_text"].splitlines()
        if line.strip()
    ]

    if not lines:

        await update.callback_query.message.reply_text(
            "❌ الحوار فارغ."
        )

        return

    status = await update.callback_query.message.reply_text(
        "⏳ بدء إنشاء البودكاست..."
    )

    generated_files = []

    try:

        total = len(lines)

        # =====================================================
        # كل سطر = دور كامل
        # السطر 1 → speaker 1
        # السطر 2 → speaker 2
        # السطر 3 → speaker 1
        # ...
        # =====================================================

        for line_index, line in enumerate(
            lines,
            start=1
        ):

            speaker_number = (
                1
                if line_index % 2 == 1
                else 2
            )

            speaker = user[
                f"speaker{speaker_number}"
            ]

            # -------------------------------------------------
            # تحليل السكتات الموجودة داخل الدور
            # -------------------------------------------------

            parts = parse_pause_tokens(line)

            text_parts = [
                part
                for part in parts
                if part[0] == "text"
            ]

            pause_parts = [
                part
                for part in parts
                if part[0] == "pause"
            ]

            # -------------------------------------------------
            # إذا لم توجد سكتات:
            # نستخدم split_text العادي
            # -------------------------------------------------

            if not pause_parts:

                chunks = split_text(line)

                for chunk_index, chunk in enumerate(
                    chunks,
                    start=1
                ):

                    filename = (
                        f"podcast_{user_id}_"
                        f"{timestamp()}_"
                        f"line{line_index}_"
                        f"part{chunk_index}_"
                        f"speaker{speaker_number}.mp3"
                    )

                    path = AUDIO_DIR / filename

                    await synthesize_to_file(
                        chunk,
                        path,
                        speaker["voice"],
                        speaker["rate"],
                        speaker["pitch"],
                        speaker["volume"],
                    )

                    generated_files.append(path)

            # -------------------------------------------------
            # إذا توجد سكتات:
            # الكلام → الصوت
            # السكتة → ملف صمت حقيقي
            # -------------------------------------------------

            else:

                segment_index = 0

                for part_type, value in parts:

                    segment_index += 1

                    if part_type == "text":

                        text_chunks = split_text(
                            value
                        )

                        for chunk_index, chunk in enumerate(
                            text_chunks,
                            start=1
                        ):

                            filename = (
                                f"podcast_{user_id}_"
                                f"{timestamp()}_"
                                f"line{line_index}_"
                                f"segment{segment_index}_"
                                f"part{chunk_index}_"
                                f"speaker{speaker_number}.mp3"
                            )

                            path = AUDIO_DIR / filename

                            await synthesize_to_file(
                                chunk,
                                path,
                                speaker["voice"],
                                speaker["rate"],
                                speaker["pitch"],
                                speaker["volume"],
                            )

                            generated_files.append(path)

                    elif part_type == "pause":

                        duration_ms = int(value)

                        filename = (
                            f"podcast_{user_id}_"
                            f"{timestamp()}_"
                            f"line{line_index}_"
                            f"pause{segment_index}_"
                            f"{duration_ms}ms.mp3"
                        )

                        path = AUDIO_DIR / filename

                        await asyncio.to_thread(
                            create_silence_mp3,
                            path,
                            duration_ms,
                        )

                        generated_files.append(path)

            await update_progress(
                status,
                line_index,
                total,
                f"🎧 إنشاء البودكاست\n"
                f"المتحدث الحالي: {speaker_number}",
            )

        if not generated_files:

            raise ValueError(
                "لم يتم إنشاء أي ملفات صوتية."
            )

        final_path = (
            AUDIO_DIR
            / f"podcast_{user_id}_"
            f"{timestamp()}_FINAL.mp3"
        )

        await status.edit_text(
            "🔄 جاري دمج الحوار والسكتات الصوتية..."
        )

        # =====================================================
        # الدمج يحافظ على الترتيب:
        #
        # Speaker 1
        # Pause
        # Speaker 1
        # Speaker 2
        # Pause
        # Speaker 2
        # Speaker 1
        # ...
        # =====================================================

        await asyncio.to_thread(
            merge_audio_files,
            generated_files,
            final_path,
        )

        await status.edit_text(
            "✅ تم إنشاء البودكاست بنجاح."
        )

        with open(final_path, "rb") as audio:

            await update.callback_query.message.reply_audio(
                audio=audio,
                filename=final_path.name,
                title="Podcast",
            )

    except Exception as e:

        logger.exception(
            "Podcast generation error"
        )

        await status.edit_text(
            f"❌ حدث خطأ أثناء إنشاء البودكاست:\n\n"
            f"{e}"
        )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id
    user = get_user(user_id)

    data = query.data

    # -----------------------------------------------------
    # NORMAL TEXT
    # -----------------------------------------------------

    if data == "text_mode":

        user["mode"] = "normal"

        await query.edit_message_text(
            "📝 وضع النص العادي.\n\n"
            "أرسل النص الذي تريد تحويله إلى صوت.",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # PODCAST MODE
    # -----------------------------------------------------

    if data == "podcast_mode":

        user["mode"] = "podcast"

        await query.edit_message_text(
            "🎧 وضع البودكاست.\n\n"
            "أرسل الحوار بحيث يكون كل دور في سطر مستقل.\n\n"
            "مثال:\n\n"
            "أهلًا بكم في حلقة اليوم. [PAUSE:SHORT]\n"
            "أهلًا بك، يسعدني أن أكون معكم. [PAUSE:MEDIUM]\n"
            "اليوم سنتحدث عن موضوع مهم.\n"
            "بالتأكيد، ولنبدأ من النقطة الأساسية. [PAUSE:LONG]\n\n"
            "السطر 1 → المتحدث 1\n"
            "السطر 2 → المتحدث 2\n"
            "وهكذا.",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # PODCAST MENU
    # -----------------------------------------------------

    if data == "podcast_menu":

        await podcast_menu(
            query,
            user,
        )

        return

    # -----------------------------------------------------
    # SPEAKER
    # -----------------------------------------------------

    if data.startswith("speaker:"):

        speaker_number = int(
            data.split(":")[1]
        )

        await speaker_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SPEAKER VOICE
    # -----------------------------------------------------

    if data.startswith("spvoice:"):

        speaker_number = int(
            data.split(":")[1]
        )

        await speaker_voice_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SET SPEAKER VOICE
    # -----------------------------------------------------

    if data.startswith("setspvoice:"):

        _, speaker_number, voice = data.split(
            ":",
            2
        )

        speaker_number = int(
            speaker_number
        )

        speaker = user[
            f"speaker{speaker_number}"
        ]

        speaker["voice"] = voice

        for voice_id, name in (
            ARABIC_VOICES + ENGLISH_VOICES
        ):

            if voice_id == voice:
                speaker["voice_name"] = name
                break

        await speaker_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SPEAKER RATE
    # -----------------------------------------------------

    if data.startswith("sprate:"):

        speaker_number = int(
            data.split(":")[1]
        )

        await speaker_rate_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SET SPEAKER RATE
    # -----------------------------------------------------

    if data.startswith("setsprate:"):

        _, speaker_number, value = data.split(
            ":",
            2
        )

        speaker_number = int(
            speaker_number
        )

        user[
            f"speaker{speaker_number}"
        ]["rate"] = value

        await speaker_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SPEAKER PITCH
    # -----------------------------------------------------

    if data.startswith("sppitch:"):

        speaker_number = int(
            data.split(":")[1]
        )

        await speaker_pitch_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SET SPEAKER PITCH
    # -----------------------------------------------------

    if data.startswith("setsppitch:"):

        _, speaker_number, value = data.split(
            ":",
            2
        )

        speaker_number = int(
            speaker_number
        )

        user[
            f"speaker{speaker_number}"
        ]["pitch"] = value

        await speaker_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SPEAKER VOLUME
    # -----------------------------------------------------

    if data.startswith("spvolume:"):

        speaker_number = int(
            data.split(":")[1]
        )

        await speaker_volume_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # SET SPEAKER VOLUME
    # -----------------------------------------------------

    if data.startswith("setspvolume:"):

        _, speaker_number, value = data.split(
            ":",
            2
        )

        speaker_number = int(
            speaker_number
        )

        user[
            f"speaker{speaker_number}"
        ]["volume"] = value

        await speaker_menu(
            query,
            user,
            speaker_number,
        )

        return

    # -----------------------------------------------------
    # NORMAL VOICE
    # -----------------------------------------------------

    if data == "voice":

        await voice_menu(
            query,
            user,
        )

        return

    # -----------------------------------------------------
    # SET NORMAL VOICE
    # -----------------------------------------------------

    if data.startswith("setvoice:"):

        voice = data.split(
            ":",
            1
        )[1]

        user["voice"] = voice

        for voice_id, name in (
            ARABIC_VOICES + ENGLISH_VOICES
        ):

            if voice_id == voice:
                user["voice_name"] = name
                break

        await query.edit_message_text(
            f"✅ تم اختيار الصوت:\n"
            f"{user['voice_name']}",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # LANGUAGE
    # -----------------------------------------------------

    if data == "language":

        await language_menu(
            query,
            user,
        )

        return

    if data.startswith("lang:"):

        language = data.split(
            ":",
            1
        )[1]

        user["language"] = language

        if language == "ar":

            user["voice"] = "ar-EG-ShakirNeural"
            user["voice_name"] = "شاكر 🇪🇬"

        elif language == "en":

            user["voice"] = "en-US-GuyNeural"
            user["voice_name"] = "Guy 🇺🇸"

        await query.edit_message_text(
            f"🌐 تم اختيار اللغة: {language}",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # NORMAL RATE
    # -----------------------------------------------------

    if data == "rate":

        await rate_menu(
            query,
            user,
        )

        return

    if data.startswith("ratevalue:"):

        value = data.split(
            ":",
            1
        )[1]

        user["rate"] = value

        await query.edit_message_text(
            f"⚡ السرعة: {value}",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # NORMAL PITCH
    # -----------------------------------------------------

    if data == "pitch":

        await pitch_menu(
            query,
            user,
        )

        return

    if data.startswith("pitchvalue:"):

        value = data.split(
            ":",
            1
        )[1]

        user["pitch"] = value

        await query.edit_message_text(
            f"↕️ النبرة: {value}",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # NORMAL VOLUME
    # -----------------------------------------------------

    if data == "volume":

        await volume_menu(
            query,
            user,
        )

        return

    if data.startswith("volumevalue:"):

        value = data.split(
            ":",
            1
        )[1]

        user["volume"] = value

        await query.edit_message_text(
            f"🔊 مستوى الصوت: {value}",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # GENERATE
    # -----------------------------------------------------

    if data == "generate":

        if user["busy"]:

            await query.message.reply_text(
                "⏳ هناك عملية قيد التنفيذ بالفعل."
            )

            return

        user["busy"] = True

        try:

            if user["mode"] == "podcast":

                await generate_podcast(
                    update,
                    context,
                    user,
                )

            else:

                await generate_audio(
                    update,
                    context,
                    user,
                )

        finally:

            user["busy"] = False

        return

    # -----------------------------------------------------
    # CLEAR PODCAST
    # -----------------------------------------------------

    if data == "clear_podcast":

        user["podcast_text"] = ""

        await query.edit_message_text(
            "🗑 تم مسح حوار البودكاست.",
            reply_markup=main_keyboard(),
        )

        return

    # -----------------------------------------------------
    # BACK
    # -----------------------------------------------------

    if data == "back":

        await query.edit_message_text(
            "🏠 القائمة الرئيسية",
            reply_markup=main_keyboard(),
        )

        return


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Unhandled exception",
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN غير موجود في Environment Variables."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
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
            receive_text,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Bot started successfully."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
