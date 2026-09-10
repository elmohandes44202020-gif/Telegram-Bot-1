import os
import re
import asyncio
import logging
from pathlib import Path
from fractions import Fraction
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

BASE_DIR = Path(__file__).resolve().parent

AUDIO_DIR = BASE_DIR / "generated_audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SOURCE_DIR = BASE_DIR / "uploaded_texts"
SOURCE_DIR.mkdir(parents=True, exist_ok=True)

MAX_CHARS = 2500

# Available parallel channels
PARALLEL_OPTIONS = [1, 2, 3, 5]

DEFAULT_PARALLEL_CHANNELS = 1

# Real silence durations
PAUSE_DURATIONS = {
    "SHORT": 350,
    "MEDIUM": 700,
    "LONG": 1200,
}

DEFAULT_RATE = "+0%"
DEFAULT_VOLUME = "+0%"
DEFAULT_PITCH = "+0Hz"

# Fallback voices
DEFAULT_AR_VOICE = "ar-EG-ShakirNeural"
DEFAULT_EN_VOICE = "en-US-GuyNeural"

DEFAULT_AR_FEMALE = "ar-EG-SalmaNeural"
DEFAULT_EN_FEMALE = "en-US-AvaNeural"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# BOT TOKEN
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN غير موجود في Environment Variables."
    )


# ============================================================
# USER STATES
# ============================================================

USER_STATES = {}


def default_user_state():
    return {
        # ----------------------------------------------------
        # General mode
        # ----------------------------------------------------
        "mode": None,

        # ----------------------------------------------------
        # Parallel channels
        # ----------------------------------------------------
        "parallel_channels": DEFAULT_PARALLEL_CHANNELS,

        # ----------------------------------------------------
        # Normal TTS
        # ----------------------------------------------------
        "normal_voice_mode": "auto",

        "normal_ar_voice": DEFAULT_AR_VOICE,
        "normal_en_voice": DEFAULT_EN_VOICE,

        "normal_rate": DEFAULT_RATE,
        "normal_pitch": DEFAULT_PITCH,
        "normal_volume": DEFAULT_VOLUME,

        # ----------------------------------------------------
        # Podcast speaker 1
        # ----------------------------------------------------
        "podcast_speaker1": {
            "voice_mode": "auto",

            "ar_voice": DEFAULT_AR_VOICE,
            "en_voice": DEFAULT_EN_VOICE,

            "rate": DEFAULT_RATE,
            "pitch": DEFAULT_PITCH,
            "volume": DEFAULT_VOLUME,
        },

        # ----------------------------------------------------
        # Podcast speaker 2
        # ----------------------------------------------------
        "podcast_speaker2": {
            "voice_mode": "auto",

            "ar_voice": DEFAULT_AR_FEMALE,
            "en_voice": DEFAULT_EN_FEMALE,

            "rate": DEFAULT_RATE,
            "pitch": DEFAULT_PITCH,
            "volume": DEFAULT_VOLUME,
        },

        # ----------------------------------------------------
        # Runtime
        # ----------------------------------------------------
        "cancel_event": None,

        # ----------------------------------------------------
        # Voice cache
        # ----------------------------------------------------
        "voices_loaded": False,
        "arabic_voices": [],
        "english_voices": [],
    }


def get_state(user_id):
    if user_id not in USER_STATES:
        USER_STATES[user_id] = default_user_state()

    return USER_STATES[user_id]


# ============================================================
# AI PODCAST MASTER PROMPT
# ============================================================

PODCAST_AI_PROMPT = r"""
أنت كاتب حوارات بودكاست احترافي، ومهمتك تحويل الموضوع أو المصدر الذي يقدمه المستخدم إلى حوار صوتي طبيعي جدًا بين متحدثين اثنين، بحيث يكون الناتج جاهزًا مباشرةً للتحويل إلى صوت بواسطة نظام TTS.

القواعد التالية إلزامية:

1. عدد المتحدثين اثنان فقط.

2. التناوب صارم جدًا:
   السطر الأول = المتحدث الأول.
   السطر الثاني = المتحدث الثاني.
   السطر الثالث = المتحدث الأول.
   السطر الرابع = المتحدث الثاني.
   وهكذا حتى النهاية.

3. لا تكتب أسماء المتحدثين.

4. لا تكتب:
   المتحدث الأول:
   المتحدث الثاني:
   1:
   2:
   Speaker 1
   Speaker 2
   [1]
   [2]

5. كل سطر يمثل دورًا صوتيًا كاملًا لمتحدث واحد.

6. تغيير السطر هو الطريقة الوحيدة التي تحدد انتقال الكلام من متحدث إلى الآخر.

7. علامات الترقيم لا تغيّر المتحدث.

8. إذا كانت الجملة طويلة فلا تقسّمها إلى عدة أسطر لمجرد أنها طويلة.

9. الحوار يجب أن يكون تفاعليًا وطبيعيًا.

10. يجب أن يتفاعل كل متحدث مع كلام المتحدث الآخر.

11. ممنوع أن يكون أحد المتحدثين مجرد مذيع يسأل طوال الوقت والآخر يجيب طوال الوقت.

12. كلا المتحدثين يسأل ويجيب ويشرح ويضيف ويعترض عندما يكون الاعتراض منطقيًا.

13. لا تجعل الحوار سؤالًا وجوابًا بشكل آلي متكرر.

14. اجعل الحوار يبدو وكأن شخصين حقيقيين يتحدثان.

15. استخدم انتقالات طبيعية دون تكرار آلي.

16. تجنب الردود الروبوتية المتكررة.

17. اجعل أطوال المداخلات متنوعة.

18. لا تجعل كل سطر بنفس الطول تقريبًا.

19. إذا كان المستخدم قدّم مصدرًا:
   اعتمد على المعلومات الموجودة فيه.
   لا تخترع معلومات غير موجودة إلا للربط الضروري.

20. إذا لم يقدم المستخدم مصدرًا، استخدم المعرفة العامة الموثوقة.

21. استخدم العربية الفصحى الطبيعية.

22. استخدم التشكيل العربي قدر الإمكان، وبالأخص الكلمات التي قد يخطئ نظام TTS في نطقها.

23. يمكن استخدام المصطلحات الإنجليزية عند الحاجة.

24. لا تكتب تعليمات صوتية داخل الحوار.

25. يمكنك استخدام الوقفات التالية فقط:

[PAUSE:SHORT]
[PAUSE:MEDIUM]
[PAUSE:LONG]

26. استخدم الوقفات عندما تكون مناسبة لغويًا أو دراميًا.

27. لا تستخدم الوقفات بكثرة.

28. لا تستخدم وقفتين متتاليتين.

29. لا تبدأ سطرًا بعلامة PAUSE.

30. لا تستخدم أي صيغة أخرى للوقفات.

31. لا تضع عنوانًا للحوار.

32. لا تكتب مقدمة خارج الحوار.

33. لا تكتب شرحًا بعد الحوار.

34. لا تستخدم Markdown.

35. لا تستخدم قوائم.

36. لا تستخدم أرقامًا لتحديد المتحدثين.

37. الناتج النهائي يجب أن يكون الحوار فقط.

38. قبل إخراج الإجابة راجع داخليًا:
   - المتحدثان اثنان فقط.
   - التناوب صحيح سطرًا بسطر.
   - لا توجد أسماء للمتحدثين.
   - لا توجد تعليمات خارج الحوار.
   - الوقفات بصيغتها الصحيحة فقط.
   - الحوار تفاعلي.
   - كلا المتحدثين يشاركان.
   - التشكيل مناسب لـ TTS.
   - الحوار طبيعي وغير آلي.

أخرج الحوار النهائي فقط.
"""


