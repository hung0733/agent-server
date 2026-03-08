import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from db.conn_pool import ConnPool
from global_var import GlobalVar

# 讀取 .env 檔案
load_dotenv()

GlobalVar.conn_pool = ConnPool()

app = FastAPI(lifespan=GlobalVar.conn_pool.lifespan)

@app.get("/health")
async def health_check():
    return {"status": "online", "database": "connected"}

