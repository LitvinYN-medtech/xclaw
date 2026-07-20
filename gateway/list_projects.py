# -*- coding: utf-8 -*-
import asyncio
import httpx
import sys

B24_BASE_URL = "https://crm.medtech.moscow"
B24_REST_PATH = "/rest/584/46ybm3qzti4j5vid/"
SQUID_PROXY_URL = "http://157.22.198.133:3128"

async def main():
    print("📡 Запрос ПОЛНОГО списка всех проектов Юрия Литвина (пагинация)...")
    
    b24_proxy = httpx.Proxy(url=SQUID_PROXY_URL)
    
    print("\n==================================================")
    print("📋 ДОСТУПНЫЕ ПРОЕКТЫ И ИХ ИДЕНТИФИКАТОРЫ (ID):")
    print("==================================================")
    
    count = 0
    start_param = 0
    
    async with httpx.AsyncClient(base_url=B24_BASE_URL, proxy=b24_proxy, timeout=45.0) as client:
        try:
            while True:
                # Передаем параметр start для каскадного сбора страниц по 50 штук
                res = await client.post(f"{B24_REST_PATH}socialnetwork.api.workgroup.list.json", json={
                    "select": ["ID", "NAME", "OPENED", "VISIBLE"],
                    "start": start_param
                })
                
                if res.status_code != 200:
                    print(f"🔴 Ошибка сервера Битрикс24 (Статус {res.status_code})")
                    break
                    
                res_json = res.json()
                data = res_json.get("result", {})
                
                # Ключ next для следующей страницы лежит на корневом уровне JSON
                next_start = res_json.get("next")
                groups = data.get("workgroups", data if isinstance(data, list) else [])
                
                if isinstance(groups, list) and groups:
                    for g in groups:
                        if not isinstance(g, dict): continue
                        g_id = g.get('id') or g.get('ID')
                        g_name = g.get('name') or g.get('NAME')
                        
                        if g_id:
                            print(f"🔹 [ID: {g_id}] — {g_name}")
                            count += 1
                
                # Если Битрикс вернул маркер следующей страницы — двигаем указатель, иначе выходим
                if next_start:
                    start_param = int(next_start)
                else:
                    break
                    
            print("==================================================")
            print(f"✅ ИСТИННОЕ КОЛИЧЕСТВО ОБНАРУЖЕННЫХ ПРОЕКТОВ: {count}\n")

        except Exception as err:
            print(f"🔴 Критическая ошибка сетевого вызова: {str(err)}")

if __name__ == "__main__":
    asyncio.run(main())