# ============================================================
# VOICE DISCOVERY
# ============================================================

async def load_voices(state):

    if state["voices_loaded"]:
        return

    try:

        voices = await edge_tts.list_voices()

        arabic = []
        english = []

        for voice in voices:

            short_name = voice.get(
                "ShortName",
                "",
            )

            locale = voice.get(
                "Locale",
                "",
            )

            if (
                locale.lower().startswith("ar-")
                or short_name.lower().startswith("ar-")
            ):
                arabic.append(voice)

            elif (
                locale.lower().startswith("en-")
                or short_name.lower().startswith("en-")
            ):
                english.append(voice)

        arabic.sort(
            key=lambda x: (
                x.get("Locale", ""),
                x.get("Gender", ""),
                x.get("ShortName", ""),
            )
        )

        english.sort(
            key=lambda x: (
                x.get("Locale", ""),
                x.get("Gender", ""),
                x.get("ShortName", ""),
            )
        )

        state["arabic_voices"] = arabic
        state["english_voices"] = english
        state["voices_loaded"] = True

        logger.info(
            "Loaded %s Arabic voices and %s English voices.",
            len(arabic),
            len(english),
        )

    except Exception as e:

        logger.exception(
            "Voice discovery failed: %s",
            e,
        )

        state["arabic_voices"] = [
            {
                "ShortName": DEFAULT_AR_VOICE,
                "Locale": "ar-EG",
                "Gender": "Male",
            },
            {
                "ShortName": DEFAULT_AR_FEMALE,
                "Locale": "ar-EG",
                "Gender": "Female",
            },
        ]

        state["english_voices"] = [
            {
                "ShortName": DEFAULT_EN_VOICE,
                "Locale": "en-US",
                "Gender": "Male",
            },
            {
                "ShortName": DEFAULT_EN_FEMALE,
                "Locale": "en-US",
                "Gender": "Female",
            },
        ]

        state["voices_loaded"] = True


# ============================================================
# LANGUAGE DETECTION
# ============================================================

ARABIC_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]"
)

LATIN_RE = re.compile(
    r"[A-Za-z]"
)


def detect_language(text):

    arabic_count = len(
        ARABIC_RE.findall(text)
    )

    latin_count = len(
        LATIN_RE.findall(text)
    )

    if arabic_count == 0 and latin_count == 0:
        return "ar"

    if arabic_count > latin_count * 1.15:
        return "ar"

    if latin_count > arabic_count * 1.15:
        return "en"

    return "mixed"


# ============================================================
# AUTO VOICE
# ============================================================

def choose_auto_voice(
    text,
    ar_voice,
    en_voice,
):

    lang = detect_language(text)

    if lang == "en":
        return en_voice

    if lang == "ar":
        return ar_voice

    arabic_count = len(
        ARABIC_RE.findall(text)
    )

    latin_count = len(
        LATIN_RE.findall(text)
    )

    if latin_count > arabic_count:
        return en_voice

    return ar_voice


# ============================================================
# TEXT SPLITTING
# ============================================================

def split_text(
    text,
    max_chars=MAX_CHARS,
):

    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    chunks = []

    current = ""

    paragraphs = re.split(
        r"\n+",
        text,
    )

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:
            continue

        if len(paragraph) <= max_chars:

            if (
                current
                and len(current)
                + len(paragraph)
                + 1
                > max_chars
            ):
                chunks.append(
                    current.strip()
                )

                current = paragraph

            else:

                current = (
                    current + " " + paragraph
                    if current
                    else paragraph
                )

        else:

            sentences = re.split(
                r"(?<=[.!؟؛:])\s+",
                paragraph,
            )

            for sentence in sentences:

                sentence = sentence.strip()

                if not sentence:
                    continue

                if len(sentence) <= max_chars:

                    if (
                        current
                        and len(current)
                        + len(sentence)
                        + 1
                        > max_chars
                    ):
                        chunks.append(
                            current.strip()
                        )

                        current = sentence

                    else:

                        current = (
                            current + " " + sentence
                            if current
                            else sentence
                        )

                else:

                    while len(sentence) > max_chars:

                        part = sentence[
                            :max_chars
                        ]

                        split_pos = part.rfind(
                            " "
                        )

                        if split_pos > max_chars * 0.5:
                            part = sentence[
                                :split_pos
                            ]

                        chunks.append(
                            part.strip()
                        )

                        sentence = sentence[
                            len(part):
                        ].strip()

                    if sentence:

                        if current:
                            chunks.append(
                                current.strip()
                            )

                        current = sentence

    if current:
        chunks.append(
            current.strip()
        )

    return chunks


# ============================================================
# PAUSE PARSER
# ============================================================

PAUSE_PATTERN = re.compile(
    r"\[PAUSE:(SHORT|MEDIUM|LONG)\]",
    re.IGNORECASE,
)


def parse_pause_tokens(text):

    parts = []

    last = 0

    for match in PAUSE_PATTERN.finditer(text):

        before = text[
            last:match.start()
        ]

        if before.strip():

            parts.append(
                (
                    "text",
                    before.strip(),
                )
            )

        pause_type = (
            match.group(1).upper()
        )

        parts.append(
            (
                "pause",
                pause_type,
            )
        )

        last = match.end()

    remaining = text[last:]

    if remaining.strip():

        parts.append(
            (
                "text",
                remaining.strip(),
            )
        )

    return parts


# ============================================================
# UNIQUE FILE
# ============================================================

def unique_filename(
    prefix="audio",
):

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    return (
        AUDIO_DIR
        / f"{prefix}_{timestamp}.mp3"
    )


# ============================================================
# TTS
# ============================================================

