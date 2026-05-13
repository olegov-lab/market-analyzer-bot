import io
import tempfile
import os
from loguru import logger


async def transcribe_voice(file_bytes: bytes, api_key: str = "") -> str | None:
    """Transcribe OGG voice message. Uses Whisper API if key provided, else Google Speech."""
    # Try OpenAI Whisper first if key available
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            buf = io.BytesIO(file_bytes)
            buf.name = "voice.ogg"
            transcript = client.audio.transcriptions.create(
                model="whisper-1", file=buf, language="ru",
            )
            text = transcript.text.strip()
            if text:
                logger.info("Whisper transcription: {} chars", len(text))
                return text
        except Exception as e:
            logger.warning("Whisper failed, falling back to Google: {}", e)

    # Fallback: Google Speech Recognition (free, no key needed)
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            import subprocess, shutil
            wav_path = tmp_path.replace(".ogg", ".wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path, "-ar", "16000", "-ac", "1", wav_path],
                capture_output=True, timeout=30,
            )
            if os.path.exists(wav_path):
                with sr.AudioFile(wav_path) as source:
                    audio = recognizer.record(source)
                text = recognizer.recognize_google(audio, language="ru-RU")
                os.unlink(wav_path)
                os.unlink(tmp_path)
                if text:
                    logger.info("Google STT: {} chars", len(text))
                    return text
        except Exception:
            pass
        finally:
            if os.path.exists(tmp_path):
                try: os.unlink(tmp_path)
                except: pass
    except ImportError:
        logger.warning("speech_recognition not installed")

    return None
