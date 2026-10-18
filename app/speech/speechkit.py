import logging
import httpx
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

class YandexSpeechKitService:
    def __init__(self):
        self.api_key = settings.yandex_api_key
        self.folder_id = settings.yandex_folder_id

    async def speech_to_text(self, audio_data: bytes, format: str = "oggopus") -> Optional[str]:
        if not self.api_key or not self.folder_id:
            logger.warning("SpeechKit API key not set")
            return None

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
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, params=params, content=audio_data)
                if response.status_code == 200:
                    result = response.json()
                    return result.get("result", "").strip()
                logger.error("STT error %s: %s", response.status_code, response.text)
        except Exception as e:
            logger.error("STT request failed: %s", e)

        return None

    async def text_to_speech(self, text: str, voice: str = "marina", emotion: str = "friendly") -> Optional[bytes]:
        if not self.api_key or not self.folder_id:
            logger.warning("SpeechKit API key not set")
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
                    return response.content
                logger.error("TTS error %s: %s", response.status_code, response.text)
        except Exception as e:
            logger.error("TTS request failed: %s", e)

        return None