async def synthesize_to_file(
    text,
    output_path,
    voice,
    rate=DEFAULT_RATE,
    pitch=DEFAULT_PITCH,
    volume=DEFAULT_VOLUME,
    retries=3,
):

    text = text.strip()

    if not text:
        return False

    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):

        try:

            communicate = edge_tts.Communicate(
                text,
                voice,
                rate=rate,
                pitch=pitch,
                volume=volume,
            )

            await communicate.save(
                str(output_path)
            )

            if (
                output_path.exists()
                and output_path.stat().st_size > 0
            ):
                return True

        except Exception as e:

            last_error = e

            logger.warning(
                "TTS attempt %s/%s failed: %s",
                attempt,
                retries,
                e,
            )

            if attempt < retries:
                await asyncio.sleep(
                    1.5 * attempt
                )

    raise RuntimeError(
        f"فشل Edge TTS بعد {retries} محاولات: "
        f"{last_error}"
    )


# ============================================================
# PARALLEL TTS
# ============================================================

async def parallel_synthesize_jobs(
    jobs,
    parallel_channels,
    cancel_event,
):
    """
    jobs:
        [
            {
                "text": "...",
                "voice": "...",
                "rate": "...",
                "pitch": "...",
                "volume": "...",
                "output": Path(...)
            }
        ]

    The returned list preserves the exact
    order of the input jobs.
    """

    if not jobs:
        return []

    parallel_channels = int(
        parallel_channels
    )

    if parallel_channels not in PARALLEL_OPTIONS:
        parallel_channels = 1

    semaphore = asyncio.Semaphore(
        parallel_channels
    )

    async def worker(job):

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        async with semaphore:

            if cancel_event.is_set():
                raise asyncio.CancelledError()

            await synthesize_to_file(
                job["text"],
                job["output"],
                job["voice"],
                job["rate"],
                job["pitch"],
                job["volume"],
            )

            if cancel_event.is_set():
                raise asyncio.CancelledError()

            return job["output"]

    tasks = [
        asyncio.create_task(
            worker(job)
        )
        for job in jobs
    ]

    try:

        results = await asyncio.gather(
            *tasks
        )

        return results

    except Exception:

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        raise


# ============================================================
# CREATE SILENCE
# ============================================================

def create_silence_mp3(
    duration_ms,
    output_path,
    sample_rate=24000,
):

    duration_seconds = (
        duration_ms / 1000.0
    )

    samples = int(
        sample_rate * duration_seconds
    )

    if samples <= 0:
        return

    container = av.open(
        str(output_path),
        mode="w",
        format="mp3",
    )

    try:

        stream = container.add_stream(
            "libmp3lame",
            rate=sample_rate,
        )

        stream.layout = "mono"

        stream.time_base = Fraction(
            1,
            sample_rate,
        )

        frame = av.AudioFrame(
            format="s16",
            layout="mono",
            samples=samples,
        )

        frame.sample_rate = sample_rate

        frame.time_base = Fraction(
            1,
            sample_rate,
        )

        for plane in frame.planes:

            plane.update(
                bytes(
                    plane.buffer_size
                )
            )

        for packet in stream.encode(
            frame
        ):

            container.mux(packet)

        for packet in stream.encode(
            None
        ):

            container.mux(packet)

    finally:

        container.close()


# ============================================================
# MERGE AUDIO
# ============================================================

def merge_audio_files(
    input_files,
    output_file,
    target_rate=24000,
):

    if not input_files:
        raise ValueError(
            "لا توجد ملفات صوتية للدمج."
        )

    output_container = av.open(
        str(output_file),
        mode="w",
        format="mp3",
    )

    try:

        output_stream = (
            output_container.add_stream(
                "libmp3lame",
                rate=target_rate,
            )
        )

        output_stream.layout = "mono"

        output_stream.time_base = Fraction(
            1,
            target_rate,
        )

        resampler = AudioResampler(
            format="s16",
            layout="mono",
            rate=target_rate,
        )

        for input_file in input_files:

            input_container = av.open(
                str(input_file)
            )

            try:

                audio_stream = next(
                    (
                        s
                        for s
                        in input_container.streams
                        if s.type == "audio"
                    ),
                    None,
                )

                if audio_stream is None:
                    continue

                for frame in input_container.decode(
                    audio_stream
                ):

                    converted_frames = (
                        resampler.resample(
                            frame
                        )
                    )

                    if not isinstance(
                        converted_frames,
                        list,
                    ):
                        converted_frames = [
                            converted_frames
                        ]

                    for converted in converted_frames:

                        if converted is None:
                            continue

                        converted.sample_rate = (
                            target_rate
                        )

                        converted.time_base = (
                            Fraction(
                                1,
                                target_rate,
                            )
                        )

                        for packet in (
                            output_stream.encode(
                                converted
                            )
                        ):

                            output_container.mux(
                                packet
                            )

            finally:

                input_container.close()

        # Flush resampler
        try:

            flushed = (
                resampler.resample(
                    None
                )
            )

            if not isinstance(
                flushed,
                list,
            ):
                flushed = [flushed]

            for frame in flushed:

                if frame is None:
                    continue

                frame.sample_rate = (
                    target_rate
                )

                frame.time_base = Fraction(
                    1,
                    target_rate,
                )

                for packet in (
                    output_stream.encode(
                        frame
                    )
                ):

                    output_container.mux(
                        packet
                    )

        except Exception:
            pass

        # Flush encoder
        for packet in (
            output_stream.encode(
                None
            )
        ):

            output_container.mux(
                packet
            )

    finally:

        output_container.close()


# ============================================================
# NORMAL AUDIO GENERATION
# ============================================================

async def generate_normal_audio(
    state,
    text,
    cancel_event,
):

    await load_voices(state)

    parts = parse_pause_tokens(
        text
    )

    jobs = []
    ordered_items = []

    job_index = 0

    # -----------------------------------------
    # Build processing plan
    # -----------------------------------------

    for part_type, content in parts:

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        if part_type == "pause":

            pause_file = unique_filename(
                f"pause_{content.lower()}"
            )

            await asyncio.to_thread(
                create_silence_mp3,
                PAUSE_DURATIONS[content],
                pause_file,
            )

            ordered_items.append(
                pause_file
            )

            continue

        text_chunks = split_text(
            content
        )

        for chunk in text_chunks:

            if cancel_event.is_set():
                raise asyncio.CancelledError()

            job_index += 1

            if (
                state["normal_voice_mode"]
                == "auto"
            ):

                voice = choose_auto_voice(
                    chunk,
                    state[
                        "normal_ar_voice"
                    ],
                    state[
                        "normal_en_voice"
                    ],
                )

            else:

                voice = (
                    state[
                        "normal_voice_mode"
                    ]
                )

            output_file = unique_filename(
                f"normal_{job_index}"
            )

            job = {
                "text": chunk,
                "voice": voice,
                "rate": state[
                    "normal_rate"
                ],
                "pitch": state[
                    "normal_pitch"
                ],
                "volume": state[
                    "normal_volume"
                ],
                "output": output_file,
            }

            jobs.append(job)

            ordered_items.append(
                output_file
            )

    # -----------------------------------------
    # Run TTS jobs in parallel
    # -----------------------------------------

    if jobs:

        await parallel_synthesize_jobs(
            jobs,
            state["parallel_channels"],
            cancel_event,
        )

    if cancel_event.is_set():
        raise asyncio.CancelledError()

    if not ordered_items:
        raise ValueError(
            "لم يتم العثور على نص صالح للتوليد."
        )

    # -----------------------------------------
    # Merge in ORIGINAL ORDER
    # -----------------------------------------

    final_file = unique_filename(
        "tts_final"
    )

    await asyncio.to_thread(
        merge_audio_files,
        ordered_items,
        final_file,
    )

    return final_file


