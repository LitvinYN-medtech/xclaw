# -*- coding: utf-8 -*-
import chromadb
import uuid
import sys

try:
    # Подключаемся к локальному серверу ChromaDB
    chroma_client = chromadb.HttpClient(host="127.0.0.1", port=8000)
    knowledge_coll = chroma_client.get_or_create_collection(name="medtech_project_knowledge")

    # Жестко зачищаем старые записи, чтобы не плодить дубли
    try:
        existing = knowledge_coll.get(where={"category": "project_purpose"})
        if existing and existing['ids']:
            knowledge_coll.delete(ids=existing['ids'])
            print("Старые тестовые записи успешно удалены.")
    except Exception:
        pass

    # Формулируем эталонные бизнесовые знания о Цифровом двойнике
    digital_twin_facts = [
        "Проект называется Цифровой двойник. Это умный цифровой Скрам-мастер и Менеджер проекта компании Медтех.",
        "Цифровой двойник делает работу с задачами удобной, он знает абсолютно всё о задачах команды и о статусе выполнения планов по каждому проекту.",
        "Цифровой двойник помогает сотрудникам не терять фокус над важными задачами и проактивно следит за приоритетами в работе.",
        "Интеллектуальный ассистент помогает не забыть о договоренностях в групповом чате, которые случайно забыли добавить в официальную задачу.",
        "Цифровой двойник знает обо всех устных и письменных договоренностях по проекту и помогает руководителю в любую секунду получать самую полную сводную информацию по актуальному статусу задач."
    ]

    # Внедряем твёрдые факты в глобальную семантическую память
    for fact in digital_twin_facts:
        knowledge_coll.add(
            documents=[fact],
            metadatas=[{"project_id": "global", "category": "project_purpose"}],
            ids=[f"digital_twin_purpose_{str(uuid.uuid4())[:8]}"]
        )

    print("🏆 УСПЕХ: Бизнес-контекст проекта 'Цифровой двойник' успешно зафиксирован в ChromaDB!")

except Exception as e:
    print(f"🔴 Критическая ошибка при записи в базу: {str(e)}")
    sys.exit(1)

