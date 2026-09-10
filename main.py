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

SOURCE_DIR = BASE_DIR / "uploaded_sources"
SOURCE_DIR.mkdir(parents=True, exist_ok=True)

MAX_CHARS = 2500

# Parallel TTS channels
ALLOWED_CHANNELS = [1, 2, 3, 5]

# Real silence durations
PAUSE_DURATIONS = {
    "SHORT": 350,
    "MEDIUM": 700,
    "LONG": 1200,
}

DEFAULT_RATE = "+0%"
DEFAULT_VOLUME = "+0%"
DEFAULT_PITCH = "+0Hz"

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
        # Current mode
        # ----------------------------------------------------

        "mode": None,

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
        # Podcast
        # ----------------------------------------------------

        "podcast_speaker1": {
            "voice_mode": "auto",

            "ar_voice": DEFAULT_AR_VOICE,
            "en_voice": DEFAULT_EN_VOICE,

            "rate": DEFAULT_RATE,
            "pitch": DEFAULT_PITCH,
            "volume": DEFAULT_VOLUME,
        },

        "podcast_speaker2": {
            "voice_mode": "auto",

            "ar_voice": DEFAULT_AR_FEMALE,
            "en_voice": DEFAULT_EN_FEMALE,

            "rate": DEFAULT_RATE,
            "pitch": DEFAULT_PITCH,
            "volume": DEFAULT_VOLUME,
        },

        # ----------------------------------------------------
        # Parallel channels
        # ----------------------------------------------------

        "parallel_channels": 1,

        # ----------------------------------------------------
        # Output filename
        # ----------------------------------------------------

        "filename_base": "audio",

        "serial_enabled": True,

        # ----------------------------------------------------
        # Runtime
        # ----------------------------------------------------

        "cancel_event": None,

        # Used when waiting for custom filename
        "waiting_for_filename": False,

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
   - السطر الأول = المتحدث الأول.
   - السطر الثاني = المتحدث الثاني.
   - السطر الثالث = المتحدث الأول.
   - السطر الرابع = المتحدث الثاني.
   - وهكذا حتى النهاية.

3. لا تكتب أسماء المتحدثين.

4. لا تكتب:
   - المتحدث الأول:
   - المتحدث الثاني:
   - 1:
   - 2:
   - Speaker 1
   - Speaker 2
   - [1]
   - [2]

5. كل سطر يمثل دورًا صوتيًا كاملًا لمتحدث واحد.

6. تغيير السطر هو الطريقة الوحيدة التي تحدد انتقال الكلام من متحدث إلى الآخر.

7. علامات الترقيم مثل:
   . ، ؛ ؟ !
   لا تغيّر المتحدث.

8. إذا كانت الجملة طويلة فلا تقسّمها إلى عدة أسطر لمجرد أنها طويلة؛ يجب أن تبقى ضمن دور المتحدث نفسه.

9. الحوار يجب أن يكون تفاعليًا، وليس مجرد مقابلة جامدة.

10. يجب أن يتفاعل كل متحدث فعلًا مع كلام المتحدث الآخر.

11. ممنوع أن يكون أحد المتحدثين مجرد مذيع يسأل طوال الوقت، بينما الآخر يجيب طوال الوقت.

12. كلا المتحدثين يجب أن:
   - يسأل أحيانًا.
   - يجيب أحيانًا.
   - يشرح أحيانًا.
   - يعترض أحيانًا عندما يكون الاعتراض منطقيًا.
   - يضيف معلومات.
   - يوضح أفكارًا.
   - يربط بين النقاط.

13. لا تجعل الحوار عبارة عن:
   سؤال ← جواب ← سؤال ← جواب
   بشكل آلي متكرر.

14. اجعل الحوار يبدو وكأن شخصين حقيقيين يتحدثان.

15. استخدم انتقالات طبيعية دون تكرار آلي.

16. تجنب الردود الروبوتية المتكررة.

17. اجعل أطوال المداخلات متنوعة.

18. لا تجعل كل سطر بنفس الطول تقريبًا.

19. إذا كان المستخدم قدّم مصدرًا:
   - اعتمد على المعلومات الموجودة في المصدر.
   - أعد صياغتها في صورة حوار.
   - لا تخترع معلومات غير موجودة فيه إلا إذا كانت ضرورية جدًا للربط.

20. إذا لم يقدم المستخدم مصدرًا، فاستخدم المعرفة العامة الموثوقة.

21. اللغة:
   - استخدم العربية الفصحى الطبيعية.
   - استخدم التشكيل العربي قدر الإمكان.
   - اجعل التشكيل صحيحًا نحويًا وصوتيًا.
   - لا تستخدم لهجة عامية إلا إذا طلب المستخدم ذلك.