# ============================================================
# PODCAST AUDIO GENERATION
# ============================================================

async def generate_podcast_audio(
    state,
    dialogue,
    cancel_event,
):

    await load_voices(state)

    raw_lines = dialogue.splitlines()

    lines = []

    for line in raw_lines:

        line = line.strip()

        if not line:
            continue

        lines.append(line)

    if not lines:
        raise ValueError(
            "لم يتم العثور على حوار صالح."
        )

    jobs = []
    ordered_items = []

    global_index = 0

    # -----------------------------------------
    # Build podcast plan
    # -----------------------------------------

    for line_number, line in enumerate(
        lines,
        start=1,
    ):

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        # Strict alternating speaker
        speaker_number = (
            1
            if line_number % 2 == 1
            else 2
        )

        speaker = state[
            "podcast_speaker1"
            if speaker_number == 1
            else "podcast_speaker2"
        ]

        parts = parse_pause_tokens(
            line
        )

        for part_type, content in parts:

            if cancel_event.is_set():
                raise asyncio.CancelledError()

            # ---------------------------------
            # Real pause
            # ---------------------------------

            if part_type == "pause":

                global_index += 1

                pause_file = unique_filename(
                    f"podcast_pause_{global_index}"
                )

                await asyncio.to_thread(
                    create_silence_mp3,
                    PAUSE_DURATIONS[content],
                    pause_file,
                )

                ordered_items.append(
                    pause_file
                )

                continue

            # ---------------------------------
            # Text chunks
            # ---------------------------------

            chunks = split_text(
                content
            )

            for chunk in chunks:

                if cancel_event.is_set():
                    raise asyncio.CancelledError()

                if not chunk:
                    continue

                global_index += 1

                if (
                    speaker["voice_mode"]
                    == "auto"
                ):

                    voice = choose_auto_voice(
                        chunk,
                        speaker[
                            "ar_voice"
                        ],
                        speaker[
                            "en_voice"
                        ],
                    )

                else:

                    voice = speaker[
                        "voice_mode"
                    ]

                output_file = unique_filename(
                    f"podcast_s{speaker_number}_{global_index}"
                )

                job = {
                    "text": chunk,
                    "voice": voice,
                    "rate": speaker[
                        "rate"
                    ],
                    "pitch": speaker[
                        "pitch"
                    ],
                    "volume": speaker[
                        "volume"
                    ],
                    "output": output_file,
                }

                jobs.append(job)

                ordered_items.append(
                    output_file
                )

    # -----------------------------------------
    # Parallel TTS
    # -----------------------------------------

    if jobs:

        await parallel_synthesize_jobs(
            jobs,
            state["parallel_channels"],
            cancel_event,
        )

    if cancel_event.is_set():
        raise asyncio.CancelledError()

    if not ordered_items:
        raise ValueError(
            "لم يتم إنشاء أي مقطع صوتي."
        )

    # -----------------------------------------
    # Merge exact dialogue order
    # -----------------------------------------

    final_file = unique_filename(
        "podcast_final"
    )

    await asyncio.to_thread(
        merge_audio_files,
        ordered_items,
        final_file,
    )

    return final_file


# ============================================================
# TXT FILE READER
# ============================================================

def read_txt_file(
    file_path,
):
    """
    Read Arabic/English TXT files with
    multiple encoding fallbacks.
    """

    encodings = [
        "utf-8",
        "utf-8-sig",
        "cp1256",
        "windows-1252",
        "latin-1",
    ]

    last_error = None

    for encoding in encodings:

        try:

            with open(
                file_path,
                "r",
                encoding=encoding,
            ) as f:

                return f.read()

        except UnicodeDecodeError as e:

            last_error = e

    raise RuntimeError(
        "تعذر قراءة ملف TXT.\n"
        f"{last_error}"
    )


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎙️ تحويل نص إلى صوت",
                    callback_data="mode_normal",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎧 إنشاء بودكاست",
                    callback_data="mode_podcast",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚙️ إعدادات النص إلى صوت",
                    callback_data="normal_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎛️ إعدادات البودكاست",
                    callback_data="podcast_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ قنوات المعالجة",
                    callback_data="parallel_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "🧠 برومبت البودكاست",
                    callback_data="show_prompt",
                )
            ],
            [
                InlineKeyboardButton(
                    "📖 تعليمات الاستخدام",
                    callback_data="help",
                )
            ],
        ]
    )


# ============================================================
# NORMAL SETTINGS
# ============================================================

def normal_settings_menu():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔊 اختيار الصوت",
                    callback_data="normal_voice",
                )
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
                    "🔉 مستوى الصوت",
                    callback_data="normal_volume",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ قنوات المعالجة",
                    callback_data="parallel_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data="back_main",
                )
            ],
        ]
    )


# ============================================================
# PODCAST SETTINGS
# ============================================================

def podcast_settings_menu():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎙️ المتحدث الأول",
                    callback_data="podcast_speaker_1",
                ),
                InlineKeyboardButton(
                    "🎙️ المتحدث الثاني",
                    callback_data="podcast_speaker_2",
                ),
            ],
            [
                InlineKeyboardButton(
                    "⚡ قنوات المعالجة",
                    callback_data="parallel_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data="back_main",
                )
            ],
        ]
    )


# ============================================================
# SPEAKER SETTINGS
# ============================================================

def speaker_settings_menu(
    speaker_number,
):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔊 الصوت",
                    callback_data=(
                        f"speaker_voice_{speaker_number}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⚡ السرعة",
                    callback_data=(
                        f"speaker_rate_{speaker_number}"
                    ),
                ),
                InlineKeyboardButton(
                    "↕️ النبرة",
                    callback_data=(
                        f"speaker_pitch_{speaker_number}"
                    ),
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔉 مستوى الصوت",
                    callback_data=(
                        f"speaker_volume_{speaker_number}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data="podcast_settings",
                )
            ],
        ]
    )


# ============================================================
# PARALLEL SETTINGS
# ============================================================

def parallel_keyboard(
    selected,
):

    keyboard = []

    row = []

    for value in PARALLEL_OPTIONS:

        text = (
            f"✅ {value}"
            if value == selected
            else str(value)
        )

        row.append(
            InlineKeyboardButton(
                f"{text} قناة",
                callback_data=(
                    f"parallel_set|{value}"
                ),
            )
        )

        if len(row) == 2:

            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main",
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# VOICE PAGINATION
# ============================================================

