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
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

AUDIO_DIR = BASE_DIR / "generated_audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# GENERAL SETTINGS
# ============================================================

MAX_CHARS = 2500

DEFAULT_RATE = "+0%"
DEFAULT_PITCH = "+0Hz"
DEFAULT_VOLUME = "+0%"

MIN_RATE = -50
MAX_RATE = 100

MIN_PITCH = -20
MAX_PITCH = 20

MIN_VOLUME = -50
MAX_VOLUME = 50


# ============================================================
# PODCAST PAUSES
# ============================================================

PAUSE_DURATIONS = {
    "SHORT": 350,
    "MEDIUM": 700,
    "LONG": 1200,
}

PAUSE_PATTERN = re.compile(
    r"\[PAUSE\s*:\s*(SHORT|MEDIUM|LONG)\s*\]",
    re.IGNORECASE,
)


# ============================================================
# VOICES
# ============================================================

ARABIC_VOICES = {
    "Shakir": "ar-EG-ShakirNeural",
    "Salma": "ar-EG-SalmaNeural",
}

ENGLISH_VOICES = {
    "Guy": "en-US-GuyNeural",
    "Ava": "en-US-AvaNeural",
}


# ============================================================
# USER STATE
# ============================================================

USERS = {}


def default_speaker():
    return {
        "voice": "ar-EG-ShakirNeural",
        "rate": DEFAULT_RATE,
        "pitch": DEFAULT_PITCH,
        "volume": DEFAULT_VOLUME,
    }


def default_user():
    return {
        # ----------------------------------------------------
        # GENERAL TTS MODE
        # ----------------------------------------------------

        "mode": "normal",

        "text": "",

        "language": "ar",

        "voice": "ar-EG-ShakirNeural",

        "rate": DEFAULT_RATE,

        "pitch": DEFAULT_PITCH,

        "volume": DEFAULT_VOLUME,

        # ----------------------------------------------------
        # PODCAST MODE
        # ----------------------------------------------------

        "podcast_text": "",

        "speaker1": default_speaker(),

        "speaker2": default_speaker(),

        "editing_speaker": 1,

        # ----------------------------------------------------
        # PROCESS STATE
        # ----------------------------------------------------

        "busy": False,

        "cancel_requested": False,
    }


def get_user(user_id):
    if user_id not in USERS:
        USERS[user_id] = default_user()

    return USERS[user_id]


# ============================================================
# LANGUAGE DETECTION
# ============================================================

def detect_language(text):
    """
    Simple Arabic detection.
    """

    if not text:
        return "ar"

    arabic_chars = len(
        re.findall(r"[\u0600-\u06FF]", text)
    )

    latin_chars = len(
        re.findall(r"[A-Za-z]", text)
    )

    if arabic_chars >= latin_chars:
        return "ar"

    return "en"


# ============================================================
# AUTO VOICE
# ============================================================

def choose_auto_voice(language):
    if language == "ar":
        return "ar-EG-ShakirNeural"

    return "en-US-GuyNeural"


# ============================================================
# FILE NAME
# ============================================================

def safe_filename(name):
    name = re.sub(r"[^\w\-. ]+", "_", name)
    name = name.strip()

    if not name:
        name = "audio"

    return name[:100]


def unique_audio_path(prefix="audio"):
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    return AUDIO_DIR / f"{safe_filename(prefix)}_{timestamp}.mp3"


# ============================================================
# TEXT SPLITTER
# ============================================================

def split_text(text, max_chars=MAX_CHARS):
    """
    Split long text while trying to preserve paragraphs
    and sentences.
    """

    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    chunks = []

    paragraphs = re.split(r"\n\s*\n", text)

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue

        sentences = re.split(
            r"(?<=[.!؟?؛])\s+",
            paragraph
        )

        current = ""

        for sentence in sentences:

            sentence = sentence.strip()

            if not sentence:
                continue

            if not current:
                current = sentence

            elif len(current) + len(sentence) + 1 <= max_chars:
                current += " " + sentence

            else:
                chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)

    # Emergency hard split
    final_chunks = []

    for chunk in chunks:

        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
            continue

        start = 0

        while start < len(chunk):
            final_chunks.append(
                chunk[start:start + max_chars]
            )
            start += max_chars

    return final_chunks


