import logging
import httpx
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

class YandexSpeechKitService:
    """
    Сервис для распознавания речи (STT) и синтеза речи (TTS) через Yandex SpeechKit API.
    """

    def __init__(self):
        self.api_key = settings.yandex_api_key
        self.folder_id = settings.yandex_folder_id

    async def speech_to_text(self, audio_data: bytes, format: str = "oggopus") -> Optional[str]:
        """
        Преобразует аудиофайл (по умолчанию Telegram voice note .ogg/Opus) в текст.
        """
        if not self.api_key or not self.folder_id:
            logger.warning("Yandex SpeechKit API Key not configured. Using mock STT.")
            return "Напомни мне завтра в 10 утра позвонить Ивану"

        url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "x-folder-id": self.folder_id
        }
        params = {
            "lang": "ru-RU",
            "topic": "general",
            "format": format
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, params=params, content=audio_data)
                if response.status_code == 200:
                    result = response.json()
                    recognized_text = result.get("result", "").strip()
                    logger.info(f"SpeechKit STT recognized: '{recognized_text}'")
                    return recognized_text
                else:
                    logger.error(f"SpeechKit STT failed [{response.status_code}]: {response.text}")
        except Exception as e:
            logger.error(f"Error during SpeechKit STT: {e}")

        return None

    async def text_to_speech(self, text: str, voice: str = "marina", emotion: str = "friendly") -> Optional[bytes]:
        """
        Синтезирует русский текст в аудиопоток формата OGG (Opus).
        """
        if not self.api_key or not self.folder_id:
            logger.warning("Yandex SpeechKit API Key not configured. Skipping TTS audio generation.")
            return None

        url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
        headers = {
            "Authorization": f"Api-Key {self.api_key}"
        }
        data = {
            "text": text,
            "lang": "ru-RU",
            "voice": voice,
            "emotion": emotion,
            "speed": "1.0",
            "format": "oggopus",
            "folderId": self.folder_id
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, data=data)
                if response.status_code == 200:
                    logger.info(f"SpeechKit TTS generated audio ({len(response.content)} bytes)")
                    return response.content
                else:
                    logger.error(f"SpeechKit TTS failed [{response.status_code}]: {response.text}")
        except Exception as e:
            logger.error(f"Error during SpeechKit TTS: {e}")

        return None