22. إذا كان الحوار يحتوي على كلمات أو مصطلحات إنجليزية ضرورية، فاستخدمها بشكل طبيعي.

23. نظام الصوت يدعم الانتقال بين العربية والإنجليزية تلقائيًا.

24. لا تكتب أي تعليمات صوتية داخل الحوار.

25. بدلًا من ذلك، يمكنك استخدام نظام الوقفات التالي فقط:

   [PAUSE:SHORT]
   [PAUSE:MEDIUM]
   [PAUSE:LONG]

26. استخدم الوقفات عندما تكون مناسبة.

27. لا تستخدم الوقفات بكثرة.

28. لا تستخدم وقفتين متتاليتين.

29. لا تبدأ سطرًا بعلامة PAUSE.

30. لا تستخدم أي صيغة أخرى للوقفات.

31. الصيغ الوحيدة المسموح بها هي:

   [PAUSE:SHORT]
   [PAUSE:MEDIUM]
   [PAUSE:LONG]

32. لا تضع عنوانًا للحوار.

33. لا تكتب مقدمة خارج الحوار.

34. لا تكتب شرحًا بعد الحوار.

35. لا تستخدم Markdown.

36. لا تستخدم قوائم.

37. لا تستخدم أرقامًا لتحديد المتحدثين.

38. الناتج النهائي يجب أن يكون الحوار فقط.

39. راجع داخليًا:
   - هل عدد المتحدثين اثنان؟
   - هل التناوب صحيح؟
   - هل توجد أسماء للمتحدثين؟
   - هل توجد تعليمات خارج الحوار؟
   - هل الوقفات صحيحة؟
   - هل الحوار تفاعلي؟
   - هل كلا المتحدثين يشاركان؟
   - هل التشكيل مناسب لـ TTS؟
   - هل الحوار يبدو بشريًا وغير آلي؟

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

                        if (
                            split_pos
                            > max_chars * 0.5
                        ):

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

    for match in PAUSE_PATTERN.finditer(
        text
    ):

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

        pause_type = match.group(
            1
        ).upper()

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


def remove_pause_tokens(text):

    return PAUSE_PATTERN.sub(
        "",
        text,
    ).strip()


# ============================================================
# UNIQUE FILE NAME
# ============================================================

def safe_filename(name):

    name = name.strip()

    name = re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        name,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    if not name:
        name = "audio"

    return name[:100]


def get_next_serial(base_name):

    base_name = safe_filename(
        base_name
    )

    pattern = re.compile(
        rf"^{re.escape(base_name)}_(\d{{3}})\.mp3$",
        re.IGNORECASE,
    )

    highest = 0

    for file in AUDIO_DIR.glob(
        "*.mp3"
    ):

        match = pattern.match(
            file.name
        )

        if match:

            try:
                number = int(
                    match.group(1)
                )

                highest = max(
                    highest,
                    number,
                )

            except ValueError:
                pass

    return highest + 1


def final_output_filename(
    state,
    prefix,
):

    base = state.get(
        "filename_base",
        prefix,
    )

    if not base:
        base = prefix

    base = safe_filename(base)

    if state.get(
        "serial_enabled",
        True,
    ):

        serial = get_next_serial(
            base
        )

        return AUDIO_DIR / (
            f"{base}_{serial:03d}.mp3"
        )

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    return AUDIO_DIR / (
        f"{base}_{timestamp}.mp3"
    )


def unique_filename(prefix="audio"):

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    return AUDIO_DIR / (
        f"{prefix}_{timestamp}.mp3"
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
        f"فشل Edge TTS بعد {retries} محاولات: {last_error}"
    )


