import os
import asyncio
from cmdop import LocalTransport
import openclaw

async def main():
    # 1. Явно создаем локальный транспорт, передавая обязательную структуру agent_info,
    # но оборачивая её в правильный конфигурационный класс, который требует gRPC-клиент
    from cmdop import CMDOPClient
    
    print("Инициализация локального браузерного движка OpenClaw...")
    # Так как cmdop agent start не работает глобально, мы поднимаем In-Process сессию
    transport = LocalTransport() 
    
    async with openclaw.AsyncOpenClaw(transport=transport) as client:
        ui_instruction = (
            "1. Открой браузер Chromium.\n"
            "2. Перейди на сайт https://crm.medtech.moscow.\n"
            "3. Введи доменный логин 'HQ\\LitvinYN' и пароль приложения из .env.\n"
            "4. Выгрузи все активные Scrum-задачи в файл контекста.\n"
            "5. Перейди на страницу https://medtech.moscow \n"
            "6. Найди текстовое поле для комментариев, введи 'Задача уже в работе' и кликни кнопку 'Отправить'."
        )
        print("Робот OpenClaw запускает Chromium и эмулирует действия в UI...")
        result = await client.agent.run(ui_instruction)
        print(f"Результат выполнения: {result}")

if __name__ == "__main__":
    asyncio.run(main())
