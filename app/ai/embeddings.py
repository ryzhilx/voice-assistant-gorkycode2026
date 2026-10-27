import asyncio
import json
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
        self._embedding_cache: Dict[str, List[float]] = {}
        self._embedding_semaphore = asyncio.Semaphore(5)

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
        remote = await self.get_remote_embedding(text, model="text-search-query")
        if remote:
            return remote

        return self._local_vectorize(text)

    async def get_remote_embedding(self, text: str, model: str = "text-search-query") -> Optional[List[float]]:
        if not (self.yandex_api_key and self.yandex_folder_id):
            return None
        try:
            return await self._get_yandex_embedding(text, model=model)
        except Exception as e:
            logger.warning("Failed to fetch Yandex embedding: %s", e)
            return None

    async def _get_yandex_embedding(self, text: str, model: str = "text-search-query") -> Optional[List[float]]:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
        headers = {
            "Authorization": f"Api-Key {self.yandex_api_key}",
            "x-folder-id": self.yandex_folder_id
        }
        payload = {
            "modelUri": f"emb://{self.yandex_folder_id}/{model}/latest",
            "text": text
        }
        client = self._get_client()
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code == 200:
            embedding = resp.json().get("embedding")
            if isinstance(embedding, list) and embedding:
                return embedding
            return None
        logger.warning("Yandex embedding error %s: %s", resp.status_code, resp.text)
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
            "бюджет": ["финансы", "деньги", "расходы", "смета"],
            "пить": ["выпить", "попить", "выпил", "выпила", "вода", "воды", "воду"],
            "позвонить": ["набрать", "созвониться", "позвонил", "позвонила", "набрал", "набрала", "звонок"],
            "купить": ["взять", "приобрести", "купил", "купила", "покупка"],
            "сделать": ["выполнить", "подготовить", "сделал", "сделала", "выполнил", "выполнила"],
            "отправить": ["отослать", "переслать", "выслать", "отправил", "отправила", "выслал", "выслала"]
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

    def _score_local(self, query: str, records: List[Dict[str, Any]]) -> List[tuple]:
        query_vec = self._local_vectorize(str(query))
        scored = []

        for rec in records:
            embedding = rec.get("embedding")
            if isinstance(embedding, str):
                try:
                    embedding = json.loads(embedding)
                except (TypeError, ValueError):
                    embedding = None
            if not isinstance(embedding, list) or not embedding:
                embedding = self._local_vectorize(rec.get("title", ""))
            score = self.cosine_similarity(query_vec, embedding)
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def rank_records(self, query: str, records: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        if not query or not records:
            return []

        scored = self._score_local(query, records)
        return [item[1] for item in scored[:top_k] if item[0] > 0.20]

    async def _document_embedding(self, record: Dict[str, Any]) -> Optional[List[float]]:
        title = str(record.get("title") or "").strip()
        if not title:
            return None

        embedding = record.get("embedding")
        if isinstance(embedding, str):
            try:
                embedding = json.loads(embedding)
            except (TypeError, ValueError):
                embedding = None
        if isinstance(embedding, list) and embedding:
            return embedding

        cached = self._embedding_cache.get(title)
        if cached:
            return cached

        async with self._embedding_semaphore:
            remote = await self.get_remote_embedding(title, model="text-search-doc")
        if remote:
            if len(self._embedding_cache) >= 512:
                self._embedding_cache.pop(next(iter(self._embedding_cache)))
            self._embedding_cache[title] = remote
        return remote

    async def rank_records_async(
        self,
        query: str,
        records: List[Dict[str, Any]],
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        if not query or not records:
            return []

        local_scored = self._score_local(query, records)
        fallback = [item[1] for item in local_scored[:top_k] if item[0] > 0.20]

        if not (self.yandex_api_key and self.yandex_folder_id):
            return fallback

        query_embedding = await self.get_remote_embedding(query, model="text-search-query")
        if not query_embedding:
            return fallback

        candidate_limit = min(len(records), max(top_k * 5, 20))
        candidates = local_scored[:candidate_limit]
        document_embeddings = await asyncio.gather(
            *[self._document_embedding(record) for _, record in candidates]
        )

        combined = []
        for (local_score, record), document_embedding in zip(candidates, document_embeddings):
            semantic_score = 0.0
            if document_embedding:
                semantic_score = max(
                    0.0,
                    self.cosine_similarity(query_embedding, document_embedding)
                )
            score = 0.5 * local_score + 0.5 * semantic_score
            combined.append((score, record))

        combined.sort(key=lambda item: item[0], reverse=True)
        reranked = [item[1] for item in combined[:top_k] if item[0] > 0.20]
        return reranked or fallback