# ============================================================
# CREATE REAL SILENCE
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
        sample_rate
        * duration_seconds
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
# MERGE AUDIO FILES
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

                frame.time_base = (
                    Fraction(
                        1,
                        target_rate,
                    )
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

        for packet in output_stream.encode(
            None
        ):

            output_container.mux(packet)

    finally:

        output_container.close()


# ============================================================
# PROGRESS BAR
# ============================================================

def make_progress_bar(
    completed,
    total,
    width=18,
):

    if total <= 0:
        return "░" * width

    ratio = completed / total

    ratio = max(
        0.0,
        min(
            1.0,
            ratio,
        ),
    )

    filled = int(
        width * ratio
    )

    return (
        "█" * filled
        + "░" * (width - filled)
    )


class ProgressReporter:

    def __init__(
        self,
        message,
        total,
        label="جاري المعالجة",
    ):

        self.message = message
        self.total = max(
            1,
            total,
        )

        self.completed = 0

        self.label = label

        self.lock = asyncio.Lock()

        self.last_update = 0.0

    async def update(
        self,
        amount=1,
        force=False,
    ):

        async with self.lock:

            self.completed += amount

            now = asyncio.get_running_loop().time()

            if (
                not force
                and now - self.last_update < 1.0
                and self.completed < self.total
            ):

                return

            self.last_update = now

            bar = make_progress_bar(
                self.completed,
                self.total,
            )

            percent = int(
                (
                    self.completed
                    / self.total
                )
                * 100
            )

            percent = min(
                100,
                percent,
            )

            text = (
                f"⏳ {self.label}\n\n"
                f"{bar} {percent}%\n\n"
                f"📦 المقاطع: "
                f"{self.completed}/"
                f"{self.total}\n"
                f"⚡ القنوات المتوازية: "
                f"{self.total_channels}"
            )

            try:

                await self.message.edit_text(
                    text
                )

            except Exception:

                pass

    def set_channels(
        self,
        channels,
    ):

        self.total_channels = channels


# ============================================================
# PARALLEL TTS ENGINE
# ============================================================

async def synthesize_parallel(
    jobs,
    channels,
    cancel_event,
    progress,
):

    """
    jobs:
        list of dictionaries containing:
            text
            output_file
            voice
            rate
            pitch
            volume

    The returned list keeps EXACTLY the same order
    as jobs, even when generation is parallel.
    """

    if not jobs:
        return []

    semaphore = asyncio.Semaphore(
        channels
    )

    results = [None] * len(jobs)

    async def worker(
        index,
        job,
    ):

        if cancel_event.is_set():

            raise asyncio.CancelledError()

        async with semaphore:

            if cancel_event.is_set():

                raise asyncio.CancelledError()

            await synthesize_to_file(
                job["text"],
                job["output_file"],
                job["voice"],
                job["rate"],
                job["pitch"],
                job["volume"],
            )

            results[index] = (
                job["output_file"]
            )

            await progress.update()

    tasks = [
        asyncio.create_task(
            worker(
                index,
                job,
            )
        )
        for index, job in enumerate(
            jobs
        )
    ]

    try:

        await asyncio.gather(
            *tasks
        )

    except asyncio.CancelledError:

        for task in tasks:

            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        raise

    except Exception:

        for task in tasks:

            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        raise

    return results


# ============================================================
# NORMAL AUDIO GENERATION
# ============================================================

async def generate_normal_audio(
    state,
    text,
    cancel_event,
    progress_message,
):

    await load_voices(state)

    parts = parse_pause_tokens(
        text
    )

    # Count text chunks + pauses
    total_jobs = 0

    for part_type, content in parts:

        if part_type == "pause":

            total_jobs += 1

        else:

            total_jobs += len(
                split_text(content)
            )

    if total_jobs <= 0:

        raise ValueError(
            "لم يتم العثور على نص صالح للتوليد."
        )

    progress = ProgressReporter(
        progress_message,
        total_jobs,
        "🎙️ جاري تحويل النص إلى صوت",
    )

    progress.set_channels(
        state["parallel_channels"]
    )

    generated_files = []

    # --------------------------------------------------------
    # We process each pause/text section in order.
    # Text chunks inside a section run in parallel.
    # --------------------------------------------------------

    for part_type, content in parts:

        if cancel_event.is_set():

            raise asyncio.CancelledError()

        if part_type == "pause":

            pause_file = unique_filename(
                f"pause_{content.lower()}"
            )

            create_silence_mp3(
                PAUSE_DURATIONS[content],
                pause_file,
            )

            generated_files.append(
                pause_file
            )

            await progress.update()

            continue

        text_chunks = split_text(
            content
        )

        jobs = []

        for chunk_index, chunk in enumerate(
            text_chunks
        ):

            if cancel_event.is_set():

                raise asyncio.CancelledError()

            if state[
                "normal_voice_mode"
            ] == "auto":

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

                voice = state[
                    "normal_voice_mode"
                ]

            output_file = unique_filename(
                f"normal_{chunk_index + 1}"
            )

            jobs.append(
                {
                    "text": chunk,
                    "output_file": output_file,
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
                }
            )

        results = await synthesize_parallel(
            jobs,
            state["parallel_channels"],
            cancel_event,
            progress,
        )

        # VERY IMPORTANT:
        # Results remain in original order.
        generated_files.extend(
            results
        )

    if not generated_files:

        raise ValueError(
            "لم يتم إنشاء أي مقطع صوتي."
        )

    final_file = final_output_filename(
        state,
        "tts",
    )

    await progress_message.edit_text(
        "🔄 جاري دمج جميع المقاطع بالترتيب..."
    )

    await asyncio.to_thread(
        merge_audio_files,
        generated_files,
        final_file,
    )

    await progress_message.edit_text(
        "✅ اكتمل تحويل النص ودمج الصوت."
    )

    return final_file


# ============================================================
# PODCAST AUDIO GENERATION
# ============================================================

async def generate_podcast_audio(
    state,
    dialogue,
    cancel_event,
    progress_message,
):

    """
    Strict speaker alternation:

    Line 1 -> speaker 1
    Line 2 -> speaker 2
    Line 3 -> speaker 1
    Line 4 -> speaker 2
    ...

    Pause tokens don't count as speaker turns.

    Parallel generation is used for TTS chunks,
    but final merge ALWAYS follows original dialogue order.
    """

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

    # --------------------------------------------------------
    # Build ordered jobs
    # --------------------------------------------------------

    ordered_items = []

    total_jobs = 0

    for line_number, line in enumerate(
        lines,
        start=1,
    ):

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

            if part_type == "pause":

                ordered_items.append(
                    {
                        "type": "pause",
                        "pause": content,
                    }
                )

                total_jobs += 1

                continue

            chunks = split_text(
                content
            )

            for chunk in chunks:

                if not chunk:
                    continue

                if speaker[
                    "voice_mode"
                ] == "auto":

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

                ordered_items.append(
                    {
                        "type": "tts",
                        "speaker": speaker_number,
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
                    }
                )

                total_jobs += 1

    if total_jobs <= 0:

        raise ValueError(
            "لم يتم إنشاء أي مقطع صوتي."
        )

    progress = ProgressReporter(
        progress_message,
        total_jobs,
        "🎧 جاري إنشاء البودكاست",
    )

    progress.set_channels(
        state["parallel_channels"]
    )

    # --------------------------------------------------------
    # We cannot blindly parallelize across dialogue
    # if pauses/order must be respected.
    #
    # Therefore:
    # - Collect TTS jobs in ordered positions.
    # - Generate them concurrently.
    # - Put results back into their exact positions.
    # - Generate pause files separately.
    # - Merge everything according to ordered_items.
    # --------------------------------------------------------

    tts_jobs = []

    tts_positions = []

    for position, item in enumerate(
        ordered_items
    ):

        if item["type"] != "tts":
            continue

        output_file = unique_filename(
            f"podcast_s{item['speaker']}"
        )

        job = {
            "text": item["text"],
            "output_file": output_file,
            "voice": item["voice"],
            "rate": item["rate"],
            "pitch": item["pitch"],
            "volume": item["volume"],
        }

        tts_jobs.append(job)

        tts_positions.append(
            position
        )

    # --------------------------------------------------------
    # Generate ALL TTS chunks in parallel.
    # --------------------------------------------------------

    tts_results = await synthesize_parallel(
        tts_jobs,
        state["parallel_channels"],
        cancel_event,
        progress,
    )

    if cancel_event.is_set():

        raise asyncio.CancelledError()

    # --------------------------------------------------------
    # Map results to exact positions
    # --------------------------------------------------------

    result_by_position = {}

    for position, result in zip(
        tts_positions,
        tts_results,
    ):

        result_by_position[
            position
        ] = result

    # --------------------------------------------------------
    # Create pauses and final ordered list
    # --------------------------------------------------------

    generated_files = []

    for position, item in enumerate(
        ordered_items
    ):

        if cancel_event.is_set():

            raise asyncio.CancelledError()

        if item["type"] == "pause":

            pause_file = unique_filename(
                f"podcast_pause_{item['pause'].lower()}"
            )

            await asyncio.to_thread(
                create_silence_mp3,
                PAUSE_DURATIONS[
                    item["pause"]
                ],
                pause_file,
            )

            generated_files.append(
                pause_file
            )

            # Pause progress may already be
            # updated by TTS only, so update here.
            await progress.update()

        else:

            generated_files.append(
                result_by_position[
                    position
                ]
            )

    if not generated_files:

        raise ValueError(
            "لم يتم إنشاء أي مقطع صوتي."
        )

    final_file = final_output_filename(
        state,
        "podcast",
    )

    await progress_message.edit_text(
        "🔄 جاري دمج البودكاست بالترتيب الصحيح..."
    )

    await asyncio.to_thread(
        merge_audio_files,
        generated_files,
        final_file,
    )

    await progress_message.edit_text(
        "🎧 اكتمل إنشاء البودكاست ودمج جميع المتحدثين."
    )

    return final_file


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
                    "⚡ سرعة المعالجة",
                    callback_data="parallel_settings",
                )
            ],
            [
                InlineKeyboardButton(
                    "📁 اسم وترقيم الملف",
                    callback_data="filename_settings",
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
# NORMAL SETTINGS MENU
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
                    "⬅️ رجوع",
                    callback_data="back_main",
                )
            ],
        ]
    )


