import os
import tempfile
import edge_tts

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# قراءة التوكن من Faable Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 البوت يعمل بنجاح!\n\n"
        "أرسل لي أي نص، وسأحوله إلى صوت."
    )


async def text_to_speech(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text

    await update.message.reply_text("⏳ جاري تحويل النص إلى صوت...")

    output_file = None

    try:
        # ملف مؤقت
        with tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
        ) as f:
            output_file = f.name

        # Edge TTS
        communicate = edge_tts.Communicate(
            text=text,
            voice="ar-EG-ShakirNeural"
        )

        await communicate.save(output_file)

        # إرسال الصوت إلى Telegram
        with open(output_file, "rb") as audio:
            await update.message.reply_audio(
                audio=audio,
                title="TTS Test",
                performer="Edge TTS"
            )

    except Exception as e:

        await update.message.reply_text(
            f"❌ حدث خطأ:\n{e}"
        )

    finally:

        if output_file and os.path.exists(output_file):
            os.remove(output_file)


def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "❌ BOT_TOKEN غير موجود في Faable Variables"
        )

    print("🚀 Telegram TTS Bot starting...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_to_speech
        )
    )

    print("✅ Bot is running")

    app.run_polling()


if __name__ == "__main__":
    main()
