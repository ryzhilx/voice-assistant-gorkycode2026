import math
import logging
import httpx
from typing import List, Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

class SemanticSearchEngine:
    """
    Модуль семантического поиска записей по смыслу (на базе эмбеддингов Yandex / чистого Python-векторизатора).
    Не требует сторонних C-библиотек (numpy) и работает на любой версии Python.
    """

    def __init__(self):
        self.yandex_api_key = settings.yandex_api_key
        self.yandex_folder_id = settings.yandex_folder_id

    async def get_embedding(self, text: str) -> List[float]:
        """Получить векторное представление текста."""
        if self.yandex_api_key and self.yandex_folder_id:
            try:
                emb = await self._get_yandex_embedding(text)
                if emb:
                    return emb
            except Exception as e:
                logger.error(f"Error fetching Yandex embedding: {e}")

        # Локальный легковесный векторизатор на основе n-грамм и семантических связей
        return self._local_vectorize(text)

    async def _get_yandex_embedding(self, text: str) -> Optional[List[float]]:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
        headers = {
            "Authorization": f"Api-Key {self.yandex_api_key}",
            "x-folder-id": self.yandex_folder_id
        }
        payload = {
            "modelUri": f"emb://{self.yandex_folder_id}/text-search-query/latest",
            "text": text
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return resp.json().get("embedding")
        return None

    def _local_vectorize(self, text: str, dim: int = 128) -> List[float]:
        """
        Локальный хеширующий векторизатор с синонимическим расширением для русского языка.
        Позволяет находить семантически близкие фразы (договор <-> соглашение / контракт).
        """
        synonyms = {
            "договор": ["контракт", "соглашение", "сделка", "подписание"],
            "презентация": ["слайды", "питч", "демо", "выступление"],
            "отчет": ["справка", "аналитика", "документ", "статистика"],
            "встреча": ["созвон", "митинг", "синк", "обсуждение"]
        }

        vec = [0.0] * dim
        tokens = text.lower().replace(",", " ").replace(".", " ").split()

        expanded_tokens = list(tokens)
        for t in tokens:
            for root, syns in synonyms.items():
                if root in t or any(s in t for s in syns):
                    expanded_tokens.extend(syns)
                    expanded_tokens.append(root)

        for token in expanded_tokens:
            h = abs(hash(token)) % dim
            vec[h] += 1.0
            # 3-граммы
            for i in range(len(token) - 2):
                h_ng = abs(hash(token[i:i+3])) % dim
                vec[h_ng] += 0.5

        # Нормализация вектора
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        """Расчет косинусного сходства между двумя векторами (чистый Python)."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0

        dot = sum(a * b for a, b in zip(v1, v2))
        norm_a = math.sqrt(sum(a * a for a in v1))
        norm_b = math.sqrt(sum(b * b for b in v2))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def rank_records(self, query: str, records: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Ранжирует список записей по релевантности запросу.
        Каждая запись должна содержать 'title' и опционально 'embedding'.
        """
        query_vec = self._local_vectorize(query)
        scored = []

        for rec in records:
            emb = rec.get("embedding")
            if not emb:
                emb = self._local_vectorize(rec.get("title", ""))
            
            score = self.cosine_similarity(query_vec, emb)
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k] if item[0] > 0.15]
