import logging
import re
import httpx
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

class YandexSpeechKitService:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.api_key = settings.yandex_api_key
        self.folder_id = settings.yandex_folder_id
        self._http_client = http_client
        self._owns_client = False

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

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
            client = self._get_client()
            response = await client.post(url, headers=headers, params=params, content=audio_data)
            if response.status_code == 200:
                result = response.json()
                return result.get("result", "").strip()
            logger.error("STT error %s: %s", response.status_code, response.text)
        except Exception as e:
            logger.error("STT request failed: %s", e)

        return None

    @staticmethod
    def clean_text_for_tts(text: str) -> str:
        if not text:
            return ""
        t = text
        t = re.sub(r"\[x\]", "Выполнено: ", t, flags=re.IGNORECASE)
        t = re.sub(r"\[ \]", "Задача: ", t)
        t = re.sub(r"\(🔄\s*([^)]+)\)", r"повторяется \1", t)
        t = re.sub(r"[\*\_`]", "", t)
        t = re.sub(r"^[\s•\-–—]+\s*", "", t, flags=re.MULTILINE)
        t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
        t = re.sub(r"[\u2000-\u32ff]", "", t)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n\s*\n+", "\n", t)
        return t.strip()

    async def text_to_speech(self, text: str, voice: str = "marina", emotion: str = "friendly") -> Optional[bytes]:
        if not self.api_key or not self.folder_id:
            logger.warning("SpeechKit API key not set")
            return None

        clean_text = self.clean_text_for_tts(text) or text
        url = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
        headers = {
            "Authorization": f"Api-Key {self.api_key}"
        }
        data = {
            "text": clean_text,
            "lang": "ru-RU",
            "voice": voice,
            "emotion": emotion,
            "speed": "1.0",
            "format": "oggopus",
            "folderId": self.folder_id
        }

        try:
            client = self._get_client()
            response = await client.post(url, headers=headers, data=data)
            if response.status_code == 200:
                return response.content
            logger.error("TTS error %s: %s", response.status_code, response.text)
        except Exception as e:
            logger.error("TTS request failed: %s", e)

        return None