VOICE_PAGE_SIZE = 8


def voice_display_name(
    voice,
):

    short_name = voice.get(
        "ShortName",
        "Unknown",
    )

    locale = voice.get(
        "Locale",
        "",
    )

    gender = voice.get(
        "Gender",
        "",
    )

    return (
        f"{short_name} | "
        f"{locale} | "
        f"{gender}"
    )


def voice_pages(
    voices,
    prefix,
    page,
    back_callback="back_main",
):

    total_pages = max(
        1,
        (
            len(voices)
            + VOICE_PAGE_SIZE
            - 1
        )
        // VOICE_PAGE_SIZE,
    )

    page = max(
        0,
        min(
            page,
            total_pages - 1,
        ),
    )

    start = (
        page
        * VOICE_PAGE_SIZE
    )

    end = (
        start
        + VOICE_PAGE_SIZE
    )

    current = voices[
        start:end
    ]

    keyboard = []

    for voice in current:

        short_name = voice.get(
            "ShortName",
            "",
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    voice_display_name(
                        voice
                    )[:60],
                    callback_data=(
                        f"{prefix}_set|"
                        f"{short_name}"
                    ),
                )
            ]
        )

    navigation = []

    if page > 0:

        navigation.append(
            InlineKeyboardButton(
                "⬅️ السابق",
                callback_data=(
                    f"{prefix}_page|"
                    f"{page - 1}"
                ),
            )
        )

    if page < total_pages - 1:

        navigation.append(
            InlineKeyboardButton(
                "التالي ➡️",
                callback_data=(
                    f"{prefix}_page|"
                    f"{page + 1}"
                ),
            )
        )

    if navigation:
        keyboard.append(
            navigation
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🔄 Auto Language",
                callback_data=(
                    f"{prefix}_auto"
                ),
            )
        ]
    )

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data=back_callback,
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# VOICE TYPE MENU
# ============================================================

def voice_type_menu(
    ar_callback,
    en_callback,
    back_callback,
):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🇸🇦 الأصوات العربية",
                    callback_data=ar_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    "🇺🇸 الأصوات الإنجليزية",
                    callback_data=en_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Auto Language",
                    callback_data=(
                        f"{ar_callback}_auto"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data=back_callback,
                )
            ],
        ]
    )


# ============================================================
# RATE
# ============================================================

def rate_keyboard(
    prefix,
):

    values = [
        "-30%",
        "-20%",
        "-10%",
        "+0%",
        "+10%",
        "+20%",
        "+30%",
        "+50%",
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                value,
                callback_data=(
                    f"{prefix}_set|{value}"
                ),
            )
            for value in values[i:i + 4]
        ]
        for i in range(
            0,
            len(values),
            4,
        )
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main",
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# PITCH
# ============================================================

def pitch_keyboard(
    prefix,
):

    values = [
        "-20Hz",
        "-10Hz",
        "-5Hz",
        "+0Hz",
        "+5Hz",
        "+10Hz",
        "+20Hz",
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                value,
                callback_data=(
                    f"{prefix}_set|{value}"
                ),
            )
            for value in values[i:i + 4]
        ]
        for i in range(
            0,
            len(values),
            4,
        )
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main",
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# VOLUME
# ============================================================