# ============================================================
# PAUSE PARSER
# ============================================================

def parse_pause_tokens(text):
    """
    Returns ordered parts:

    ("text", "...")
    ("pause", milliseconds)
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

        duration = PAUSE_DURATIONS.get(
            pause_type,
            PAUSE_DURATIONS["SHORT"],
        )

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
    return PAUSE_PATTERN.sub("", text).strip()


# ============================================================
# EDGE TTS
# ============================================================

async def synthesize_to_file(
    text,
    output_path,
    voice,
    rate=DEFAULT_RATE,
    pitch=DEFAULT_PITCH,
    volume=DEFAULT_VOLUME,
):
    """
    Generate one Edge TTS audio file.
    """

    text = text.strip()

    if not text:
        return False

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )

    await communicate.save(str(output_path))

    return True


# ============================================================
# SILENCE AUDIO
# ============================================================

def create_silence_mp3(
    output_path,
    duration_ms,
    sample_rate=24000,
):
    """
    Create a real silent MP3 using PyAV.
    """

    duration_seconds = duration_ms / 1000.0

    total_samples = int(
        sample_rate * duration_seconds
    )

    container = av.open(
        str(output_path),
        mode="w",
        format="mp3",
    )

    stream = container.add_stream(
        "libmp3lame",
        rate=sample_rate,
    )

    stream.layout = "mono"

    frame_size = 1024

    generated = 0

    try:

        while generated < total_samples:

            count = min(
                frame_size,
                total_samples - generated,
            )

            frame = av.AudioFrame(
                format="s16",
                layout="mono",
                samples=count,
            )

            frame.sample_rate = sample_rate

            # Silence = zero PCM samples
            for plane in frame.planes:
                plane.update(
                    b"\x00" * plane.buffer_size
                )

            frame.pts = generated
            frame.time_base = av.Rational(
                1,
                sample_rate,
            )

            for packet in stream.encode(frame):
                container.mux(packet)

            generated += count

        for packet in stream.encode(None):
            container.mux(packet)

    finally:
        container.close()

    return output_path


# ============================================================
# AUDIO MERGER
# ============================================================

def merge_audio_files(
    input_files,
    output_file,
    target_rate=24000,
):
    """
    Merge MP3/WAV files using PyAV.

    No external FFmpeg executable is required.
    """

    if not input_files:
        raise ValueError("No audio files to merge.")

    output_container = av.open(
        str(output_file),
        mode="w",
        format="mp3",
    )

    output_stream = output_container.add_stream(
        "libmp3lame",
        rate=target_rate,
    )

    output_stream.layout = "mono"

    resampler = AudioResampler(
        format="s16",
        layout="mono",
        rate=target_rate,
    )

    try:

        for input_file in input_files:

            input_container = av.open(
                str(input_file)
            )

            try:

                input_stream = input_container.streams.audio[0]

                for frame in input_container.decode(
                    input_stream
                ):

                    try:
                        converted = resampler.resample(
                            frame
                        )
                    except Exception:
                        converted = []

                    if converted is None:
                        continue

                    if not isinstance(
                        converted,
                        list,
                    ):
                        converted = [converted]

                    for converted_frame in converted:

                        for packet in output_stream.encode(
                            converted_frame
                        ):
                            output_container.mux(
                                packet
                            )

            finally:
                input_container.close()

        # Flush resampler
        try:

            flushed = resampler.resample(None)

            if flushed is not None:

                if not isinstance(
                    flushed,
                    list,
                ):
                    flushed = [flushed]

                for frame in flushed:

                    for packet in output_stream.encode(
                        frame
                    ):
                        output_container.mux(
                            packet
                        )

        except Exception:
            pass

        # Flush encoder
        for packet in output_stream.encode(None):
            output_container.mux(packet)

    finally:
        output_container.close()

    return output_file


# ============================================================
# GENERAL TTS GENERATION
# ============================================================

async def generate_normal_audio(
    user_id,
):
    user = get_user(user_id)

    text = user["text"].strip()

    if not text:
        raise ValueError(
            "لم يتم إدخال أي نص."
        )

    chunks = split_text(text)

    if not chunks:
        raise ValueError(
            "النص فارغ."
        )

    user["busy"] = True
    user["cancel_requested"] = False

    generated_files = []

    try:

        for index, chunk in enumerate(chunks, start=1):

            if user["cancel_requested"]:
                raise asyncio.CancelledError()

            output_path = unique_audio_path(
                f"tts_{user_id}_{index}"
            )

            success = False

            last_error = None

            # Retry
            for attempt in range(3):

                if user["cancel_requested"]:
                    raise asyncio.CancelledError()

                try:

                    await synthesize_to_file(
                        text=chunk,
                        output_path=output_path,
                        voice=user["voice"],
                        rate=user["rate"],
                        pitch=user["pitch"],
                        volume=user["volume"],
                    )

                    success = True
                    break

                except Exception as exc:
                    last_error = exc

                    logger.exception(
                        "TTS attempt failed"
                    )

                    await asyncio.sleep(
                        1 + attempt
                    )

            if not success:

                raise RuntimeError(
                    f"فشل توليد الجزء {index}: "
                    f"{last_error}"
                )

            generated_files.append(
                output_path
            )

        final_path = unique_audio_path(
            f"tts_final_{user_id}"
        )

        if len(generated_files) == 1:

            # Keep generated file and also use it
            # as final result.
            final_path = generated_files[0]

        else:

            merge_audio_files(
                generated_files,
                final_path,
            )

        return final_path

    finally:

        user["busy"] = False


# ============================================================
# PODCAST GENERATION
# ============================================================

async def generate_podcast_audio(
    user_id,
):
    user = get_user(user_id)

    podcast_text = user["podcast_text"].strip()

    if not podcast_text:
        raise ValueError(
            "لم يتم إدخال حوار البودكاست."
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # Each line = one speaker turn.
    # Odd lines -> Speaker 1
    # Even lines -> Speaker 2
    # --------------------------------------------------------

    lines = [
        line.strip()
        for line in podcast_text.splitlines()
        if line.strip()
    ]

    if not lines:
        raise ValueError(
            "لم يتم العثور على أسطر في الحوار."
        )

    user["busy"] = True
    user["cancel_requested"] = False

    generated_files = []

    try:

        for line_index, line in enumerate(
            lines,
            start=1,
        ):

            if user["cancel_requested"]:
                raise asyncio.CancelledError()

            # ------------------------------------------------
            # STRICT ALTERNATION
            # ------------------------------------------------

            speaker_number = (
                1
                if line_index % 2 == 1
                else 2
            )

            speaker = user[
                f"speaker{speaker_number}"
            ]

            # ------------------------------------------------
            # Parse pauses
            # ------------------------------------------------

            parts = parse_pause_tokens(line)

            if not parts:
                continue

            part_index = 0

            for part_type, value in parts:

                if user["cancel_requested"]:
                    raise asyncio.CancelledError()

                part_index += 1

                # --------------------------------------------
                # REAL SILENCE
                # --------------------------------------------

                if part_type == "pause":

                    silence_path = unique_audio_path(
                        f"podcast_s{speaker_number}_pause"
                    )

                    create_silence_mp3(
                        silence_path,
                        value,
                    )

                    generated_files.append(
                        silence_path
                    )

                    continue

                # --------------------------------------------
                # TEXT
                # --------------------------------------------

                text_part = value.strip()

                if not text_part:
                    continue

                # Remove any technical tokens
                text_part = remove_pause_tokens(
                    text_part
                )

                if not text_part:
                    continue

                # ------------------------------------------------
                # Important:
                # A long line can be internally split,
                # but ALL chunks remain same speaker.
                # ------------------------------------------------

                chunks = split_text(
                    text_part,
                    MAX_CHARS,
                )

                for chunk_index, chunk in enumerate(
                    chunks,
                    start=1,
                ):

                    if user["cancel_requested"]:
                        raise asyncio.CancelledError()

                    output_path = unique_audio_path(
                        f"podcast_s{speaker_number}_"
                        f"l{line_index}_"
                        f"p{part_index}_"
                        f"c{chunk_index}"
                    )

                    success = False
                    last_error = None

                    # Retry each TTS segment
                    for attempt in range(3):

                        if user["cancel_requested"]:
                            raise asyncio.CancelledError()

                        try:

                            await synthesize_to_file(
                                text=chunk,
                                output_path=output_path,
                                voice=speaker["voice"],
                                rate=speaker["rate"],
                                pitch=speaker["pitch"],
                                volume=speaker["volume"],
                            )

                            success = True
                            break

                        except Exception as exc:

                            last_error = exc

                            logger.exception(
                                "Podcast TTS attempt failed"
                            )

                            await asyncio.sleep(
                                1 + attempt
                            )

                    if not success:

                        raise RuntimeError(
                            "فشل توليد جزء البودكاست: "
                            f"{last_error}"
                        )

                    generated_files.append(
                        output_path
                    )

        if not generated_files:
            raise ValueError(
                "لم يتم إنشاء أي مقطع صوتي."
            )

        # ----------------------------------------------------
        # FINAL MERGE
        # ----------------------------------------------------

        final_path = unique_audio_path(
            f"podcast_final_{user_id}"
        )

        merge_audio_files(
            generated_files,
            final_path,
        )

        return final_path

    finally:

        user["busy"] = False


# ============================================================
# START COMMAND
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    get_user(user_id)

    keyboard = [
        [
            InlineKeyboardButton(
                "🔊 تحويل النص إلى صوت",
                callback_data="mode_normal",
            )
        ],
        [
            InlineKeyboardButton(
                "🎧 البودكاست",
                callback_data="mode_podcast",
            )
        ],
    ]

    await update.message.reply_text(
        "مرحبًا بك 🎙️\n\n"
        "اختر الوضع الذي تريد استخدامه:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# MAIN MENU
# ============================================================

def main_menu_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔊 تحويل النص لصوت",
                    callback_data="mode_normal",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎧 البودكاست",
                    callback_data="mode_podcast",
                )
            ],
        ]
    )


# ============================================================
# NORMAL TTS MENU
# ============================================================

def normal_menu_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🌐 اللغة",
                    callback_data="normal_language",
                ),
                InlineKeyboardButton(
                    "🎙️ الصوت",
                    callback_data="normal_voice",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⚡ السرعة",
                    callback_data="normal_rate",
                ),
                InlineKeyboardButton(
                    "↕️ النبرة",
                    callback_data="normal_pitch",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔊 مستوى الصوت",
                    callback_data="normal_volume",
                ),
            ],
            [
                InlineKeyboardButton(
                    "▶️ إنشاء الصوت",
                    callback_data="normal_generate",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🛑 إيقاف",
                    callback_data="stop",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 القائمة الرئيسية",
                    callback_data="main_menu",
                )
            ],
        ]
    )


# ============================================================
# PODCAST MENU
# ============================================================

def podcast_menu_keyboard():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👤 المتحدث 1",
                    callback_data="podcast_speaker_1",
                ),
                InlineKeyboardButton(
                    "👤 المتحدث 2",
                    callback_data="podcast_speaker_2",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎙️ إعدادات المتحدث 1",
                    callback_data="podcast_settings_1",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎙️ إعدادات المتحدث 2",
                    callback_data="podcast_settings_2",
                )
            ],
            [
                InlineKeyboardButton(
                    "▶️ إنشاء البودكاست",
                    callback_data="podcast_generate",
                )
            ],
            [
                InlineKeyboardButton(
                    "🛑 إيقاف",
                    callback_data="stop",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 القائمة الرئيسية",
                    callback_data="main_menu",
                )
            ],
        ]
    )


# ============================================================
# NORMAL LANGUAGE
# ============================================================

async def show_normal_language(
    query,
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🇪🇬 العربية",
                callback_data="normal_lang_ar",
            )
        ],
        [
            InlineKeyboardButton(
                "🇺🇸 English",
                callback_data="normal_lang_en",
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Auto Sync",
                callback_data="normal_lang_auto",
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="normal_menu",
            )
        ],
    ]

    await query.edit_message_text(
        "🌐 اختر اللغة:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# NORMAL VOICES
# ============================================================

async def show_normal_voices(
    query,
    language,
):

    if language == "ar":
        voices = ARABIC_VOICES
    else:
        voices = ENGLISH_VOICES

    keyboard = []

    for name, voice_id in voices.items():

        keyboard.append(
            [
                InlineKeyboardButton(
                    name,
                    callback_data=f"normal_voice_set|{voice_id}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="normal_menu",
            )
        ]
    )

    await query.edit_message_text(
        "🎙️ اختر الصوت:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# RATE MENU
# ============================================================

async def show_rate_menu(
    query,
    prefix,
    current_rate,
):

    rates = [
        ("🐢 -25%", "-25%"),
        ("🐢 -10%", "-10%"),
        ("▶️ 0%", "+0%"),
        ("⚡ +10%", "+10%"),
        ("⚡ +25%", "+25%"),
        ("🚀 +50%", "+50%"),
    ]

    keyboard = []

    for label, value in rates:

        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{prefix}_set|{value}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data=(
                    "normal_menu"
                    if prefix == "normal_rate"
                    else "podcast_settings_back"
                ),
            )
        ]
    )

    await query.edit_message_text(
        f"⚡ السرعة الحالية: {current_rate}\n\n"
        "اختر السرعة:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# PITCH MENU
# ============================================================

async def show_pitch_menu(
    query,
    prefix,
    current_pitch,
):

    values = [
        ("🔽 منخفضة -10Hz", "-10Hz"),
        ("🔽 منخفضة -5Hz", "-5Hz"),
        ("↕️ طبيعية 0Hz", "+0Hz"),
        ("🔼 مرتفعة +5Hz", "+5Hz"),
        ("🔼 مرتفعة +10Hz", "+10Hz"),
    ]

    keyboard = []

    for label, value in values:

        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{prefix}_set|{value}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data=(
                    "normal_menu"
                    if prefix == "normal_pitch"
                    else "podcast_settings_back"
                ),
            )
        ]
    )

    await query.edit_message_text(
        f"↕️ النبرة الحالية: {current_pitch}\n\n"
        "اختر النبرة:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# VOLUME MENU
# ============================================================

async def show_volume_menu(
    query,
    prefix,
    current_volume,
):

    values = [
        ("🔉 -25%", "-25%"),
        ("🔉 -10%", "-10%"),
        ("🔊 0%", "+0%"),
        ("🔊 +10%", "+10%"),
        ("🔊 +25%", "+25%"),
    ]

    keyboard = []

    for label, value in values:

        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{prefix}_set|{value}",
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data=(
                    "normal_menu"
                    if prefix == "normal_volume"
                    else "podcast_settings_back"
                ),
            )
        ]
    )

    await query.edit_message_text(
        f"🔊 مستوى الصوت الحالي: {current_volume}\n\n"
        "اختر المستوى:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# PODCAST SPEAKER SETTINGS
# ============================================================

async def show_podcast_speaker_settings(
    query,
    user,
    speaker_number,
):

    speaker = user[
        f"speaker{speaker_number}"
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                "🎙️ الصوت",
                callback_data=(
                    f"podcast_voice_{speaker_number}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "⚡ السرعة",
                callback_data=(
                    f"podcast_rate_{speaker_number}"
                ),
            ),
            InlineKeyboardButton(
                "↕️ النبرة",
                callback_data=(
                    f"podcast_pitch_{speaker_number}"
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                "🔊 مستوى الصوت",
                callback_data=(
                    f"podcast_volume_{speaker_number}"
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="podcast_menu",
            )
        ],
    ]

    await query.edit_message_text(
        f"🎧 إعدادات المتحدث {speaker_number}\n\n"
        f"🎙️ الصوت: {speaker['voice']}\n"
        f"⚡ السرعة: {speaker['rate']}\n"
        f"↕️ النبرة: {speaker['pitch']}\n"
        f"🔊 الصوت: {speaker['volume']}",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    user = get_user(user_id)

    data = query.data

    # ========================================================
    # MAIN MENU
    # ========================================================

    if data == "main_menu":

        await query.edit_message_text(
            "اختر الوضع:",
            reply_markup=main_menu_keyboard(),
        )

        return

    # ========================================================
    # NORMAL MODE
    # ========================================================

    if data == "mode_normal":

        user["mode"] = "normal"

        await query.edit_message_text(
            "🔊 وضع تحويل النص إلى صوت\n\n"
            "أرسل النص الذي تريد تحويله، "
            "ثم اضبط الإعدادات من القائمة.",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_menu":

        await query.edit_message_text(
            "🔊 إعدادات تحويل النص إلى صوت",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_language":

        await show_normal_language(query)

        return

    if data == "normal_lang_ar":

        user["language"] = "ar"
        user["voice"] = choose_auto_voice("ar")

        await query.edit_message_text(
            "🇪🇬 تم اختيار العربية.",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_lang_en":

        user["language"] = "en"
        user["voice"] = choose_auto_voice("en")

        await query.edit_message_text(
            "🇺🇸 English selected.",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_lang_auto":

        user["language"] = "auto"

        detected = detect_language(
            user.get("text", "")
        )

        user["voice"] = choose_auto_voice(
            detected
        )

        await query.edit_message_text(
            f"🔄 Auto Sync\n\n"
            f"تم اكتشاف اللغة: "
            f"{'العربية' if detected == 'ar' else 'English'}",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_voice":

        language = user["language"]

        if language == "auto":
            language = detect_language(
                user.get("text", "")
            )

        await show_normal_voices(
            query,
            language,
        )

        return

    if data.startswith("normal_voice_set|"):

        voice = data.split("|", 1)[1]

        user["voice"] = voice

        await query.edit_message_text(
            f"🎙️ تم اختيار الصوت:\n{voice}",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_rate":

        await show_rate_menu(
            query,
            "normal_rate",
            user["rate"],
        )

        return

    if data.startswith("normal_rate_set|"):

        value = data.split("|", 1)[1]

        user["rate"] = value

        await query.edit_message_text(
            f"⚡ تم ضبط السرعة: {value}",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_pitch":

        await show_pitch_menu(
            query,
            "normal_pitch",
            user["pitch"],
        )

        return

    if data.startswith("normal_pitch_set|"):

        value = data.split("|", 1)[1]

        user["pitch"] = value

        await query.edit_message_text(
            f"↕️ تم ضبط النبرة: {value}",
            reply_markup=normal_menu_keyboard(),
        )

        return

    if data == "normal_volume":

        await show_volume_menu(
            query,
            "normal_volume",
            user["volume"],
        )

        return

    if data.startswith("normal_volume_set|"):

        value = data.split("|", 1)[1]

        user["volume"] = value

        await query.edit_message_text(
            f"🔊 تم ضبط مستوى الصوت: {value}",
            reply_markup=normal_menu_keyboard(),
        )

        return

    # ========================================================
    # PODCAST MODE
    # ========================================================

    if data == "mode_podcast":

        user["mode"] = "podcast"

        await query.edit_message_text(
            "🎧 وضع البودكاست\n\n"
            "أرسل الحوار على شكل أسطر.\n\n"
            "السطر الأول = المتحدث 1\n"
            "السطر الثاني = المتحدث 2\n"
            "السطر الثالث = المتحدث 1\n"
            "وهكذا بالتناوب.\n\n"
            "يمكن استخدام:\n"
            "[PAUSE:SHORT]\n"
            "[PAUSE:MEDIUM]\n"
            "[PAUSE:LONG]",
            reply_markup=podcast_menu_keyboard(),
        )

        return

    if data == "podcast_menu":

        await query.edit_message_text(
            "🎧 إعدادات البودكاست",
            reply_markup=podcast_menu_keyboard(),
        )

        return

    if data in (
        "podcast_speaker_1",
        "podcast_speaker_2",
    ):

        speaker_number = int(
            data.split("_")[-1]
        )

        user["editing_speaker"] = speaker_number

        await show_podcast_speaker_settings(
            query,
            user,
            speaker_number,
        )

        return

    if data.startswith(
        "podcast_settings_"
    ):

        speaker_number = int(
            data.split("_")[-1]
        )

        user["editing_speaker"] = speaker_number

        await show_podcast_speaker_settings(
            query,
            user,
            speaker_number,
        )

        return

    # ========================================================
    # PODCAST VOICE
    # ========================================================

    match = re.match(
        r"podcast_voice_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        keyboard = [
            [
                InlineKeyboardButton(
                    "Shakir",
                    callback_data=(
                        f"podcast_voice_set|"
                        f"{speaker_number}|"
                        f"ar-EG-ShakirNeural"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "Salma",
                    callback_data=(
                        f"podcast_voice_set|"
                        f"{speaker_number}|"
                        f"ar-EG-SalmaNeural"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "Guy English",
                    callback_data=(
                        f"podcast_voice_set|"
                        f"{speaker_number}|"
                        f"en-US-GuyNeural"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "Ava English",
                    callback_data=(
                        f"podcast_voice_set|"
                        f"{speaker_number}|"
                        f"en-US-AvaNeural"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data=(
                        f"podcast_settings_"
                        f"{speaker_number}"
                    ),
                )
            ],
        ]

        await query.edit_message_text(
            f"🎙️ صوت المتحدث {speaker_number}:",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            ),
        )

        return

    if data.startswith(
        "podcast_voice_set|"
    ):

        _, speaker_number, voice = data.split(
            "|",
            2,
        )

        speaker_number = int(
            speaker_number
        )

        user[
            f"speaker{speaker_number}"
        ]["voice"] = voice

        await show_podcast_speaker_settings(
            query,
            user,
            speaker_number,
        )

        return

    # ========================================================
    # PODCAST RATE
    # ========================================================

    match = re.match(
        r"podcast_rate_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await show_rate_menu(
            query,
            f"podcast_rate_{speaker_number}",
            user[
                f"speaker{speaker_number}"
            ]["rate"],
        )

        return

    if data.startswith(
        "podcast_rate_"
    ) and "_set|" in data:

        prefix, value = data.split(
            "|",
            1,
        )

        speaker_number = int(
            prefix.split("_")[-2]
        )

        user[
            f"speaker{speaker_number}"
        ]["rate"] = value

        await show_podcast_speaker_settings(
            query,
            user,
            speaker_number,
        )

        return

    # ========================================================
    # PODCAST PITCH
    # ========================================================

    match = re.match(
        r"podcast_pitch_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await show_pitch_menu(
            query,
            f"podcast_pitch_{speaker_number}",
            user[
                f"speaker{speaker_number}"
            ]["pitch"],
        )

        return

    if data.startswith(
        "podcast_pitch_"
    ) and "_set|" in data:

        prefix, value = data.split(
            "|",
            1,
        )

        speaker_number = int(
            prefix.split("_")[-2]
        )

        user[
            f"speaker{speaker_number}"
        ]["pitch"] = value

        await show_podcast_speaker_settings(
            query,
            user,
            speaker_number,
        )

        return

    # ========================================================
    # PODCAST VOLUME
    # ========================================================

    match = re.match(
        r"podcast_volume_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await show_volume_menu(
            query,
            f"podcast_volume_{speaker_number}",
            user[
                f"speaker{speaker_number}"
            ]["volume"],
        )

        return

    if data.startswith(
        "podcast_volume_"
    ) and "_set|" in data:

        prefix, value = data.split(
            "|",
            1,
        )

        speaker_number = int(
            prefix.split("_")[-2]
        )

        user[
            f"speaker{speaker_number}"
        ]["volume"] = value

        await show_podcast_speaker_settings(
            query,
            user,
            speaker_number,
        )

        return

    # ========================================================
    # NORMAL GENERATE
    # ========================================================

    if data == "normal_generate":

        if user["busy"]:

            await query.message.reply_text(
                "⏳ هناك عملية جارية بالفعل."
            )

            return

        if not user["text"].strip():

            await query.message.reply_text(
                "⚠️ أرسل النص أولًا."
            )

            return

        await query.message.reply_text(
            "⏳ جاري تحويل النص إلى صوت...\n"
            "قد يستغرق الأمر بعض الوقت حسب طول النص."
        )

        try:

            path = await generate_normal_audio(
                user_id
            )

            with open(
                path,
                "rb",
            ) as audio_file:

                await query.message.reply_audio(
                    audio=audio_file,
                    caption="🔊 تم إنشاء الصوت بنجاح.",
                )

        except asyncio.CancelledError:

            await query.message.reply_text(
                "🛑 تم إيقاف العملية."
            )

        except Exception as exc:

            logger.exception(
                "Normal TTS generation failed"
            )

            await query.message.reply_text(
                f"❌ حدث خطأ أثناء إنشاء الصوت:\n"
                f"{exc}"
            )

        return

    # ========================================================
    # PODCAST GENERATE
    # ========================================================

    if data == "podcast_generate":

        if user["busy"]:

            await query.message.reply_text(
                "⏳ هناك عملية بودكاست جارية بالفعل."
            )

            return

        if not user["podcast_text"].strip():

            await query.message.reply_text(
                "⚠️ أرسل حوار البودكاست أولًا."
            )

            return

        await query.message.reply_text(
            "🎧 جاري إنشاء البودكاست...\n\n"
            "يتم الآن:\n"
            "• توليد صوت كل متحدث\n"
            "• معالجة السكتات\n"
            "• الحفاظ على ترتيب الحوار\n"
            "• دمج كل شيء في MP3 واحد"
        )

        try:

            path = await generate_podcast_audio(
                user_id
            )

            with open(
                path,
                "rb",
            ) as audio_file:

                await query.message.reply_audio(
                    audio=audio_file,
                    caption="🎧 تم إنشاء البودكاست بنجاح.",
                )

        except asyncio.CancelledError:

            await query.message.reply_text(
                "🛑 تم إيقاف إنشاء البودكاست."
            )

        except Exception as exc:

            logger.exception(
                "Podcast generation failed"
            )

            await query.message.reply_text(
                f"❌ حدث خطأ أثناء إنشاء البودكاست:\n"
                f"{exc}"
            )

        return

    # ========================================================
    # STOP
    # ========================================================

    if data == "stop":

        if user["busy"]:

            user["cancel_requested"] = True

            await query.message.reply_text(
                "🛑 تم طلب إيقاف العملية."
            )

        else:

            await query.message.reply_text(
                "لا توجد عملية تعمل حاليًا."
            )

        return


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    user = get_user(user_id)

    text = update.message.text.strip()

    if not text:
        return

    # ========================================================
    # NORMAL MODE
    # ========================================================

    if user["mode"] == "normal":

        user["text"] = text

        # Auto Sync
        if user["language"] == "auto":

            detected = detect_language(
                text
            )

            user["voice"] = choose_auto_voice(
                detected
            )

            detected_name = (
                "العربية"
                if detected == "ar"
                else "English"
            )

            await update.message.reply_text(
                f"📝 تم حفظ النص.\n\n"
                f"🔄 اللغة المكتشفة: {detected_name}\n"
                f"🎙️ الصوت: {user['voice']}\n\n"
                f"عدد الأحرف: {len(text)}",
                reply_markup=normal_menu_keyboard(),
            )

        else:

            await update.message.reply_text(
                f"📝 تم حفظ النص.\n\n"
                f"عدد الأحرف: {len(text)}",
                reply_markup=normal_menu_keyboard(),
            )

        return

    # ========================================================
    # PODCAST MODE
    # ========================================================

    if user["mode"] == "podcast":

        user["podcast_text"] = text

        lines = [
            line
            for line in text.splitlines()
            if line.strip()
        ]

        await update.message.reply_text(
            "🎧 تم حفظ حوار البودكاست.\n\n"
            f"عدد الأسطر: {len(lines)}\n"
            f"عدد الأحرف: {len(text)}\n\n"
            "التناوب:\n"
            "السطر 1 → المتحدث 1\n"
            "السطر 2 → المتحدث 2\n"
            "السطر 3 → المتحدث 1\n"
            "السطر 4 → المتحدث 2\n\n"
            "والسكتات المدعومة:\n"
            "[PAUSE:SHORT]\n"
            "[PAUSE:MEDIUM]\n"
            "[PAUSE:LONG]",
            reply_markup=podcast_menu_keyboard(),
        )

        return


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context,
):

    logger.exception(
        "Unhandled exception",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    token = os.getenv(
        "BOT_TOKEN"
    )

    if not token:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    application = (
        Application.builder()
        .token(token)
        .build()
    )

    # --------------------------------------------------------
    # Handlers
    # --------------------------------------------------------

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
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "Bot started successfully."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