# ============================================================
# PODCAST SETTINGS MENU
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
                    "⬅️ رجوع",
                    callback_data="back_main",
                )
            ],
        ]
    )


def speaker_settings_menu(
    speaker_number
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
                    "🔉 الصوت",
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

def parallel_settings_menu(
    state
):

    channels = state[
        "parallel_channels"
    ]

    keyboard = []

    for value in ALLOWED_CHANNELS:

        mark = (
            "✅ "
            if value == channels
            else ""
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{mark}{value} قناة متوازية",
                    callback_data=(
                        f"parallel_set|{value}"
                    ),
                )
            ]
        )

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
# FILENAME SETTINGS
# ============================================================

def filename_settings_menu(
    state
):

    serial = (
        "🟢 الترقيم: تشغيل"
        if state["serial_enabled"]
        else "🔴 الترقيم: إيقاف"
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ تغيير اسم الملف",
                    callback_data="filename_custom",
                )
            ],
            [
                InlineKeyboardButton(
                    serial,
                    callback_data="filename_toggle_serial",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 اسم افتراضي",
                    callback_data="filename_reset",
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
# VOICE LIST PAGINATION
# ============================================================

VOICE_PAGE_SIZE = 8


def voice_display_name(
    voice
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
                "🌐 اختيار الإنجليزية",
                callback_data=(
                    prefix.replace(
                        "_ar_voice",
                        "_en_voice",
                    )
                ),
            )
        ]
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
                callback_data="back_main",
            )
        ]
    )

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# RATE / PITCH / VOLUME
# ============================================================