def volume_keyboard(
    prefix,
):

    values = [
        "-20%",
        "-10%",
        "+0%",
        "+10%",
        "+20%",
    ]

    keyboard = [
        [
            InlineKeyboardButton(
                value,
                callback_data=(
                    f"{prefix}_set|{value}"
                ),
            )
            for value in values[i:i + 3]
        ]
        for i in range(
            0,
            len(values),
            3,
        )
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                "⬅️ رجوع",
                callback_data="back_main",
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = (
        update.effective_user.id
    )

    get_state(user_id)

    await update.message.reply_text(
        "مرحبًا بك 👋\n\n"
        "🎙️ نظام Edge TTS\n"
        "🎧 إنشاء بودكاست متعدد المتحدثين\n"
        "📄 يدعم ملفات TXT\n"
        "⚡ يدعم المعالجة المتوازية\n\n"
        "اختر العملية:",
        reply_markup=main_menu(),
    )


# ============================================================
# HELP
# ============================================================

HELP_TEXT = """
📖 تعليمات الاستخدام

🎙️ تحويل النص إلى صوت

يمكنك:
• إرسال النص مباشرة.
• أو إرسال ملف TXT.

البرنامج يقسم النص داخليًا إلى مقاطع
ويعالج عدة مقاطع بالتوازي حسب عدد القنوات
الذي تختاره.

🎧 البودكاست

يمكنك إرسال الحوار مباشرة أو داخل ملف TXT.

كل سطر غير فارغ = مداخلة واحدة.

السطر 1 = المتحدث الأول
السطر 2 = المتحدث الثاني
السطر 3 = المتحدث الأول
السطر 4 = المتحدث الثاني

علامات الترقيم لا تغيّر المتحدث.

⚠️ لا تكتب أسماء المتحدثين.

⏸️ الوقفات

[PAUSE:SHORT] = 350ms
[PAUSE:MEDIUM] = 700ms
[PAUSE:LONG] = 1200ms

هذه وقفات صوتية حقيقية وليست كلامًا منطوقًا.

🌐 Auto Language

يكتشف البرنامج اللغة تلقائيًا
ويختار الصوت العربي أو الإنجليزي المناسب.

⚡ القنوات المتوازية

1 قناة = معالجة واحدة في كل مرة.
2 قنوات = مقطعان في نفس الوقت.
3 قنوات = ثلاثة مقاطع في نفس الوقت.
5 قنوات = خمسة مقاطع في نفس الوقت.

والبرنامج يحافظ على ترتيب المقاطع الأصلي
عند دمج الملف النهائي.

📁 الملفات الناتجة

يتم حفظ الملفات داخل:
generated_audio

ولا يتم حذفها تلقائيًا.
"""


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

    state = get_state(user_id)

    data = query.data

    # ========================================================
    # MAIN
    # ========================================================

    if data == "back_main":

        await query.edit_message_text(
            "القائمة الرئيسية:",
            reply_markup=main_menu(),
        )

        return

    # ========================================================
    # PARALLEL SETTINGS
    # ========================================================

    if data == "parallel_settings":

        selected = state[
            "parallel_channels"
        ]

        await query.edit_message_text(
            "⚡ عدد قنوات المعالجة المتوازية:\n\n"
            "كلما زاد العدد يمكن معالجة عدد أكبر "
            "من مقاطع Edge TTS في نفس الوقت.\n\n"
            f"الإعداد الحالي: "
            f"{selected} قناة",
            reply_markup=parallel_keyboard(
                selected
            ),
        )

        return

    if data.startswith(
        "parallel_set|"
    ):

        value = int(
            data.split("|", 1)[1]
        )

        if value not in PARALLEL_OPTIONS:
            value = 1

        state[
            "parallel_channels"
        ] = value

        await query.edit_message_text(
            f"✅ تم ضبط المعالجة المتوازية على "
            f"{value} قناة.",
            reply_markup=main_menu(),
        )

        return

    # ========================================================
    # NORMAL MODE
    # ========================================================

    if data == "mode_normal":

        state["mode"] = "normal"

        await query.edit_message_text(
            "🎙️ وضع تحويل النص إلى صوت\n\n"
            "أرسل النص مباشرة، أو أرسل ملف TXT "
            "لتحويل نص ضخم إلى صوت.\n\n"
            "⚡ القنوات الحالية: "
            f"{state['parallel_channels']}"
        )

        return

    # ========================================================
    # NORMAL SETTINGS
    # ========================================================

    if data == "normal_settings":

        await query.edit_message_text(
            "⚙️ إعدادات النص إلى صوت:",
            reply_markup=normal_settings_menu(),
        )

        return

    # ========================================================
    # NORMAL VOICE
    # ========================================================

    if data == "normal_voice":

        await query.edit_message_text(
            "🔊 اختر نوع الأصوات:",
            reply_markup=voice_type_menu(
                "normal_ar_voice",
                "normal_en_voice",
                "normal_settings",
            ),
        )

        return

    if data == "normal_ar_voice":

        await load_voices(state)

        await query.edit_message_text(
            "🇸🇦 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                "normal_ar_voice",
                0,
                "normal_voice",
            ),
        )

        return

    if data.startswith(
        "normal_ar_voice_page|"
    ):

        page = int(
            data.split("|", 1)[1]
        )

        await query.edit_message_text(
            "🇸🇦 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                "normal_ar_voice",
                page,
                "normal_voice",
            ),
        )

        return

    if data.startswith(
        "normal_ar_voice_set|"
    ):

        voice = data.split(
            "|",
            1,
        )[1]

        state[
            "normal_ar_voice"
        ] = voice

        state[
            "normal_voice_mode"
        ] = "auto"

        await query.edit_message_text(
            f"✅ تم اختيار الصوت العربي:\n"
            f"{voice}\n\n"
            "والصوت الإنجليزي الحالي محفوظ.",
            reply_markup=normal_settings_menu(),
        )

        return

    if data == "normal_ar_voice_auto":

        state[
            "normal_voice_mode"
        ] = "auto"

        await query.edit_message_text(
            "✅ تم تفعيل Auto Language.",
            reply_markup=normal_settings_menu(),
        )

        return

    # ========================================================
    # NORMAL ENGLISH VOICE
    # ========================================================

    if data == "normal_en_voice":

        await load_voices(state)

        await query.edit_message_text(
            "🇺🇸 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                "normal_en_voice",
                0,
                "normal_voice",
            ),
        )

        return

    if data.startswith(
        "normal_en_voice_page|"
    ):

        page = int(
            data.split("|", 1)[1]
        )

        await query.edit_message_text(
            "🇺🇸 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                "normal_en_voice",
                page,
                "normal_voice",
            ),
        )

        return

    if data.startswith(
        "normal_en_voice_set|"
    ):

        voice = data.split(
            "|",
            1,
        )[1]

        state[
            "normal_en_voice"
        ] = voice

        state[
            "normal_voice_mode"
        ] = "auto"

        await query.edit_message_text(
            f"✅ تم اختيار الصوت الإنجليزي:\n"
            f"{voice}",
            reply_markup=normal_settings_menu(),
        )

        return

    if data == "normal_en_voice_auto":

        state[
            "normal_voice_mode"
        ] = "auto"

        await query.edit_message_text(
            "✅ تم تفعيل Auto Language.",
            reply_markup=normal_settings_menu(),
        )

        return

    # ========================================================
    # NORMAL RATE
    # ========================================================

    if data == "normal_rate":

        await query.edit_message_text(
            "⚡ اختر سرعة الكلام:",
            reply_markup=rate_keyboard(
                "normal_rate"
            ),
        )

        return

    if data.startswith(
        "normal_rate_set|"
    ):

        value = data.split(
            "|",
            1,
        )[1]

        state[
            "normal_rate"
        ] = value

        await query.edit_message_text(
            f"✅ السرعة: {value}",
            reply_markup=normal_settings_menu(),
        )

        return

    # ========================================================
    # NORMAL PITCH
    # ========================================================

    if data == "normal_pitch":

        await query.edit_message_text(
            "↕️ اختر النبرة:",
            reply_markup=pitch_keyboard(
                "normal_pitch"
            ),
        )

        return

    if data.startswith(
        "normal_pitch_set|"
    ):

        value = data.split(
            "|",
            1,
        )[1]

        state[
            "normal_pitch"
        ] = value

        await query.edit_message_text(
            f"✅ النبرة: {value}",
            reply_markup=normal_settings_menu(),
        )

        return

    # ========================================================
    # NORMAL VOLUME
    # ========================================================

    if data == "normal_volume":

        await query.edit_message_text(
            "🔉 اختر مستوى الصوت:",
            reply_markup=volume_keyboard(
                "normal_volume"
            ),
        )

        return

    if data.startswith(
        "normal_volume_set|"
    ):

        value = data.split(
            "|",
            1,
        )[1]

        state[
            "normal_volume"
        ] = value

        await query.edit_message_text(
            f"✅ مستوى الصوت: {value}",
            reply_markup=normal_settings_menu(),
        )

        return

    # ========================================================
    # PODCAST MODE
    # ========================================================

    if data == "mode_podcast":

        state["mode"] = "podcast"

        await query.edit_message_text(
            "🎧 وضع البودكاست\n\n"
            "يمكنك إرسال الحوار مباشرة، "
            "أو إرسال ملف TXT ضخم.\n\n"
            "كل سطر غير فارغ = مداخلة واحدة.\n\n"
            "السطر الأول = المتحدث الأول.\n"
            "السطر الثاني = المتحدث الثاني.\n"
            "ثم بالتناوب.\n\n"
            "⚡ القنوات الحالية: "
            f"{state['parallel_channels']}\n\n"
            "مثال:\n"
            "كيف حالك اليوم؟\n"
            "أنا بخير، وأريد أن أحدثك عن موضوع مهم.\n"
            "ما هو؟\n"
            "سنتحدث عن فوائد الجري.\n\n"
            "يمكن استخدام:\n"
            "[PAUSE:SHORT]\n"
            "[PAUSE:MEDIUM]\n"
            "[PAUSE:LONG]"
        )

        return

    # ========================================================
    # PODCAST SETTINGS
    # ========================================================

    if data == "podcast_settings":

        await query.edit_message_text(
            "🎛️ إعدادات البودكاست:",
            reply_markup=podcast_settings_menu(),
        )

        return

    if data == "podcast_speaker_1":

        await query.edit_message_text(
            "🎙️ إعدادات المتحدث الأول:",
            reply_markup=speaker_settings_menu(
                1
            ),
        )

        return

    if data == "podcast_speaker_2":

        await query.edit_message_text(
            "🎙️ إعدادات المتحدث الثاني:",
            reply_markup=speaker_settings_menu(
                2
            ),
        )

        return

    # ========================================================
    # SPEAKER VOICE
    # ========================================================

    if data in (
        "speaker_voice_1",
        "speaker_voice_2",
    ):

        speaker_number = int(
            data.split("_")[-1]
        )

        await query.edit_message_text(
            "🔊 اختر نوع الأصوات:",
            reply_markup=voice_type_menu(
                f"speaker{speaker_number}_ar_voice",
                f"speaker{speaker_number}_en_voice",
                f"podcast_speaker_{speaker_number}",
            ),
        )

        return

    # ========================================================
    # SPEAKER ARABIC VOICE
    # ========================================================

    match = re.match(
        r"speaker(\d+)_ar_voice$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await load_voices(state)

        await query.edit_message_text(
            "🇸🇦 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                f"speaker{speaker_number}_ar_voice",
                0,
                f"speaker_voice_{speaker_number}",
            ),
        )

        return

    match = re.match(
        r"speaker(\d+)_ar_voice_page\|(\d+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        page = int(
            match.group(2)
        )

        await query.edit_message_text(
            "🇸🇦 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                f"speaker{speaker_number}_ar_voice",
                page,
                f"speaker_voice_{speaker_number}",
            ),
        )

        return

    match = re.match(
        r"speaker(\d+)_ar_voice_set\|(.+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        voice = match.group(2)

        speaker = state[
            f"podcast_speaker{speaker_number}"
        ]

        speaker[
            "ar_voice"
        ] = voice

        speaker[
            "voice_mode"
        ] = "auto"

        await query.edit_message_text(
            f"✅ المتحدث {speaker_number}\n"
            f"الصوت العربي:\n{voice}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    match = re.match(
        r"speaker(\d+)_ar_voice_auto$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        speaker = state[
            f"podcast_speaker{speaker_number}"
        ]

        speaker[
            "voice_mode"
        ] = "auto"

        await query.edit_message_text(
            f"✅ تم تفعيل Auto Language "
            f"للمتحدث {speaker_number}.",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # ========================================================
    # SPEAKER ENGLISH VOICE
    # ========================================================

    match = re.match(
        r"speaker(\d+)_en_voice$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await load_voices(state)

        await query.edit_message_text(
            "🇺🇸 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                f"speaker{speaker_number}_en_voice",
                0,
                f"speaker_voice_{speaker_number}",
            ),
        )

        return

    match = re.match(
        r"speaker(\d+)_en_voice_page\|(\d+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        page = int(
            match.group(2)
        )

        await query.edit_message_text(
            "🇺🇸 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                f"speaker{speaker_number}_en_voice",
                page,
                f"speaker_voice_{speaker_number}",
            ),
        )

        return

    match = re.match(
        r"speaker(\d+)_en_voice_set\|(.+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        voice = match.group(2)

        speaker = state[
            f"podcast_speaker{speaker_number}"
        ]

        speaker[
            "en_voice"
        ] = voice

        speaker[
            "voice_mode"
        ] = "auto"

        await query.edit_message_text(
            f"✅ المتحدث {speaker_number}\n"
            f"الصوت الإنجليزي:\n{voice}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # ========================================================
    # SPEAKER RATE
    # ========================================================

    match = re.match(
        r"speaker_rate_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await query.edit_message_text(
            f"⚡ سرعة المتحدث "
            f"{speaker_number}:",
            reply_markup=rate_keyboard(
                f"speaker_rate_{speaker_number}"
            ),
        )

        return

    match = re.match(
        r"speaker_rate_(\d+)_set\|(.+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        value = match.group(2)

        speaker = state[
            f"podcast_speaker{speaker_number}"
        ]

        speaker["rate"] = value

        await query.edit_message_text(
            f"✅ سرعة المتحدث "
            f"{speaker_number}: {value}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # ========================================================
    # SPEAKER PITCH
    # ========================================================

    match = re.match(
        r"speaker_pitch_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await query.edit_message_text(
            f"↕️ نبرة المتحدث "
            f"{speaker_number}:",
            reply_markup=pitch_keyboard(
                f"speaker_pitch_{speaker_number}"
            ),
        )

        return

    match = re.match(
        r"speaker_pitch_(\d+)_set\|(.+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        value = match.group(2)

        speaker = state[
            f"podcast_speaker{speaker_number}"
        ]

        speaker["pitch"] = value

        await query.edit_message_text(
            f"✅ نبرة المتحدث "
            f"{speaker_number}: {value}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # ========================================================
    # SPEAKER VOLUME
    # ========================================================

    match = re.match(
        r"speaker_volume_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await query.edit_message_text(
            f"🔉 مستوى صوت المتحدث "
            f"{speaker_number}:",
            reply_markup=volume_keyboard(
                f"speaker_volume_{speaker_number}"
            ),
        )

        return

    match = re.match(
        r"speaker_volume_(\d+)_set\|(.+)",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        value = match.group(2)

        speaker = state[
            f"podcast_speaker{speaker_number}"
        ]

        speaker["volume"] = value

        await query.edit_message_text(
            f"✅ مستوى صوت المتحدث "
            f"{speaker_number}: {value}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # ========================================================
    # AI PROMPT
    # ========================================================

    if data == "show_prompt":

        await query.message.reply_text(
            "🧠 البرومبت الرئيسي:\n\n"
            + PODCAST_AI_PROMPT
        )

        return

    # ========================================================
    # HELP
    # ========================================================

    if data == "help":

        await query.edit_message_text(
            HELP_TEXT,
            reply_markup=main_menu(),
        )

        return


# ============================================================
# PROCESS TEXT
# ============================================================

async def process_input_text(
    update,
    state,
    text,
):

    if state["cancel_event"] is not None:

        state[
            "cancel_event"
        ].set()

    cancel_event = asyncio.Event()

    state[
        "cancel_event"
    ] = cancel_event

    if state["mode"] == "normal":

        status_message = (
            await update.message.reply_text(
                "⏳ جاري تحويل النص إلى صوت...\n"
                f"⚡ القنوات: "
                f"{state['parallel_channels']}\n"
                "📄 يتم الحفاظ على ترتيب المقاطع."
            )
        )

        try:

            final_file = (
                await generate_normal_audio(
                    state,
                    text,
                    cancel_event,
                )
            )

            if cancel_event.is_set():
                return

            await status_message.edit_text(
                "✅ تم إنشاء الصوت بنجاح."
            )

            with open(
                final_file,
                "rb",
            ) as audio:

                await update.message.reply_audio(
                    audio=audio,
                    title=final_file.name,
                )

        except asyncio.CancelledError:

            await status_message.edit_text(
                "🛑 تم إلغاء العملية."
            )

        except Exception as e:

            logger.exception(
                "Normal TTS failed: %s",
                e,
            )

            await status_message.edit_text(
                "❌ حدث خطأ أثناء إنشاء الصوت:\n"
                f"{e}"
            )

        finally:

            if (
                state["cancel_event"]
                is cancel_event
            ):
                state[
                    "cancel_event"
                ] = None

        return

    # ========================================================
    # PODCAST
    # ========================================================

    if state["mode"] == "podcast":

        status_message = (
            await update.message.reply_text(
                "⏳ جاري إنشاء البودكاست...\n"
                f"⚡ القنوات: "
                f"{state['parallel_channels']}\n"
                "🎙️ تتم معالجة المقاطع بالتوازي "
                "مع الحفاظ على ترتيب الحوار."
            )
        )

        try:

            final_file = (
                await generate_podcast_audio(
                    state,
                    text,
                    cancel_event,
                )
            )

            if cancel_event.is_set():
                return

            await status_message.edit_text(
                "🎧 تم إنشاء البودكاست بنجاح."
            )

            with open(
                final_file,
                "rb",
            ) as audio:

                await update.message.reply_audio(
                    audio=audio,
                    title=final_file.name,
                )

        except asyncio.CancelledError:

            await status_message.edit_text(
                "🛑 تم إلغاء إنشاء البودكاست."
            )

        except Exception as e:

            logger.exception(
                "Podcast generation failed: %s",
                e,
            )

            await status_message.edit_text(
                "❌ حدث خطأ أثناء إنشاء البودكاست:\n"
                f"{e}"
            )

        finally:

            if (
                state["cancel_event"]
                is cancel_event
            ):
                state[
                    "cancel_event"
                ] = None

        return


# ============================================================
# TEXT MESSAGE HANDLER
# ============================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = (
        update.effective_user.id
    )

    state = get_state(user_id)

    text = (
        update.message.text or ""
    ).strip()

    if not text:
        return

    if state["mode"] is None:

        await update.message.reply_text(
            "اختر أولًا نوع العملية:",
            reply_markup=main_menu(),
        )

        return

    await process_input_text(
        update,
        state,
        text,
    )


# ============================================================
# TXT DOCUMENT HANDLER
# ============================================================

async def document_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = (
        update.effective_user.id
    )

    state = get_state(user_id)

    document = update.message.document

    if document is None:
        return

    filename = (
        document.file_name
        or "uploaded.txt"
    )

    extension = (
        Path(filename)
        .suffix
        .lower()
    )

    # Only TXT for now
    if extension != ".txt":

        await update.message.reply_text(
            "❌ هذا الملف غير مدعوم.\n\n"
            "حاليًا يدعم البرنامج ملفات:\n"
            "📄 .txt"
        )

        return

    if state["mode"] is None:

        await update.message.reply_text(
            "📄 تم استلام ملف TXT.\n\n"
            "اختر أولًا العملية التي تريدها:",
            reply_markup=main_menu(),
        )

        return

    status = await update.message.reply_text(
        "📥 جاري قراءة ملف TXT..."
    )

    try:

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        safe_name = re.sub(
            r"[^a-zA-Z0-9._-]",
            "_",
            filename,
        )

        source_path = (
            SOURCE_DIR
            / f"{timestamp}_{safe_name}"
        )

        telegram_file = (
            await document.get_file()
        )

        await telegram_file.download_to_drive(
            custom_path=str(
                source_path
            )
        )

        text = await asyncio.to_thread(
            read_txt_file,
            source_path,
        )

        if not text.strip():

            await status.edit_text(
                "❌ ملف TXT فارغ."
            )

            return

        char_count = len(text)

        await status.edit_text(
            "✅ تم قراءة الملف بنجاح.\n\n"
            f"📄 الملف: {filename}\n"
            f"🔤 عدد الأحرف: {char_count:,}\n"
            f"⚡ القنوات: "
            f"{state['parallel_channels']}\n\n"
            "⏳ بدأت المعالجة..."
        )

        # ------------------------------------
        # Cancel previous operation
        # ------------------------------------

        if state["cancel_event"] is not None:

            state[
                "cancel_event"
            ].set()

        cancel_event = asyncio.Event()

        state[
            "cancel_event"
        ] = cancel_event

        # ------------------------------------
        # Normal
        # ------------------------------------

        if state["mode"] == "normal":

            final_file = (
                await generate_normal_audio(
                    state,
                    text,
                    cancel_event,
                )
            )

            if cancel_event.is_set():
                return

            await status.edit_text(
                "✅ تم تحويل ملف TXT إلى صوت."
            )

            with open(
                final_file,
                "rb",
            ) as audio:

                await update.message.reply_audio(
                    audio=audio,
                    title=final_file.name,
                )

        # ------------------------------------
        # Podcast
        # ------------------------------------

        elif state["mode"] == "podcast":

            final_file = (
                await generate_podcast_audio(
                    state,
                    text,
                    cancel_event,
                )
            )

            if cancel_event.is_set():
                return

            await status.edit_text(
                "🎧 تم إنشاء البودكاست من ملف TXT."
            )

            with open(
                final_file,
                "rb",
            ) as audio:

                await update.message.reply_audio(
                    audio=audio,
                    title=final_file.name,
                )

    except asyncio.CancelledError:

        await status.edit_text(
            "🛑 تم إلغاء العملية."
        )

    except Exception as e:

        logger.exception(
            "TXT processing failed: %s",
            e,
        )

        await status.edit_text(
            "❌ حدث خطأ أثناء معالجة ملف TXT:\n"
            f"{e}"
        )

    finally:

        # We intentionally DO NOT delete
        # the uploaded TXT or generated files.

        if "cancel_event" in locals():

            if (
                state["cancel_event"]
                is cancel_event
            ):

                state[
                    "cancel_event"
                ] = None


# ============================================================
# CANCEL
# ============================================================

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = (
        update.effective_user.id
    )

    state = get_state(user_id)

    if state["cancel_event"] is not None:

        state[
            "cancel_event"
        ].set()

        await update.message.reply_text(
            "🛑 تم إرسال أمر إلغاء العملية الحالية."
        )

    else:

        await update.message.reply_text(
            "لا توجد عملية قيد التنفيذ."
        )


# ============================================================
# PROMPT
# ============================================================

async def prompt_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        PODCAST_AI_PROMPT
    )


# ============================================================
# HELP COMMAND
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        HELP_TEXT,
        reply_markup=main_menu(),
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.exception(
        "Unhandled exception:",
        exc_info=context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commands
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "prompt",
            prompt_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # --------------------------------------------------------
    # Buttons
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # --------------------------------------------------------
    # TXT files
    #
    # IMPORTANT:
    # This handler is separate from TEXT.
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler,
        )
    )

    # --------------------------------------------------------
    # Normal text
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
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
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
