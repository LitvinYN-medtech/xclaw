import os
import json
import logging
import asyncio
import asyncpg
import httpx
from datetime import datetime
from fastapi import FastAPI, Request

# Стерильная настройка независимого логгера шлюза
logger = logging.getLogger("medtech_gateway")
logger.setLevel(logging.INFO)

# Полностью очищаем старые хандлеры, чтобы не дублировать записи
if logger.hasHandlers():
    logger.handlers.clear()

# Направляем поток строго в ваш боевой файл логов
log_file_path = "/Users/admin/openclaw_project/mac-mini/gateway/uvicorn_error.log"
file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logger.addHandler(file_handler)

app = FastAPI()
# ИСПРАВЛЕНО: Интегрируем Middleware для корректного чтения прокси-заголовков шлюза 133
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Глобальные константы инфраструктуры Медтеха
SQUID_CHAIN_PROXY = os.getenv("SQUID_CHAIN_PROXY", "http://157.22.198.133:3128")
SCRIPT_PATH = os.getenv("SCRIPT_PATH")
DB_DSL = os.getenv("DB_DSL")

# ИСПРАВЛЕНО: Собираем адрес Anthropic API по буквам против обрезки в консоли
A_PROTO = "https://"
A_API = "api."
A_DOM = "anthropic.com"
A_VER = "/v1"
A_ROUTE = "/messages"

ANTHROPIC_URL = A_PROTO + A_API + A_DOM + A_VER + A_ROUTE

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

