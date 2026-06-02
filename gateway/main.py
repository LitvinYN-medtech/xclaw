from fastapi import FastAPI
import asyncpg
import redis.asyncio as aioredis

app = FastAPI(title="OpenClaw Data API Gateway")

# Константы подключения (настройки из нашего docker-compose.yml)
PG_URL = "postgresql://gateway_user:secret_password@127.0.0.1:5432/gateway_db"
REDIS_URL = "redis://127.0.0.1:6379/0"

@app.get("/")
async def root():
    return {"status": "Gateway is active"}

@app.get("/health-check")
async def health_check():
    health = {"postgres": "unknown", "redis": "unknown"}
    
    # 1. Тестируем подключение к PostgreSQL
    try:
        conn = await asyncpg.connect(PG_URL)
        # Получаем версию СУБД для проверки
        version = await conn.fetchval("SELECT version();")
        await conn.close()
        health["postgres"] = f"Connected! ({version.split()[1]})"
    except Exception as e:
        health["postgres"] = f"Failed: {str(e)}"
        
    # 2. Тестируем подключение к Redis
    try:
        r = aioredis.from_url(REDIS_URL)
        # Отправляем команду PING, ожидаем ответ PONG
        pong = await r.ping()
        await r.close()
        health["redis"] = "Connected! (PONG)" if pong else "No response"
    except Exception as e:
        health["redis"] = f"Failed: {str(e)}"
        
    return health
