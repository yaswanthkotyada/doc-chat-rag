from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.chat import router as chat_router
from app.routers.conversations import router as conversations_router
from app.routers.health import router as health_router

app = FastAPI(title="DOC_POC API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(conversations_router)
app.include_router(chat_router)


@app.get("/")
async def root():
    return {"message": "DOC_POC API is running"}