def rate_keyboard(prefix):

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


def pitch_keyboard(prefix):

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


def volume_keyboard(prefix):

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
# /START
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
        "🎧 إنشاء بودكاست متعدد المتحدثين\n\n"
        "يمكنك إرسال نص أو ملف TXT.\n\n"
        "اختر العملية:",
        reply_markup=main_menu(),
    )


# ============================================================
# HELP
# ============================================================

HELP_TEXT = """
📖 تعليمات الاستخدام

🎙️ تحويل نص إلى صوت

يمكنك:
• إرسال النص مباشرة.
• أو إرسال ملف TXT ضخم.

سيتم تقسيم النص داخليًا ثم توليده بالتوازي حسب عدد القنوات التي اخترتها.

🎧 البودكاست

يمكنك إرسال الحوار مباشرة أو كملف TXT.

كل سطر = مداخلة واحدة.

السطر 1 = المتحدث الأول
السطر 2 = المتحدث الثاني
السطر 3 = المتحدث الأول
السطر 4 = المتحدث الثاني

لا تكتب أسماء المتحدثين.

⏸️ الوقفات:

[PAUSE:SHORT]
[PAUSE:MEDIUM]
[PAUSE:LONG]

🌐 Auto Language

يكتشف البرنامج العربية والإنجليزية تلقائيًا.

⚡ القنوات المتوازية

يمكنك اختيار:
1 قناة
2 قناة
3 قنوات
5 قنوات

كلما زادت القنوات قد تزيد سرعة الإنتاج،
مع الحفاظ على ترتيب المقاطع النهائي.

📁 الملفات

يمكن اختيار اسم الملف.

ويمكن تفعيل الترقيم:

audio_001.mp3
audio_002.mp3
audio_003.mp3

أو مثلًا:

podcast_001.mp3
podcast_002.mp3

الملفات لا يتم حذفها تلقائيًا.

🛑 لإلغاء العملية:

/cancel
"""


# ============================================================
# TXT READER
# ============================================================

def read_txt_file(
    path
):

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp1256",
        "windows-1256",
        "latin-1",
    ]

    last_error = None

    for encoding in encodings:

        try:

            with open(
                path,
                "r",
                encoding=encoding,
            ) as f:

                return f.read()

        except UnicodeDecodeError as e:

            last_error = e

    raise RuntimeError(
        f"تعذر قراءة ملف TXT: {last_error}"
    )


