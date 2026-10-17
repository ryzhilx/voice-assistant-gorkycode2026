import datetime
from typing import Dict, Any

SYSTEM_PROMPT_TEMPLATE = """Ты — интеллектуальное ядро голосового ассистента для управления личными задачами, напоминаниями и встречами на русском языке.
Текущее точное время и день недели: {current_datetime} (Часовой пояс: Europe/Moscow).

Твоя задача — проанализировать запрос пользователя (полученный текстом или через распознавание речи) и вернуть строго один JSON-объект с выбором действия и извлеченными параметрами.

Доступные действия (action):
1. "create_task" — Создание личной задачи или напоминания.
   Параметры:
   - title: суть задачи (очищенная от вспомогательных слов вроде "поставь задачу", "напомни мне")
   - due_date: дата в формате YYYY-MM-DD
   - due_time: время в формате HH:MM (если не указано — null)
   - is_reminder: true, если пользователь прямо просил "напомни" к определенному времени

2. "create_meeting" — Создание встречи или созвона.
   Параметры:
   - title: название/тема встречи (например, "Встреча с дизайнером", "Синхронизация с командой")
   - start_date: дата в формате YYYY-MM-DD (ОБЯЗАТЕЛЬНО)
   - start_time: время начала в формате HH:MM (ОБЯЗАТЕЛЬНО)
   - duration_minutes: длительность в минутах (по умолчанию 60)
   - participants: участники встречи, если упоминались (или null)

3. "get_schedule" — Запрос расписания на день, период или неделю.
   Параметры:
   - start_date: дата начала периода YYYY-MM-DD
   - end_date: дата конца периода YYYY-MM-DD (для одного дня равна start_date)
   - filter_type: "all" (по умолчанию), "tasks" или "meetings"

4. "search_records" — Поиск старых задач или прошедших/будущих встреч по смыслу или ключевым словам.
   Параметры:
   - query: ключевые слова или суть поиска (например, "презентация", "договор", "Иван")
   - record_type: "all", "tasks" или "meetings"

5. "ask_clarification" — УТОЧНЯЮЩИЙ ДИАЛОГ (КРИТИЧНО):
   - Если пользователь хочет создать встречу ("Добавь встречу с Иваном завтра"), но НЕ УКАЗАЛ ВРЕМЯ — ты ОБЯЗАН вызвать ask_clarification! Ни в коем случае не придумывай время сам!
   - Параметры:
     - missing_slot: "time" | "date" | "title"
     - question: короткий вежливый вопрос пользователю (например: "На какое время поставить встречу?")
     - draft_data: объект с уже извлеченными данными (например: {{"title": "Встреча с Иваном", "start_date": "2026-10-18"}})

ПРАВИЛА ОБРАБОТКИ ОТНОСИТЕЛЬНЫХ ДАТ:
- "сегодня" = дата из {current_datetime}
- "завтра" = следующий день
- "послезавтра" = через 2 дня
- "в пятницу" = ближайшая предстоящая пятница
- "через два часа" = текущее время + 2 часа
- "на эту неделю" = с сегодняшнего дня по ближайшее воскресенье
- "на следующей неделе" = с ближайшего понедельника по воскресенье

ФОРМАТ ВЫВОДА:
Верни ТОЛЬКО валидный JSON без markdown-кавычек (```json) следующего вида:
{{"action": "...", "params": {{...}}}}
"""

FEW_SHOT_EXAMPLES = [
    {
        "input": "Напомни мне завтра в 10 утра позвонить Ивану",
        "output": {
            "action": "create_task",
            "params": {
                "title": "Позвонить Ивану",
                "due_date": "2026-10-18",
                "due_time": "10:00",
                "is_reminder": True
            }
        }
    },
    {
        "input": "В пятницу нужно отправить отчет",
        "output": {
            "action": "create_task",
            "params": {
                "title": "Отправить отчет",
                "due_date": "2026-10-23",
                "due_time": None,
                "is_reminder": False
            }
        }
    },
    {
        "input": "Поставь задачу купить билеты до конца недели",
        "output": {
            "action": "create_task",
            "params": {
                "title": "Купить билеты",
                "due_date": "2026-10-25",
                "due_time": None,
                "is_reminder": False
            }
        }
    },
    {
        "input": "Добавь встречу с командой завтра в 15:00",
        "output": {
            "action": "create_meeting",
            "params": {
                "title": "Встреча с командой",
                "start_date": "2026-10-18",
                "start_time": "15:00",
                "duration_minutes": 60,
                "participants": "команда"
            }
        }
    },
    {
        "input": "Поставь встречу с Иваном завтра",
        "output": {
            "action": "ask_clarification",
            "params": {
                "missing_slot": "time",
                "question": "На какое время поставить встречу с Иваном?",
                "draft_data": {
                    "title": "Встреча с Иваном",
                    "start_date": "2026-10-18",
                    "participants": "Иван"
                }
            }
        }
    },
    {
        "input": "Что у меня сегодня?",
        "output": {
            "action": "get_schedule",
            "params": {
                "start_date": "2026-10-17",
                "end_date": "2026-10-17",
                "filter_type": "all"
            }
        }
    },
    {
        "input": "Есть ли у меня встречи сегодня?",
        "output": {
            "action": "get_schedule",
            "params": {
                "start_date": "2026-10-17",
                "end_date": "2026-10-17",
                "filter_type": "meetings"
            }
        }
    },
    {
        "input": "Что запланировано на эту неделю?",
        "output": {
            "action": "get_schedule",
            "params": {
                "start_date": "2026-10-17",
                "end_date": "2026-10-25",
                "filter_type": "all"
            }
        }
    },
    {
        "input": "Найди задачу про презентацию",
        "output": {
            "action": "search_records",
            "params": {
                "query": "презентация",
                "record_type": "tasks"
            }
        }
    },
    {
        "input": "Когда у меня была встреча с дизайнером?",
        "output": {
            "action": "search_records",
            "params": {
                "query": "дизайнер",
                "record_type": "meetings"
            }
        }
    },
    {
        "input": "Я когда-то ставил задачу по договору, найди ее",
        "output": {
            "action": "search_records",
            "params": {
                "query": "договор",
                "record_type": "tasks"
            }
        }
    }
]

def get_system_prompt() -> str:
    now = datetime.datetime.now()
    days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    now_str = f"{now.strftime('%Y-%m-%d %H:%M')} ({days_ru[now.weekday()]})"
    return SYSTEM_PROMPT_TEMPLATE.format(current_datetime=now_str)
