# -*- coding: utf-8 -*-
import asyncio
import asyncpg
import httpx
import logging
import sys
from datetime import datetime

# Боевые константы инфраструктуры Медтеха
DB_DSL = "postgresql://litvinyn:Fklgy57995@157.22.198.133:5432/xclaw_db"
GATEWAY_URL = "http://127.0.0.1:18795/webhook" # Локальный порт нашего FastAPI шлюза

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("OpenClawWorker")

async def execute_agent_action(agent):
    """
    Эмулирует входящий запрос от пользователя Юрия Литвина.
    Шлюз main_claude.py подтянет свежий реляционный контекст из PostgreSQL
    и автоматически отправит готовый сочный дашборд в чат Битрикс24!
    """
    logger.info(f"🤖 Рука OpenClaw запускает автоматизацию: '{agent['action_type']}' для проекта ID {agent['project_id']}...")
    
    # Формируем фейковый вебхук Битрикса, заставляя шлюз думать, что шеф сам нажал кнопку
    payload = {
        "event": "ONIMCONNECT",
        "data[PARAMS][FROM_USER_ID]": str(agent['user_id']),
        "data[PARAMS][USER_NAME]": "Автоматический Агент OpenClaw",
        "dialog_id": str(agent['user_id']), # Отправляем в личку шефу (ID 584)
        "raw_message": f"Сделай ретро по закрытым задачам проекта {agent['project_id']} за последний месяц."
    }
    
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            # Стреляем напрямую в локальный порт FastAPI, проходя мимо всех прокси шлюзов
            res = await client.post(GATEWAY_URL, json=payload)
            if res.status_code == 200:
                logger.info(f"   ✅ УСПЕХ: Команда регулярного отчета успешно передана на шлюз.")
            else:
                logger.error(f"   ⚠️ Шлюз вернул ошибку: {res.status_code} | {res.text[:200]}")
    except Exception as e:
        logger.error(f"   🔴 Критический сбой вызова руки автоматизации OpenClaw: {str(e)}")

async def check_cron_schedules():
    """
    Сканирует таблицу регулярных задач. В рамках демонстрации, если задача 
    создана и еще ни разу не выполнялась (last_run IS NULL), мы запускаем её 
    мгновенно, чтобы прямо сейчас увидеть результат работы ИИ-агента!
    """
    conn = await asyncpg.connect(DB_DSL)
    
    # Берем новые, еще не запущенные регулярные триггеры от шефа
    agents = await conn.fetch("""
        SELECT id, project_id, user_id, action_type 
        FROM openclaw.scheduled_agents 
        WHERE last_run IS NULL;
    """)
    
    if agents:
        logger.info(f"🔎 Обнаружено {len(agents)} новых агентских инструкций к исполнению...")
        for agent in agents:
            # Запускаем выполнение автоматической рассылки/действия
            await execute_agent_action(agent)
            
            # Фиксируем временную метку выполнения, чтобы исключить зацикливание в рантайме
            await conn.execute("""
                UPDATE openclaw.scheduled_agents 
                SET last_run = CURRENT_TIMESTAMP 
                WHERE id = $1;
            """, agent['id'])
            
    await conn.close()

async def main():
    logger.info("🚀 ФОНОВЫЙ ИСПОЛНИТЕЛЬНЫЙ ДЕМОН АВТОНОМНЫХ АГЕНТОВ OPENCLAW ЗАПУЩЕН...")
    logger.info("Слежу за таблицей openclaw.scheduled_agents каждые 15 секунд.")
    
    while True:
        try:
            await check_cron_schedules()
        except Exception as e:
            logger.error(f"🔴 Ошибка каскадного цикла проверки воркера: {str(e)}")
        # Проверяем базу данных 4 раза в минуту
        await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())

