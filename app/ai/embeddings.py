import math
import logging
import re
import httpx
from typing import List, Optional, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)

class SemanticSearchEngine:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.yandex_api_key = settings.yandex_api_key
        self.yandex_folder_id = settings.yandex_folder_id
        self._http_client = http_client
        self._owns_client = False

    def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
            self._owns_client = True
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    @staticmethod
    def stem_word(w: str) -> str:
        w = w.lower()
        if len(w) <= 3:
            return w
        return re.sub(r'(?:ами|ями|иями|ов|ев|ей|ам|ям|иям|ом|ем|ой|ей|ею|ах|ях|иях|ую|юю|ая|яя|ое|ее|ые|ие|ый|ий|ой|ого|его|ому|ему|ым|им|ыми|ими|а|я|у|ю|о|е|ы|и|ь|й)$', '', w)

    async def get_embedding(self, text: str) -> List[float]:
        if self.yandex_api_key and self.yandex_folder_id:
            try:
                emb = await self._get_yandex_embedding(text)
                if emb:
                    return emb
            except Exception as e:
                logger.warning("Failed to fetch Yandex embedding: %s", e)

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
        client = self._get_client()
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            return resp.json().get("embedding")
        return None

    def _local_vectorize(self, text: str, dim: int = 256) -> List[float]:
        vec = [0.0] * dim
        if not text:
            return vec

        synonyms = {
            "договор": ["контракт", "соглашение", "сделка", "подписание"],
            "презентация": ["слайды", "питч", "демо", "выступление"],
            "отчет": ["справка", "аналитика", "документ", "статистика"],
            "встреча": ["созвон", "митинг", "синк", "обсуждение"],
            "бюджет": ["финансы", "деньги", "расходы", "смета"]
        }
        stopwords = {
            "и", "в", "во", "не", "на", "с", "со", "по", "к", "ко", "о", "об", "обо",
            "у", "из", "за", "от", "до", "для", "про", "а", "но", "мне", "я", "ее", "его", "их"
        }
        stemmed_syns = {self.stem_word(k): [self.stem_word(s) for s in v] for k, v in synonyms.items()}

        raw_tokens = [t for t in re.sub(r"[^a-zA-Zа-яА-Я0-9]", " ", str(text).lower()).split() if t not in stopwords and len(t) > 1]
        expanded_tokens = list(raw_tokens)

        for t in raw_tokens:
            st = self.stem_word(t)
            expanded_tokens.append(st)
            for s_root, s_list in stemmed_syns.items():
                if st == s_root or st in s_list or s_root in st or any(sl in st for sl in s_list):
                    expanded_tokens.extend(s_list)
                    expanded_tokens.append(s_root)

        for token in expanded_tokens:
            h = abs(hash(token)) % dim
            vec[h] += 1.0
            for i in range(len(token) - 2):
                h_ng = abs(hash(token[i:i+3])) % dim
                vec[h_ng] += 0.5

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    @staticmethod
    def cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0

        dot = sum(a * b for a, b in zip(v1, v2))
        norm_a = math.sqrt(sum(a * a for a in v1))
        norm_b = math.sqrt(sum(b * b for b in v2))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def rank_records(self, query: str, records: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        if not query or not records:
            return []

        query_vec = self._local_vectorize(str(query))
        scored = []

        for rec in records:
            emb = rec.get("embedding")
            if not emb:
                emb = self._local_vectorize(rec.get("title", ""))
            score = self.cosine_similarity(query_vec, emb)
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k] if item[0] > 0.20]

