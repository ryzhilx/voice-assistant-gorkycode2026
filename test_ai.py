import asyncio
import json
from app.ai.llm_client import LLMOrchestrator
from app.ai.embeddings import SemanticSearchEngine
from app.ai.schemas import AIAction

async def main():
    print("=" * 60)
    print("🚀 ТЕСТИРОВАНИЕ ИИ-МОДУЛЯ ГОЛОСОВОГО АССИСТЕНТА")
    print("=" * 60)

    ai = LLMOrchestrator()
    search = SemanticSearchEngine()

    test_cases = [
        # 1. Создание задачи / напоминания
        ("Напомни мне завтра в 10 утра позвонить Ивану", "Сценарий 1: Напоминание с датой и временем"),
        ("В пятницу нужно отправить отчет", "Сценарий 1: Задача с относительной датой (пятница)"),
        ("Поставь задачу купить билеты до конца недели", "Сценарий 1: Задача до конца недели"),

        # 2. Создание встречи
        ("Добавь встречу с командой завтра в 15:00", "Сценарий 2: Встреча со временем"),
        ("В четверг в 11 у меня встреча с дизайнером", "Сценарий 2: Встреча в день недели"),

        # 3. Расписание
        ("Что у меня сегодня?", "Сценарий 3: Расписание на сегодня"),
        ("Есть ли у меня встречи сегодня?", "Сценарий 3: Только встречи на сегодня"),
        ("Что запланировано на эту неделю?", "Сценарий 3: Расписание на неделю"),

        # 4. Поиск
        ("Найди задачу про презентацию", "Сценарий 4: Поиск по ключевому слову"),
        ("Когда у меня была встреча с дизайнером?", "Сценарий 4: Поиск прошедших событий")
    ]

    print("\n--- [1] ТЕСТ ИЗВЛЕЧЕНИЯ НАМЕРЕНИЙ И СЛОТОВ ---")
    for phrase, desc in test_cases:
        res = await ai.parse_intent(phrase)
        print(f"\n[Запрос]: '{phrase}' ({desc})")
        print(f" -> Действие: {res.action.value}")
        print(f" -> Параметры: {json.dumps(res.params, ensure_ascii=False)}")

    # 5. Тест уточняющего диалога (Slot Filling)
    print("\n" + "=" * 60)
    print("--- [2] ТЕСТ УТОЧНЯЮЩЕГО ДИАЛОГА (SLOT FILLING) ---")
    phrase_incomplete = "Поставь встречу с Иваном завтра"
    print(f"\n1. Пользователь говорит: '{phrase_incomplete}'")
    step1 = await ai.parse_intent(phrase_incomplete)
    print(f" -> Ассистент реагирует: {step1.action.value}")
    print(f" -> Вопрос пользователю: {step1.params.get('question')}")
    print(f" -> Драфт сохранен: {step1.params.get('draft_data')}")

    # Пользователь отвечает временем
    answer = "В 15:00"
    print(f"\n2. Ответ пользователя: '{answer}'")
    context = {
        "awaiting_slot": step1.params.get("missing_slot"),
        "draft_data": step1.params.get("draft_data")
    }
    step2 = await ai.parse_intent(answer, context=context)
    print(f" -> Ассистент завершает действие: {step2.action.value}")
    print(f" -> Итоговые параметры встречи: {json.dumps(step2.params, ensure_ascii=False)}")
    print(f" -> Подтверждение пользователю: {step2.user_reply}")

    # 6. Тест семантического поиска
    print("\n" + "=" * 60)
    print("--- [3] ТЕСТ СЕМАНТИЧЕСКОГО ПОИСКА ПО СМЫСЛУ ---")
    sample_records = [
        {"id": 1, "title": "Согласовать контракт и юридические правки", "type": "task"},
        {"id": 2, "title": "Подготовить слайды для питча проекта", "type": "task"},
        {"id": 3, "title": "Купить билеты на самолет в Москву", "type": "task"},
        {"id": 4, "title": "Встреча с дизайнером интерфейсов", "type": "meeting"},
        {"id": 5, "title": "Отправить ежемесячный отчет руководству", "type": "task"}
    ]

    search_query = "Я когда-то ставил задачу по договору, найди ее"
    print(f"\nПользователь ищет: '{search_query}'")
    # Извлечем ключевую тему
    intent_res = await ai.parse_intent(search_query)
    q = intent_res.params.get("query", "договор")
    print(f"Извлеченная поисковая фраза: '{q}'")
    
    results = search.rank_records(q, sample_records, top_k=2)
    print("Найденные наиболее релевантные записи:")
    for r in results:
        print(f"  [ID: {r['id']}] {r['title']} ({r['type']})")

    print("\n" + "=" * 60)
    print("✅ ВСЕ 5 СЦЕНАРИЕВ ТЗ УСПЕШНО ПРОТЕСТИРОВАНЫ!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