# ============================================================
# DOCUMENT HANDLER
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
        or "document.txt"
    )

    extension = (
        Path(filename)
        .suffix
        .lower()
    )

    if extension != ".txt":

        await update.message.reply_text(
            "❌ حاليًا الملفات المدعومة هي:\n\n"
            "📄 .txt\n\n"
            "أرسل ملف TXT ثم اختر وضع تحويل النص "
            "أو البودكاست."
        )

        return

    if state["mode"] is None:

        await update.message.reply_text(
            "📄 تم استلام ملف TXT.\n\n"
            "اختر أولًا العملية التي تريد تنفيذها:",
            reply_markup=main_menu(),
        )

        # We still don't process because mode
        # wasn't selected.
        return

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    safe_name = safe_filename(
        Path(filename).stem
    )

    source_path = (
        SOURCE_DIR
        / f"{user_id}_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.txt"
    )

    try:

        status_message = (
            await update.message.reply_text(
                "📥 جاري تنزيل ملف TXT..."
            )
        )

        telegram_file = (
            await context.bot.get_file(
                document.file_id
            )
        )

        await telegram_file.download_to_drive(
            custom_path=str(
                source_path
            )
        )

        text = read_txt_file(
            source_path
        )

        if not text.strip():

            await status_message.edit_text(
                "❌ ملف TXT فارغ."
            )

            return

        logger.info(
            "Received TXT file %s (%s chars) from user %s",
            filename,
            len(text),
            user_id,
        )

        # ----------------------------------------------------
        # Cancel previous generation
        # ----------------------------------------------------

        if state[
            "cancel_event"
        ] is not None:

            state[
                "cancel_event"
            ].set()

        cancel_event = asyncio.Event()

        state[
            "cancel_event"
        ] = cancel_event

        # ----------------------------------------------------
        # NORMAL
        # ----------------------------------------------------

        if state["mode"] == "normal":

            await status_message.edit_text(
                "⏳ تم تحميل الملف.\n"
                "جاري تحويل النص إلى صوت..."
            )

            try:

                final_file = (
                    await generate_normal_audio(
                        state,
                        text,
                        cancel_event,
                        status_message,
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
                    "Normal TXT TTS failed: %s",
                    e,
                )

                await status_message.edit_text(
                    "❌ حدث خطأ أثناء إنشاء الصوت:\n"
                    f"{e}"
                )

            finally:

                state[
                    "cancel_event"
                ] = None

            return

        # ----------------------------------------------------
        # PODCAST
        # ----------------------------------------------------

        if state["mode"] == "podcast":

            await status_message.edit_text(
                "⏳ تم تحميل ملف الحوار.\n"
                "جاري إنشاء البودكاست..."
            )

            try:

                final_file = (
                    await generate_podcast_audio(
                        state,
                        text,
                        cancel_event,
                        status_message,
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
                    "Podcast TXT failed: %s",
                    e,
                )

                await status_message.edit_text(
                    "❌ حدث خطأ أثناء إنشاء البودكاست:\n"
                    f"{e}"
                )

            finally:

                state[
                    "cancel_event"
                ] = None

    except Exception as e:

        logger.exception(
            "TXT file processing failed: %s",
            e,
        )

        try:

            await status_message.edit_text(
                "❌ تعذر قراءة ملف TXT:\n"
                f"{e}"
            )

        except Exception:

            await update.message.reply_text(
                "❌ تعذر قراءة ملف TXT."
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

    state = get_state(user_id)

    data = query.data

    # --------------------------------------------------------
    # MAIN
    # --------------------------------------------------------

    if data == "back_main":

        state[
            "waiting_for_filename"
        ] = False

        await query.edit_message_text(
            "القائمة الرئيسية:",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # NORMAL MODE
    # --------------------------------------------------------

    if data == "mode_normal":

        state["mode"] = "normal"

        await query.edit_message_text(
            "🎙️ وضع تحويل النص إلى صوت\n\n"
            "أرسل النص أو أرسل ملف TXT ضخم."
        )

        return

    if data == "normal_settings":

        await query.edit_message_text(
            "⚙️ إعدادات النص إلى صوت:",
            reply_markup=normal_settings_menu(),
        )

        return

    if data == "normal_voice":

        await load_voices(state)

        await query.edit_message_text(
            "🌍 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                "normal_ar_voice",
                0,
            ),
        )

        return

    # --------------------------------------------------------
    # Normal Arabic
    # --------------------------------------------------------

    if data.startswith(
        "normal_ar_voice_page|"
    ):

        page = int(
            data.split("|")[1]
        )

        await query.edit_message_text(
            "🌍 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                "normal_ar_voice",
                page,
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
            f"✅ الصوت العربي:\n{voice}\n\n"
            "Auto Language يستخدم هذا الصوت للعربية.",
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

    # --------------------------------------------------------
    # Normal English
    # --------------------------------------------------------

    if data == "normal_en_voice":

        await load_voices(state)

        await query.edit_message_text(
            "🌍 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                "normal_en_voice",
                0,
            ),
        )

        return

    if data.startswith(
        "normal_en_voice_page|"
    ):

        page = int(
            data.split("|")[1]
        )

        await query.edit_message_text(
            "🌍 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                "normal_en_voice",
                page,
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
            f"✅ الصوت الإنجليزي:\n{voice}",
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

    # --------------------------------------------------------
    # Normal rate
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Normal pitch
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Normal volume
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # PODCAST
    # --------------------------------------------------------

    if data == "mode_podcast":

        state["mode"] = "podcast"

        await query.edit_message_text(
            "🎧 وضع البودكاست\n\n"
            "أرسل الحوار أو ملف TXT.\n\n"
            "كل سطر = مداخلة واحدة.\n"
            "السطر الأول للمتحدث الأول.\n"
            "السطر الثاني للمتحدث الثاني.\n"
            "ثم بالتناوب.\n\n"
            "يمكنك استخدام:\n"
            "[PAUSE:SHORT]\n"
            "[PAUSE:MEDIUM]\n"
            "[PAUSE:LONG]"
        )

        return

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

    # --------------------------------------------------------
    # Speaker voice
    # --------------------------------------------------------

    if data in (
        "speaker_voice_1",
        "speaker_voice_2",
    ):

        speaker_number = int(
            data.split("_")[-1]
        )

        await load_voices(state)

        await query.edit_message_text(
            "🌍 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                f"speaker{speaker_number}_ar_voice",
                0,
            ),
        )

        return

    # --------------------------------------------------------
    # Speaker Arabic page
    # --------------------------------------------------------

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
            "🌍 الأصوات العربية:",
            reply_markup=voice_pages(
                state["arabic_voices"],
                f"speaker{speaker_number}_ar_voice",
                page,
            ),
        )

        return

    # --------------------------------------------------------
    # Speaker Arabic set
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Speaker Auto
    # --------------------------------------------------------

    match = re.match(
        r"speaker(\d+)_ar_voice_auto",
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

    # --------------------------------------------------------
    # Speaker English
    # --------------------------------------------------------

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
            "🌍 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                f"speaker{speaker_number}_en_voice",
                0,
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
            "🌍 الأصوات الإنجليزية:",
            reply_markup=voice_pages(
                state["english_voices"],
                f"speaker{speaker_number}_en_voice",
                page,
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

    # --------------------------------------------------------
    # Speaker rate
    # --------------------------------------------------------

    match = re.match(
        r"speaker_rate_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await query.edit_message_text(
            f"⚡ سرعة المتحدث {speaker_number}:",
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

        speaker[
            "rate"
        ] = value

        await query.edit_message_text(
            f"✅ سرعة المتحدث {speaker_number}: {value}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # --------------------------------------------------------
    # Speaker pitch
    # --------------------------------------------------------

    match = re.match(
        r"speaker_pitch_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await query.edit_message_text(
            f"↕️ نبرة المتحدث {speaker_number}:",
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

        speaker[
            "pitch"
        ] = value

        await query.edit_message_text(
            f"✅ نبرة المتحدث {speaker_number}: {value}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # --------------------------------------------------------
    # Speaker volume
    # --------------------------------------------------------

    match = re.match(
        r"speaker_volume_(\d+)$",
        data,
    )

    if match:

        speaker_number = int(
            match.group(1)
        )

        await query.edit_message_text(
            f"🔉 مستوى صوت المتحدث {speaker_number}:",
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

        speaker[
            "volume"
        ] = value

        await query.edit_message_text(
            f"✅ مستوى صوت المتحدث {speaker_number}: {value}",
            reply_markup=speaker_settings_menu(
                speaker_number
            ),
        )

        return

    # ========================================================
    # PARALLEL SETTINGS
    # ========================================================

    if data == "parallel_settings":

        await query.edit_message_text(
            "⚡ سرعة المعالجة\n\n"
            "اختر عدد قنوات Edge TTS التي تعمل "
            "بالتوازي.\n\n"
            "كلما زاد العدد قد يتم إنشاء المقاطع "
            "بسرعة أكبر، وسيتم الحفاظ على ترتيبها "
            "عند الدمج النهائي.",
            reply_markup=parallel_settings_menu(
                state
            ),
        )

        return

    if data.startswith(
        "parallel_set|"
    ):

        value = int(
            data.split("|")[1]
        )

        if value not in ALLOWED_CHANNELS:
            return

        state[
            "parallel_channels"
        ] = value

        await query.edit_message_text(
            f"✅ تم اختيار {value} "
            f"قناة متوازية.",
            reply_markup=main_menu(),
        )

        return

    # ========================================================
    # FILENAME SETTINGS
    # ========================================================

    if data == "filename_settings":

        current = state.get(
            "filename_base",
            "audio",
        )

        serial_text = (
            "مفعّل"
            if state["serial_enabled"]
            else "متوقف"
        )

        await query.edit_message_text(
            "📁 إعدادات الملف الناتج\n\n"
            f"الاسم الأساسي الحالي: {current}\n"
            f"الترقيم: {serial_text}\n\n"
            "مثال عند تشغيل الترقيم:\n"
            f"{safe_filename(current)}_001.mp3\n"
            f"{safe_filename(current)}_002.mp3\n"
            f"{safe_filename(current)}_003.mp3",
            reply_markup=filename_settings_menu(
                state
            ),
        )

        return

    if data == "filename_custom":

        state[
            "waiting_for_filename"
        ] = True

        await query.edit_message_text(
            "✏️ أرسل الآن اسم الملف الأساسي.\n\n"
            "مثال:\n"
            "محاضرات\n\n"
            "وسيصبح الناتج:\n"
            "محاضرات_001.mp3\n"
            "محاضرات_002.mp3\n"
            "محاضرات_003.mp3"
        )

        return

    if data == "filename_toggle_serial":

        state[
            "serial_enabled"
        ] = not state[
            "serial_enabled"
        ]

        await query.edit_message_text(
            "📁 تم تغيير نظام الترقيم.",
            reply_markup=filename_settings_menu(
                state
            ),
        )

        return

    if data == "filename_reset":

        state[
            "filename_base"
        ] = "audio"

        state[
            "serial_enabled"
        ] = True

        await query.edit_message_text(
            "✅ تم إعادة إعدادات اسم الملف الافتراضية:\n\n"
            "audio_001.mp3\n"
            "audio_002.mp3\n"
            "audio_003.mp3",
            reply_markup=filename_settings_menu(
                state
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
        update.message.text
        or ""
    ).strip()

    if not text:
        return

    # --------------------------------------------------------
    # Custom filename
    # --------------------------------------------------------

    if state[
        "waiting_for_filename"
    ]:

        state[
            "filename_base"
        ] = safe_filename(text)

        state[
            "waiting_for_filename"
        ] = False

        await update.message.reply_text(
            "✅ تم حفظ اسم الملف:\n\n"
            f"{state['filename_base']}\n\n"
            "ومع الترقيم سيكون مثلًا:\n"
            f"{state['filename_base']}_001.mp3\n"
            f"{state['filename_base']}_002.mp3\n"
            f"{state['filename_base']}_003.mp3",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # No mode
    # --------------------------------------------------------

    if state["mode"] is None:

        await update.message.reply_text(
            "اختر أولًا نوع العملية:",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # Cancel previous generation
    # --------------------------------------------------------

    if state[
        "cancel_event"
    ] is not None:

        state[
            "cancel_event"
        ].set()

    cancel_event = asyncio.Event()

    state[
        "cancel_event"
    ] = cancel_event

    # ========================================================
    # NORMAL
    # ========================================================

    if state["mode"] == "normal":

        status_message = (
            await update.message.reply_text(
                "⏳ جاري تجهيز النص..."
            )
        )

        try:

            final_file = (
                await generate_normal_audio(
                    state,
                    text,
                    cancel_event,
                    status_message,
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
                "⏳ جاري تجهيز البودكاست..."
            )
        )

        try:

            final_file = (
                await generate_podcast_audio(
                    state,
                    text,
                    cancel_event,
                    status_message,
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

            state[
                "cancel_event"
            ] = None

        return


# ============================================================
# /CANCEL
# ============================================================

async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = (
        update.effective_user.id
    )

    state = get_state(user_id)

    if state[
        "cancel_event"
    ] is not None:

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
# /PROMPT
# ============================================================

async def prompt_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        PODCAST_AI_PROMPT
    )


# ============================================================
# /HELP
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

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    # --------------------------------------------------------
    # TXT FILES
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.FileExtension(
                "txt"
            ),
            document_handler,
        )
    )

    # --------------------------------------------------------
    # Other documents
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.Document.ALL,
            document_handler,
        )
    )

    # --------------------------------------------------------
    # Text
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


if __name__ == "__main__":
    main()
