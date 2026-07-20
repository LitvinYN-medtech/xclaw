# -*- coding: utf-8 -*-
import asyncio
import asyncpg
import chromadb
from chromadb.utils import embedding_functions

DB_DSL = "postgresql://litvinyn:Fklgy57995@157.22.198.133:5432/xclaw_db"

async def main():
    print("📡 ЗАПУСК СЕМАНТИЧЕСКОЙ ИНДЕКСАЦИИ ПРОЕКТОВ...")
    
    # 1. Извлекаем все проекты из базы данных
    conn = await asyncpg.connect(DB_DSL)
    # Выбираем уникальные ID и имена проектов, которые мы реально синхронизировали в live_tasks
    rows = await conn.fetch("""
        SELECT DISTINCT group_id 
        FROM openclaw.live_tasks 
        WHERE group_id IS NOT NULL;
    """)
    
    if not rows:
        print("⚠️ В таблице live_tasks нет данных о проектах. Сначала запустите sync_structure.py")
        await conn.close()
        return

    # Нам также нужны красивые имена этих проектов. Поскольку в live_tasks лежат только ID, 
    # мы можем достать имена из логов или использовать реестр, но для теста сопоставим ID с именами, 
    # которые выгрузил наш list_projects.py. Чтобы было всеядно, сделаем сопоставление по известным ID:
    project_mapping = {
        1: "ДКИ Малые проекты", 2: "Медтех Сайнтифик", 3: "Команда Гранты", 
        6: "ДКИ Административные задачи взаимодействие с АНО", 7: "Грантовая программа",
        8: "Оперативные задачи", 9: "Биобанк internal", 27: "1.5. DAILY БИОБАНК",
        168: "Цифровой двойник Scrum менеджер"
    }
    
    # 2. Инициализируем ChromaDB
    chroma_client = chromadb.HttpClient(host="127.0.0.1", port=8000)
    registry_coll = chroma_client.get_or_create_collection(
        name="medtech_projects_registry", 
        embedding_function=embedding_functions.DefaultEmbeddingFunction()
    )
    
    # 3. Загружаем эмбеддинги в базу знаний
    print("🧠 Генерация векторов и запись в ChromaDB...")
    for r in rows:
        p_id = r['group_id']
        # Берем имя из маппинга или дефолтим, если это новый проект из 90+ доступных
        p_name = project_mapping.get(p_id, f"Проект Направление {p_id}")
        
        # document — это текст, по которому будет идти смысловой поиск
        # metadata — жесткий ID, который мы подставим в SQL-запрос
        registry_coll.upsert(
            documents=[f"Проект {p_name} направление задачи бэклог архив"],
            metadatas=[{"project_id": str(p_id)}],
            ids=[f"proj_{p_id}"]
        )
        print(f"   🔹 Векторизован проект ID: {p_id} | {p_name}")
        
    await conn.close()
    print("🏆 Семантический реестр ChromaDB успешно обновлен!")

if __name__ == "__main__":
    asyncio.run(main())