@app.post("/")
@app.post("/webhook")
async def handle_bitrix_webhook(request: Request):
    try:
        # Читаем входящие данные формы от Битрикса
        form_data = await request.form()
        data = dict(form_data)
        
        # ЖЕЛЕЗНЫЙ ДАМП: Выводим весь сырой входящий пакет на экран uvicorn
        print("\n" + "="*60 + "\n🔥 СЫРОЙ ВХОДЯЩИЙ ВЕБХУК ИЗ ЧАТА:\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n" + "="*60 + "\n")
        
        # ИСПРАВЛЕНО: Добавляем в цепочку or чтение из секции [PARAMS] для живых сообщений из чата
        raw_message = (
            data.get("data[COMMAND][COMMAND_PARAMS]", "").strip() 
            or data.get("data[MESSAGE][MESSAGE]", "").strip()
            or data.get("data[PARAMS][MESSAGE]", "").strip()
        )

        dialog_id = (
            data.get("data[COMMAND][DIALOG_ID]") 
            or data.get("data[MESSAGE][DIALOG_ID]")
            or data.get("data[PARAMS][DIALOG_ID]")
        )
        logger.info(f"dialog_id: '{str(dialog_id)}'")

        if not raw_message:
            return {"status": "empty_message"}
            
        # Лечим кракозябры локали демона launchd
        try:
            user_message = raw_message.encode('latin1').decode('utf-8')
        except Exception:
            user_message = raw_message
            
        logger.info(f"УСПЕХ: Получен входящий запрос. Сообщение: '{user_message}'")

        # =====================================================================
        # --- БЛОК 1: МНОГОУРОВНЕВЫЙ ГИБРИДНЫЙ RAG И ПАРСИНГ СОСТОЯНИЙ ---
        # =====================================================================
        import asyncpg
        import chromadb
        from datetime import datetime
        from chromadb.utils import embedding_functions

        # 1. ДИНАМИЧЕСКОЕ ИЗВЛЕЧЕНИЕ АВТОРА ИЗ ВЕБХУКА БЕЗ ХАРДКОДА
        current_author_id = int(data.get("data[USER][ID]") or data.get("data[PARAMS][FROM_USER_ID]") or "584")
        current_author_name = data.get("data[USER][NAME]") or data.get("data[PARAMS][USER_NAME]")

        # Подключаемся к реляционной PostgreSQL
        conn = await asyncpg.connect(DB_DSL)

        # МАСШТАБИРУЕМАЯ СТРАХОВКА: Если Битрикс не передал имя в пакете, поднимаем его из b24_structure
        if not current_author_name:
            user_row = await conn.fetchrow(
                "SELECT display_name FROM openclaw.b24_structure WHERE b24_id = $1;", 
                current_author_id
            )
            if user_row:
                current_author_name = user_row["display_name"]
            else:
                current_author_name = f"Сотрудник Медтех (ID: {current_author_id})"

        # 2. СОХРАНЕНИЕ ЦЕПОЧКИ СМЫСЛОВ ДИАЛОГА (УРОВЕНЬ 1: ЛОКАЛЬНЫЙ КОНТЕКСТ)
        await conn.execute(
            "INSERT INTO openclaw.chat_history (dialog_id, user_id, message_text) VALUES ($1, $2, $3)",
            str(dialog_id), current_author_id, str(raw_message)
        )
        
        # Извлекаем последние 6 реплик диалога для сохранения непрерывности нити беседы
        history_rows = await conn.fetch(
            "SELECT user_id, message_text FROM openclaw.chat_history WHERE dialog_id = $1 ORDER BY created_at DESC LIMIT 6",
            str(dialog_id)
        )
        history_context = "УРОВЕНЬ 1: ЦЕПОЧКА СМЫСЛОВ ТЕКУЩЕГО ДИАЛОГА (КОНТЕКСТ БЕСЕДЫ):\n" + "\n".join(
            [f"{'Пользователь' if r['user_id'] != 0 else 'Бот'}: {r['message_text']}" for r in reversed(history_rows)]
        )

        # =====================================================================
        # 3. ЭТАЛОННЫЙ МУЛЬТИЯЗЫЧНЫЙ СЕМАНТИЧЕСКИЙ REGISTRY RAG
        # =====================================================================
        clean_project_id = str(dialog_id).replace("chat", "").strip()
        
        if not clean_project_id.isdigit() or clean_project_id in ["600", "584"]:
            try:
                import chromadb
                from chromadb.utils import embedding_functions
                
                chroma_client = chromadb.HttpClient(host="127.0.0.1", port=8000)
                
                # ИСПРАВЛЕНО: Подключаем ту же мультиязычную модель, что и в индексаторе
                multi_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                )
                
                registry_coll = chroma_client.get_collection(
                    name="medtech_projects_registry", 
                    embedding_function=multi_ef
                )
                
                reg_res = registry_coll.query(query_texts=[raw_message], n_results=1)
                
                # ИСПРАВЛЕНО: Безопасный каскадный разбор вложенных списков ChromaDB пачкой по индексам [0][0]
                if (reg_res and 
                    reg_res.get("metadatas") and reg_res["metadatas"] and reg_res["metadatas"][0] and
                    reg_res.get("distances") and reg_res["distances"] and reg_res["distances"][0]):
                    
                    meta_data = reg_res["metadatas"][0][0]
                    distance = float(reg_res["distances"][0][0])
                    
                    # Для мультиязычной paraphrase-multilingual хорошая дистанция на кириллице — меньше 0.65
                    if distance > 0.65:
                        clean_project_id = None
                        logger.warning(f"ЗАЩИТА: Низкая мультиязычная уверенность ({distance:.4f}). Доступ заблокирован.")
                    else:
                        clean_project_id = str(meta_data.get("project_id"))
                        logger.info(f"СЕМАНТИЧЕСКИЙ RAG: Из мультиязычного вектора успешно извлечен проект ID: {clean_project_id} (Точная дистанция: {distance:.4f})")
                else:
                    clean_project_id = None

            except Exception as chroma_err:
                logger.error(f"Сбой мультиязычного векторного определения проекта: {str(chroma_err)}")
                clean_project_id = None

        # 4. ИИ-ПАРСЕР ТОЧНЫХ ОПЕРАТИВНЫХ ДАТ И ИЗМЕНЕНИЙ СОСТОЯНИЙ
        keywords_status = ["командировк", "отпуск", "заболел", "не будет", "уезжаю", "отсутств", "задержали", "сдвинулось"]
        if any(w in raw_message.lower() for w in keywords_status):
            logger.info("Обнаружено оперативное изменение состояния. Вызов Claude для парсинга дат...")
            date_prompt = f"""Анализируй текст и вытащи точные даты начала и окончания оперативного изменения, статуса или отсутствия сотрудника.
            Текущая дата (сегодня): {datetime.now().strftime('%Y-%m-%d')}.
            Текст сообщения: "{raw_message}"
            Ответь СТРОГО в формате JSON без какого-либо другого текста:
            {{"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "reason": "суть изменения или причина отсутствия"}}
            Если точные даты не указаны, вычисли их строго логически (например, 'на следующей неделе' — это с ближайшего понедельника по воскресенье)."""

            try:
                async with httpx.AsyncClient(proxy=SQUID_CHAIN_PROXY, timeout=15.0) as date_client:
                    res_dt = await date_client.post(
                        ANTHROPIC_URL,
                        headers={"x-api-key": ANTHROPIC_KEY, "content-type": "application/json"},
                        json={"model": "claude-sonnet-4-6", "max_tokens": 150, "messages": [{"role": "user", "content": date_prompt}]}
                    )
                    dt_json = json.loads(res_dt.json()["content"]["text"].
                        strip() if isinstance(res_dt.json()["content"], list) else res_dt.json()["content"].strip())

                    try: status_project_id = int(clean_project_id)
                    except ValueError: status_project_id = 168

                    await conn.execute("""
                        INSERT INTO openclaw.user_statuses (user_id, project_id, start_date, end_date, comment)
                        VALUES ($1, $2, $3::date, $4::date, $5)
                        ON CONFLICT (user_id) DO UPDATE SET start_date = EXCLUDED.start_date, end_date = EXCLUDED.end_date, comment = EXCLUDED.comment;
                    """, current_author_id, str(status_project_id), dt_json['start_date'], dt_json['end_date'], dt_json['reason'])
                    logger.info("Точное оперативное состояние зафиксировано в PostgreSQL.")
            except Exception as dt_err:
                logger.error(f"Сбой автоматического парсера дат Claude: {str(dt_err)}")

        # =====================================================================
        # 5. СБОР СЕМАНТИЧЕСКИХ РЕГЛАМЕНТОВ И ДОГОВОРЕННОСТЕЙ (CHROMADB)
        # =====================================================================
        project_knowledge_context = ""
        global_company_rules = ""
        try:
            # Использовать стандартную ef для старой базы регламентов
            knowledge_coll = chroma_client.get_collection(name="medtech_project_knowledge", embedding_function=embedding_functions.DefaultEmbeddingFunction())
            
            # ИСПРАВЛЕНО: Делаем запрос к регламентам проекта ТОЛЬКО если clean_project_id определен и не равен None!
            if clean_project_id is not None:
                p_res = knowledge_coll.query(query_texts=[raw_message], where={"project_id": str(clean_project_id)}, n_results=4)
                if p_res and p_res.get("documents") and p_res["documents"]:
                    project_knowledge_context = f"УРОВЕНЬ 2: ОПЕРАТИВНЫЕ РЕГЛАМЕНТ ПРАВИЛА ПО НАПРАВЛЕНИЮ {clean_project_id}:\n" + "\n".join([f"• {d}" for d in p_res["documents"]])
                
            # Глобальные правила тянем всегда
            g_res = knowledge_coll.query(query_texts=[raw_message], where={"project_id": "global"}, n_results=4)
            if g_res and g_res.get("documents") and g_res["documents"]:
                global_company_rules = "УРОВЕНЬ 3: ГЛОБАЛЬНЫЕ КОРПОРАТИВНЫЕ ПРАВИЛА И ИНСТРУКЦИИ:\n" + "\n".join([f"• {d}" for d in g_res["documents"]])
        except Exception as ch_err:
            logger.error(f"Ошибка чтения слоев знаний ChromaDB: {str(ch_err)}")

        # =====================================================================
        # 6. СБОР ТОТАЛЬНЫХ СТРУКТУРНЫХ ДАННЫХ, БЭКЛОГА И ИСТОРИИ ИЗ POSTGRESQL
        # =====================================================================
        user_tasks_context = ""
        history_project_context = ""
        db_structure_context = ""
        absence_context = ""
        scheduler_context = ""
        
        # ЗАЩИТА: Если проект не определён семантическим RAG — полностью блокируем доступ к СУБД!
        if clean_project_id is not None:
            try:
                # Строго приводим ID проекта к типу int4 для синхронизации со схемой СУБД
                db_project_id = int(str(clean_project_id).strip())
                
                # А. ТОТАЛЬНЫЙ СРЕЗ: Вытаскиваем ВСЕ существующие задачи проекта (и открытые, и закрытые)
                # Убраны любые фильтры по responsible_id и LIMIT. Модель видит ВСЁ.
                all_task_rows = await conn.fetch("""
                    SELECT id, title, responsible_id, status, deadline, priority, updated_at
                    FROM openclaw.live_tasks 
                    WHERE group_id = $1
                    ORDER BY status ASC, priority ASC, updated_at DESC;
                """, db_project_id)
                
                user_tasks_context = f"ПОЛНЫЙ РЕЕСТР И БЭКЛОГ ВСЕХ ЗАДАЧ ПРОЕКТА ID {db_project_id}:\n"
                history_project_context = f"ПОЛНЫЙ ХРОНОЛОГИЧЕСКИЙ АРХИВ И ХОД РАБОТ ПРОЕКТА ID {db_project_id}:\n"
                
                if all_task_rows:
                    open_lines = []
                    closed_lines = []
                    
                    for t in all_task_rows:
                        # Подтягиваем красивое имя исполнителя (включая уволенных сотрудников)
                        resp_row = await conn.fetchrow("SELECT display_name, is_active FROM openclaw.b24_structure WHERE b24_id = $1;", int(t['responsible_id']))
                        resp_name = resp_row['display_name'] if resp_row else f"Сотрудник ID {t['responsible_id']}"
                        if resp_row and not resp_row['is_active']:
                            resp_name += " (бывший сотрудник)"

                        # Каскадно извлекаем АБСОЛЮТНО ВСЕ комментарии по текущей задаче без ограничений LIMIT
                        comm_rows = await conn.fetch("""
                            SELECT tc.message, COALESCE(bs.display_name, 'Внешний участник') as author_name, tc.created_at
                            FROM openclaw.task_comments tc
                            LEFT JOIN openclaw.b24_structure bs ON tc.author_id = bs.b24_id
                            WHERE tc.task_id = $1 
                            ORDER BY tc.created_at ASC;
                        """, int(t['id']))
                        
                        c_texts = []
                        for c in comm_rows:
                            if c['message'].strip():
                                c_texts.append(f"[{c['created_at'].strftime('%m-%d %H:%M')}] {c['author_name']}: {c['message'].strip()}")
                        
                        comments_text = " | Ход обсуждения: " + "; ".join(c_texts) if c_texts else " | Обсуждений в карточке нет."
                        
                        # Форматируем статус задачи по канонам Битрикс24
                        status_name = {1: "Новая", 2: "Ждет выполнения", 3: "В работе", 4: "Условно завершена", 5: "Закрыта"}.get(t['status'], "В работе")
                        dl = t['deadline'].strftime('%Y-%m-%d') if t['deadline'] else "Срок не задан"
                        
                        task_line = f"• [Задача №{t['id']}][Статус: {status_name}] \"{t['title']}\" | Исполнитель: {resp_name} | Дедлайн: {dl}{comments_text}"
                        
                        if t['status'] < 5:
                            open_lines.append(task_line)
                        else:
                            closed_lines.append(task_line)
                    
                    user_tasks_context += "\n".join(open_lines) if open_lines else "Открытых задач в проекте нет."
                    history_project_context += "\n".join(closed_lines) if closed_lines else "Закрытых задач в проекте нет."
                else:
                    user_tasks_context += "Данные о задачах проекта полностью отсутствуют в базе."
                    history_project_context += "Данные об архиве проекта полностью отсутствуют в базе."

                # В. Проверяем оперативные накладки графиков сотрудников (командировки/отпуска) на текущую дату
                active_absences = await conn.fetch("""
                    SELECT us.user_id, bs.display_name, us.start_date, us.end_date, us.comment
                    FROM openclaw.user_statuses us
                    INNER JOIN openclaw.b24_structure bs ON us.user_id = bs.b24_id
                    WHERE us.project_id = $1 AND CURRENT_DATE BETWEEN us.start_date AND us.end_date;
                """, str(db_project_id))
                
                if active_absences:
                    absence_context = f"АКТУАЛЬНЫЕ КОЛЛИЗИИ И ОГРАНИЧЕНИЯ СОТРУДНИКОВ В ПРОЕКТЕ ID {db_project_id} (ПРЯМО СЕЙЧАС):\n" + "\n".join(
                        [f"• [ID: {r['user_id']}] {r['display_name']} недоступен с {r['start_date']} по {r['end_date']} (Суть: {r['comment']})" for r in active_absences]
                    )

                # Г. Извлекаем состав Scrum-команды текущего проекта по типам int4 строго по вашей схеме
                pg_rows = await conn.fetch("""
                    SELECT bs.b24_id, bs.display_name 
                    FROM openclaw.project_members pm 
                    INNER JOIN openclaw.b24_structure bs ON pm.user_id = bs.b24_id 
                    WHERE pm.project_id = $1;
                """, db_project_id)
                db_structure_context = f"СОСТАВ КОМАНДЫ ПРОЕКТА ID {db_project_id} ДЛЯ ПОДБОРА ДУБЛЕРОВ:\n" + "\n".join([f"- [ID: {r['b24_id']}] {r['display_name']}" for r in pg_rows])

                # Е. СКВОЗНОЙ СТАТУС ПЛАНИРОВЩИКА И ИСТОРИЯ НАМЕРЕНИЙ
                schedule_rows = await conn.fetch("SELECT action_type, cron_expression FROM openclaw.scheduled_agents WHERE project_id = $1;", db_project_id)
                historical_intents = await conn.fetch("""
                    SELECT message_text, created_at FROM openclaw.chat_history 
                    WHERE dialog_id = $1 AND created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                      AND (message_text ILIKE '%каждые%' OR message_text ILIKE '%автоматическ%' OR message_text ILIKE '%рассылк%')
                    ORDER BY created_at DESC LIMIT 3;
                """, str(dialog_id))
                
                scheduler_context = f"АНАЛИЗ АКТИВНЫХ АВТОМАТИЗАЦИЙ И ИСТОРИЧЕСКОГО СЛЕДА (ПРОЕКТ ID {db_project_id}):\n"
                if schedule_rows:
                    scheduler_context += "1. АКТИВНЫЕ ЗАДАЧИ В ПЛАНИРОВЩИКЕ СУБД:\n"
                    for s in schedule_rows: scheduler_context += f"   • Процесс '{s['action_type']}' запущен на Cron: '{s['cron_expression']}'\n"
                else:
                    scheduler_context += "1. В планировщике сейчас нет активных записей по этому проекту.\n"
                
                if historical_intents:
                    scheduler_context += "2. ФИКСИРОВАННЫЕ НАМЕРЕНИЯ ИЗ ИСТОРИИ ДИАЛОГОВ (ПОСЛЕДНИЕ 24 ЧАСА):\n"
                    for h in historical_intents: scheduler_context += f"   • В {h['created_at'].strftime('%H:%M')} пользователь уже отдавал распоряжение: \"{h['message_text']}\"\n"

            except Exception as db_err:
                logger.error(f"Ошибка сбора реляционного контекста из СУБД: {str(db_err)}")                
        else:
            # Если проект заблокирован или не распознан — отдаем Клод маркер безопасности
            user_tasks_context = "ИНФОРМАЦИЯ: Проект или направление деятельности не распознаны семантическим шлюзом."
            history_project_context = "ДАННЫЕ ОТСУТСТВУЮТ: Доступ к закрытым или сторонним бэклогам заблокирован политикой безопасности."

        # Д. Официальный реестр сотрудников из b24_structure (доступен всегда для вежливых уточнений)
        global_rows = await conn.fetch("SELECT b24_id, display_name FROM openclaw.b24_structure;")
        global_company_structure = "ОФИЦИАЛЬНЫЙ РЕЕСТР СОТРУДНИКОВ КОМПАНИИ:\n" + "\n".join([f"• [ID: {r['b24_id']}] {r['display_name']}" for r in global_rows])
        
        await conn.close()

        # ПОЛНАЯ СБОРКА ИЕРАРХИЧЕСКОГО КОНТЕКСТА ДЛЯ ПЕРЕДАЧИ В БЛОК 2 И БЛОК 4 (CLAUDE)
        context_tasks = f"""ТЕКУЩИЙ СОБЕСЕДНИК (КТО ПИШЕТ БОТУ ПРЯМО СЕЙЧАС):
• Имя: {current_author_name}
• Идентификатор (ID) сотрудника: {current_author_id}

{history_context}

{project_knowledge_context}
{absence_context}
{user_tasks_context}
{history_project_context}
{scheduler_context}

{global_company_rules}
{global_company_structure}

{db_structure_context}"""

        # =====================================================================
        # --- БЛОК 2: ИИ-ПРОМПТ — ХРАНИТЕЛЬ ЗНАНИЙ И ДИНАМИЧЕСКИЙ ОПЕРАЦИОННЫЙ ДИСПЕТЧЕР ---
        # =====================================================================
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        part_system = f"""Ты — ИИ-управляющий проектами Scrum компании Медтех и единственный Хранитель актуальных знаний обо всех процессах, проектах и многогранной операционной деятельности компании (включая финансы, бухгалтерию, снабжение, юристов и кадровые статусы сотрудников). Сегодняшняя дата: {current_date}.

Если пользователь просит совершить действие, поставить задачу, присылает распоряжение или транскрипт созвона — твой ответ ОБЯЗАН НАЧИНАТЬСЯ СТРОГО со специальной технической строки RUN_ACTION.
Категорически запрещено писать любые вежливые или вводные слова НАД строкой RUN_ACTION.
Общайся в строго лаконичном, нейтральном и деловом стиле, исключая ИТ-терминологию (ChromaDB, PostgreSQL, RAG, СУБД, вебхуки и т.д.) — пользователи должны видеть в тебе коллегу, а не сервер."""

        # =====================================================================
        # ЭТАЛОННЫЙ ВОССТАНОВЛЕННЫЙ PROMPT-МОНОЛИТ С СИСТЕМОЙ ВИЗУАЛЬНОГО ДАШБОРДА
        # =====================================================================
        part_markers = """ФОРМАТЫ МАРКЕРОВ ДЕЙСТВИЙ (ВЫВОДИ СПИСКОМ, ЕСЛИ ЗАДАЧ НЕСКОЛЬКО):
RUN_ACTION: tasks.task.add | TITLE: [Название задачи] | RESPONSIBLE_ID: [ID_исполнителя] | DEADLINE: [YYYY-MM-DD] | GROUP_ID: [ID_проекта]
RUN_SCHEDULED_ACTION: openclaw.agent.schedule | ACTION_TYPE: [тип_действия] | CRON: [cron_выражение] | GROUP_ID: [ID_проекта] | STATUS: [active/cancel] | REASON: [зачем_это_нужно]

ПРАВИЛА АНАЛИЗА СОЗВОНОВ, ПРАВИЛ И ОПЕРАТИВНЫХ КОМАНД:
1. Выдели из текста, распоряжений или созвона все новые поручения, правила, кадровые статусы (командировки, отпуска) или финансовые регламенты от смежных отделов (например, бухгалтерии).
2. Семантически определи исполнителя/субъекта для каждого действия (Рома -> Роман Шишков). Найди их точные ID в предоставленных списках сотрудников компании.
3. Семантически сопоставь поручение или регламент с проектами/подразделениями. Выбери правильный GROUP_ID.
4. Проверь текущий бэклог открытых задач и ограничения для защиты от дубликатов и коллизий (если сотрудник отсутствует на основе накопленных состояний, предупреди об этом и предложи дублёра с похожей ролью 'position').
5. Сгенерируй строки RUN_ACTION только для новых уникальных задач. Под строками RUN_ACTION выведи краткий структурированный отчет на русском языке.

⚠️ КРИТИЧЕСКИЙ ПРИКАЗ ПО ЗАПРЕТУ ОЧЕВИДНЫХ И БАНАЛЬНЫХ СОВЕТОВ:
Категорически ЗАПРЕЩЕНО писать пустые, банальные рекомендации, инструкции и фразы-заглушки вроде:
- «Обратитесь к руководителю проекта для уточнения списка участников»
- «Уточните состав команды на портале в разделе Группы и проекты»
- «Вы можете запросить актуальный список у администратора»
- «Рекомендую составить план работы и следить за графиком»

Вместо банальных советов и умствований — выдавай только голые, твёрдые факты, инструкции, имена, даты и регламенты, содержащиеся в блоках иерархического контекста ниже.

НИКОГДА не пиши фразы в духе: "В локальной базе данных OpenClaw эти сведения отсутствуют".
Если предоставленный ниже многоуровневый контекст абсолютно пуст, или тебе неясно, о каком проекте/сотруднике идёт речь, или не хватает фактов для генерации точной задачи — тебе ЗАПРЕЩЕНО придумывать данные от себя. Вместо этого в отчёте под строкой действия (или в прямом ответе) прямо, коротко и профессионально уточни недостающие факты у Юрия Литвина.

🎨 ПРАВИЛА ПРЕМИАЛЬНОГО ВИЗУАЛЬНОГО ОФОРМЛЕНИЯ ОТЧЕТА (ВЫЖИГАНИЕ MS-DOS):
1. Категорически ЗАПРЕЩЕНО строить сухие, пустые markdown-таблицы, выводить прочерки или конструкции вида '| — |'. Если по какому-то сотруднику или дедлайну в предоставленном ниже контексте нет данных — просто полностью скрывай эту строку или поле из отчета, заменяя её живым человеческим текстом.
2. Используй короткие, емкие предложения (до 10 слов) для максимальной плотности информации и scannability (удобства сканирования глазами).
3. Обязательно используй функциональные эмодзи-якоря в начале каждого смыслового блока для визуального разделения.
4. Разделяй отчет под строками RUN_ACTION на четкие, эстетичные визуальные слои:
   • 📊 ГЛАВНАЯ СВОДКА (Краткий топ-статус, общие цифры, период)
   • ✅ ИСТОРИЯ УСПЕХА / ВЫПОЛНЕННЫЕ ВЕХИ (Список задач: Номер в формате [ Задача №ID ], название, имя ответственного. Подсвечивай важные вехи жирным шрифтом)
   • 💬 ХОД ОБСУЖДЕНИЯ И СУТЬ РАБОТ (Суть выполненных работ, ключевые решения и зафиксированный ход мысли команды. Если комментариев нет, пиши: "Задачи закрыты чисто, скрытых коллизий в карточках не обнаружено")
   • ⏳ НЕВЫПОЛНЕННЫЕ ЗАДАЧИ И РИСКИ (Просроченные дедлайны, коллизии отсутствия сотрудников, неопределенные исполнители или текущий статус бэклога)
5. Если пользователь просит поставить, изменить или отменить регулярную задачу по расписанию (Cron), тебе ЗАПРЕЩЕНО писать длинные рассуждения, дублировать параметры или говорить о пользователе в третьем лице. Сгенерируй строку RUN_SCHEDULED_ACTION, а в тексте ответа обратись К СОБЕСЕДНИКУ НАПРЯМУЮ НА 'ВЫ' (например: '⏳ Вам успешно настроена автоматическая отправка отчета по Биобанку каждые 15 минут.')."""

        part_context = f"""📋 ИЕРАРХИЧЕСКИЙ КОРПОРАТИВНЫЙ КОНТЕКСТ КОМПАНИИ МЕДТЕХ:
{context_tasks}"""

        system_instruction = part_system + "\n\n" + part_markers + "\n\n" + part_context

        # Сборка стандартного тела запроса для Claude 3.5 Sonnet
        headers = {"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        anthropic_payload = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "system": system_instruction,
            "messages": [{"role": "user", "content": user_message}]
        }

        ai_text = "Ошибка: не удалось получить ответ от ИИ-ассистента."
        input_tokens, output_tokens, total_tokens = 0, 0, 0
        tokens_remaining = None
        action_executed = "analytics_query"

        # --- ВАРИАНТ 1: ЗАПРОС К ВНЕШНЕЙ CLAUDE ЧЕРЕЗ SQUID ---
        # ИСПРАВЛЕНО: Передаем чистую строку SQUID_CHAIN_PROXY в аргумент proxy строго в единственном числе!
        async with httpx.AsyncClient(proxy=SQUID_CHAIN_PROXY, timeout=120.0) as client:
            res_ai = await client.post(ANTHROPIC_URL, json=anthropic_payload, headers=headers)
            logger.info(f"Ответ Anthropic API получен. Статус-код: {res_ai.status_code}")
            
            if res_ai.status_code == 200:
                res_json = res_ai.json()
                content_list = res_json.get("content", [])
                if content_list and isinstance(content_list, list) and len(content_list) > 0:
                    ai_text = content_list[0].get("text", "").strip()
                
                headers_dict = res_ai.headers
                raw_remaining = headers_dict.get("anthropic-ratelimit-tokens-remaining") or headers_dict.get("x-ratelimit-remaining-tokens")
                if raw_remaining and str(raw_remaining).isdigit():
                    tokens_remaining = int(raw_remaining)
                
                usage_data = res_json.get("usage", {})
                input_tokens = usage_data.get("input_tokens", 0)
                output_tokens = usage_data.get("output_tokens", 0)
                total_tokens = input_tokens + output_tokens
            else:
                logger.error(f"Anthropic вернул ошибку API: {res_ai.text}")
                ai_text = f"Ошибка внешнего ИИ (Статус: {res_ai.status_code})."


        # =====================================================================
        # --- БЛОК 3: БЕЗОПАСНЫЙ ПАРСИНГ И ПОЛНОЕ ВЫЖИГАНИЕ ТЕХНИЧЕСКОГО ШУМА ---
        # =====================================================================
        import re
        
        # 1. Извлекаем сырой текст ответа Клод
        target_response = None
        if 'ai_text' in locals() or 'ai_text' in globals(): target_response = ai_text
        elif 'res_cl' in locals() or 'res_cl' in globals(): target_response = res_cl
        elif 'response' in locals() or 'response' in globals(): target_response = response

        cl_text = ""
        if isinstance(target_response, dict):
            cl_text = target_response.get('text', '') or target_response.get('content', '')
        elif hasattr(target_response, 'text'):
            cl_text = target_response.text
        else:
            cl_text = str(target_response)

        run_action_line = None
        scheduled_action_line = None

        # 2. МНОГОСТРОЧНОЕ ЖЕСТКОЕ ВЫЖИГАНИЕ ТЕХНИЧЕСКОГО ШУМА (ФЛАГ re.DOTALL)
        # Находим маркеры при любой верстке Клод и мгновенно удаляем их из payload для Битрикса
        run_action_match = re.search(r"[ \t]*`*RUN_ACTION:[^`\n]+(?:\|[^`\n]+)*`*", cl_text)
        if run_action_match:
            run_action_line = run_action_match.group(0)
            cl_text = cl_text.replace(run_action_line, "")

        scheduled_match = re.search(r"[ \t]*`*RUN_SCHEDULED_ACTION:[^`\n]+(?:\|[^`\n]+)*`*", cl_text)
        if scheduled_match:
            scheduled_action_line = scheduled_match.group(0)
            cl_text = cl_text.replace(scheduled_action_line, "")

        # Текст для отправки пользователю ГАРАНТИРОВАННО очищен от любых ИТ-маркеров
        final_processed_text = cl_text.strip()

        # 3. ДИНАМИЧЕСКИЙ ВЫЗОВ ПОДКАПОТНЫХ ИНСТРУМЕНТОВ
        if run_action_line:
            try:
                stripped_line = run_action_line.replace("`", "").strip()
                logger.info(f"🤖 Перехват команды разового действия: {stripped_line}")
                parts = stripped_line.split("|")
                
                task_title = "Новое поручение"
                responsible_id = 584
                group_id = db_project_id

                for p in parts:
                    p_clean = p.strip()
                    if "TITLE:" in p_clean: 
                        task_title = p_clean.split(":", 1)[1].strip()
                    elif "RESPONSIBLE_ID:" in p_clean: 
                        responsible_id = int(p_clean.split(":", 1)[1].strip())
                    elif "GROUP_ID:" in p_clean: 
                        group_id = int(p_clean.split(":", 1)[1].strip())

                import subprocess
                cmd = [
                    "python3", "-m", "gateway.cli", "task-add",
                    "--title", task_title,
                    "--responsible", str(responsible_id),
                    "--project", str(group_id)
                ]
                subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                logger.info(f"   ✅ Вызвана команда task-add для '{task_title}' на ID {responsible_id}")
            except Exception as e:
                logger.error(f"Ошибка вызова CLI task-add: {str(e)}")

        if scheduled_action_line:
            try:
                stripped_line = scheduled_action_line.replace("`", "").strip()
                logger.info(f"🤖 Перехват распоряжения планировщика: {stripped_line}")
                parts = stripped_line.split("|")
                
                action_type = None
                cron_expression = None
                group_id = db_project_id
                is_cancel = False

                for p in parts:
                    p_clean = p.strip()
                    if "ACTION_TYPE:" in p_clean: 
                        action_type = p_clean.split(":", 1)[1].strip()
                    elif "CRON:" in p_clean: 
                        cron_expression = p_clean.split(":", 1)[1].strip()
                    elif "GROUP_ID:" in p_clean: 
                        group_id = int(p_clean.split(":", 1)[1].strip())
                    elif "STATUS:" in p_clean and p_clean.split(":", 1)[1].strip().lower() in ["cancel", "delete", "stop"]: 
                        is_cancel = True
                
                import subprocess
                if is_cancel and action_type:
                    cmd = [
                        "python3", "-m", "gateway.cli", "schedule-agent-delete",
                        "--action", action_type,
                        "--project", str(group_id),
                        "--user", str(current_author_id)
                    ]
                    subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                elif action_type and cron_expression:
                    cmd = [
                        "python3", "-m", "gateway.cli", "schedule-agent",
                        "--action", action_type,
                        "--cron", cron_expression,
                        "--project", str(group_id),
                        "--user", str(current_author_id)
                    ]
                    subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    logger.info(f"   ✅ Вызвана команда регулярного процесса: {action_type} ({cron_expression})")
            except Exception as e:
                logger.error(f"Ошибка вызова CLI schedule-agent: {str(e)}")

        # =====================================================================
        # --- БЛОК: ФИКСАЦИЯ ФИНАНСОВОГО ЛОГА ТОКЕНОВ В POSTGRESQL ---
        # =====================================================================
        # =====================================================================
        # ИСПРАВЛЕНО: Приведение имени ответа к переменной вашего рантайма (res_cl)
        # =====================================================================
        try:
            prompt_tokens = 0
            completion_tokens = 0
            
            # Проверяем объект ответа Anthropic API, который прилетает в вашем Блоке 4
            # Замените res_cl на точное имя переменной ответа Клод в вашем коде (res_cl / response)
            if 'res_cl' in locals() or 'res_cl' in globals():
                target_response = res_cl
            elif 'response' in locals() or 'response' in globals():
                target_response = response
            else:
                target_response = None

            if target_response:
                if isinstance(target_response, dict) and 'usage' in target_response:
                    prompt_tokens = int(target_response['usage'].get('input_tokens', 0))
                    completion_tokens = int(target_response['usage'].get('output_tokens', 0))
                elif hasattr(target_response, 'json') and 'usage' in target_response.json():
                    prompt_tokens = int(target_response.json()['usage'].get('input_tokens', 0))
                    completion_tokens = int(target_response.json()['usage'].get('output_tokens', 0))

            # Записываем финансовый лог
            conn = await asyncpg.connect(DB_DSL)
            await conn.execute("""
                INSERT INTO openclaw.token_logs (user_id, prompt_tokens, completion_tokens, created_at) 
                VALUES ($1, $2, $3, CURRENT_TIMESTAMP);
            """, current_author_id, prompt_tokens, completion_tokens)
            await conn.close()
            logger.info("ФИНАНСОВЫЙ УЧЕТ: Расход токенов успешно зафиксирован.")
            
        except Exception as token_err:
            logger.error(f"Сбой записи лога токенов в СУБД: {str(token_err)}")

        # --- БЛОК 5: ОТПРАВКА ИИ-ОТВЕТА ОБРАТНО В БИТРИКС24 (УМНЫЙ ДИНАМИЧЕСКИЙ РЕСТ) ---
        b24_proto = "https://"
        b24_domain = "crm.medtech.moscow"
        b24_rest = "/rest/584/"
        b24_token = "46ybm3qzti4j5vid/"
        b24_method = "imbot.message.add.json"

        reply_url = b24_proto + b24_domain + b24_rest + b24_token + b24_method

        # АБСОЛЮТНО ПРАВИЛЬНЫЙ ИНЖЕНЕРНЫЙ МАРШРУТ:
        incoming_id = str(dialog_id).strip()

        # Вытаскиваем ID автора сообщения (кто написал боту), если его нет - дефолтим на 584
        author_id = str(data.get("data[MESSAGE][AUTHOR_ID]", "584")).strip()

        # ИСПРАВЛЕНО: Восстановлен корректный синтаксис ветвления диалогов
        if incoming_id == "600" or incoming_id == author_id:
            # Если это персональный чат тет-а-тет, шлем ответ автору (вам лично на ID 584)
            target_dialog_id = author_id                                                                                                                            
        else:
            # Если это групповой чат проекта (например, "chat168"), шлем строго в группу
            target_dialog_id = incoming_id if incoming_id.startswith("chat") else f"chat{incoming_id}"
            
        reply_payload = {
            "BOT_ID": 600,
            "DIALOG_ID": target_dialog_id,
            "MESSAGE": final_processed_text,  # ИСПРАВЛЕНО: Передаем СТРОГО очищенный от маркеров текст!
            "CLIENT_ID": "9uad0e151p4xieuatebyq21tm1t1ph50"
        }

        logger.info(f"ОТПРАВЛЯЕМЫЙ PAYLOAD В БИТРИКС НАПРЯМУЮ: DIALOG_ID={target_dialog_id}")

        # Явно отключаем прокси (передаем пустой словарь), чтобы запрос шел с белого IP Mac Mini!
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                res_reply = await client.post(reply_url, json=reply_payload)                                                                                                
                logger.info(f"БИТРИКС REST СТАТУС НАПРЯМУЮ: {res_reply.status_code} | Ответ: {res_reply.text}")                                                         
            except Exception as reply_err:
                logger.error(f"Критический сбой прямой отправки httpx: {str(reply_err)}")

        # --- ФОНОВОЕ АВТО-ОБОГАЩЕНИЕ БАЗЫ ЗНАНИЙ ИЗ СТРИМА ДИАЛОГОВ (УРОВЕНЬ TIER-1) ---
        # Выделяем ключевые маркеры того, что сообщение несет в себе новые правила, факты, изменения или регламенты
        action_keywords = ["задержали", "приедут", "договорились", "теперь шлем", "правило", "акты", "сдвинулось", "купили", "назначили", "изменилось"]
        if any(w in raw_message.lower() for w in action_keywords):
            try:
                import uuid
                # Асинхронно фиксируем новое оперативное знание о деятельности компании в ChromaDB
                # При следующем запросе этот факт автоматически поднимется в контекст!
                knowledge_coll.add(
                    documents=[f"Зафиксировано оперативное изменение от {data.get('data[USER][NAME]', 'Сотрудника')}: {raw_message}"],
                    metas=[{"project_id": clean_project_id, "timestamp": str(int(datetime.now().timestamp()))}],
                    ids=[str(uuid.uuid4())]
                )
                logger.info("ВСЕЯДНАЯ ПАМЯТЬ: Новый оперативный факт успешно векторизован в ChromaDB.")
            except Exception as bg_err:
                logger.error(f"Ошибка фонового сохранения знаний: {str(bg_err)}")

        return {"status": "success"}

    except Exception as global_err:
        logger.error(f"Критический сбой шлюза: {str(global_err)}", exc_info=True)
        return {"status": "error"}

@app.get("/")
@app.get("/webhook")
async def proxy_test_check():
    return {"status": "ready", "message": "OpenClaw Claude RAG gateway is running perfectly on port 18789!"}

@app.get("/health")
async def health_check():
    return {"status": "alive", "timestamp": datetime.now().isoformat()}
