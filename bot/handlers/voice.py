import io
from loguru import logger
from openai import OpenAI


async def transcribe_voice(file_bytes: bytes, api_key: str) -> str | None:
    """Transcribe OGG voice message using OpenAI Whisper API."""
    if not api_key:
        logger.warning("No OpenAI API key for voice transcription")
        return None
    try:
        client = OpenAI(api_key=api_key)
        buf = io.BytesIO(file_bytes)
        buf.name = "voice.ogg"
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            language="ru",
        )
        text = transcript.text.strip()
        logger.info("Whisper transcription: {} chars", len(text))
        return text if text else None
    except Exception as e:
        logger.error("Whisper transcription error: {}", e)
        return None
