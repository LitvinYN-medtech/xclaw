import os
import json
import asyncio
import asyncpg

# Строка подключения к вашей Enterprise-БД
DB_DSL = "postgresql://litvinyn:Fklgy57995@157.22.198.133:5432/xclaw_db"
SQUID_CHAIN_PROXY = "http://157.22.198.186:3128"

async def sync():
    env = os.environ.copy()
    env.update({
        "B24_DOMAIN": "crm.medtech.moscow",
        "B24_AUTH_MODE": "webhook",
        "B24_WEBHOOK_USER_ID": "584",
        "B24_WEBHOOK_CODE": "84d5b7r1otf671mx",
        "HTTP_PROXY": SQUID_CHAIN_PROXY,
        "HTTPS_PROXY": SQUID_CHAIN_PROXY
    })
    script_path = "/Users/admin/openclaw_project/bitrix24-skill/skills/bitrix24-agent/scripts/bitrix24_client.py"
    
    print("Подключение к PostgreSQL...")
    conn = await asyncpg.connect(DB_DSL)
    
    # 1. СИНХРОНИЗАЦИЯ ВСЕХ АКТИВНЫХ СОТРУДНИКОВ
    print("Выгрузка активных сотрудников из Битрикс24...")
    start_offset = 0
    total_users_saved = 0
    while True:
        user_params = json.dumps({"FILTER": {"ACTIVE": "Y"}, "start": start_offset})
        proc = await asyncio.create_subprocess_exec(
            "python3", script_path, "user.get", "--params", user_params, "--packs", "core",
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0: break
        res_data = json.loads(stdout.decode('utf-8'))
        users_batch = res_data.get("result", [])
        if not users_batch: break
        
        for u in users_batch:
            full_name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
            if full_name:
                await conn.execute(
                    "INSERT INTO openclaw.b24_structure (entity_type, b24_id, display_name) VALUES ('user', $1, $2) ON CONFLICT (b24_id) DO UPDATE SET display_name=$2",
                    int(u.get("ID")), full_name
                )
                total_users_saved += 1
        if "next" in res_data: start_offset = int(res_data["next"])
        else:
            if len(users_batch) < 50: break
            start_offset += 50

    # 2. ПАГИНАЦИЯ И СБОР СВЯЗЕЙ УЧАСТНИКОВ ПРОЕКТОВ ИЗ ВСЕГО БЭКЛОГА
    print("Парсинг связей участников Scrum-команд из живого бэклога...")
    start_t_offset = 0
    total_links_saved = 0
    
    while True:
        # Корректировка глубины синхронизации бэклога: берем срез за последние 30 дней (1 месяц)
        from datetime import datetime, timedelta
        sprint_start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")

        task_params = json.dumps({
            "select": ["ID", "TITLE", "STATUS", "DEADLINE", "GROUP_ID", "GROUP_NAME", "RESPONSIBLE_ID", "CLOSED_DATE"], 
            "filter": {
                ">=CHANGED_DATE": sprint_start_date 
            },
            "start": start_t_offset
        })

        proc_g = await asyncio.create_subprocess_exec(
            "python3", script_path, "tasks.task.list", "--params", task_params, "--packs", "core,boards", 
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout_g, _ = await proc_g.communicate()
        if proc_g.returncode != 0: break
        
        res_g_data = json.loads(stdout_g.decode('utf-8'))
        tasks_batch = res_g_data.get("result", {}).get("tasks", []) if isinstance(res_g_data.get("result"), dict) else res_g_data.get("result", [])
        
        if not tasks_batch or len(tasks_batch) == 0:
            break
            
        for t in tasks_batch:
            g_id = t.get("GROUP_ID") or t.get("groupId")
            r_id = t.get("RESPONSIBLE_ID") or t.get("responsibleId")
            if g_id and r_id and int(g_id) > 0 and int(r_id) > 0:
                await conn.execute(
                    "INSERT INTO openclaw.project_members (project_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", 
                    int(g_id), int(r_id)
                )
                total_links_saved += 1
                
        # Шаг пагинации по бэклогу
        if "next" in res_g_data:
            start_t_offset = int(res_g_data["next"])
        else:
            if len(tasks_batch) < 50: break
            start_t_offset += 50

    # 3. ПОЛУЧЕНИЕ ТОЧНОГО ИТОГОВОГО КОЛИЧЕСТВА ПРОЕКТОВ ИЗ НАШЕГО КЭША В БД
    total_projects = await conn.fetchval("SELECT COUNT(*) FROM openclaw.b24_structure WHERE entity_type='project'")

    await conn.close()
    
    # КРАСИВЫЙ И КРИСТАЛЬНО ЧИСТЫЙ ИТОГОВЫЙ СТАТУС ДЛЯ ТЕРМИНАЛА
    print("\n" + "="*50)
    print("🏁 СИНХРОНИЗАЦИЯ СТРУКТУРЫ OPENCLAW ЗАВЕРШЕНА УСПЕХНО")
    print("="*50)
    print(f"👥 Всего активных сотрудников загружено: {total_users_saved}")
    print(f"📁 Всего Scrum-проектов зафиксировано:    {total_projects}")
    print(f"🔗 Всего связей участников обработано:   {total_links_saved}")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(sync())
