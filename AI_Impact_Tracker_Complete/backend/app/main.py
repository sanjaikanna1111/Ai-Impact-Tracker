from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.config import settings
from app.db import init_db

@asynccontextmanager
async def lifespan(app:FastAPI):
    await init_db(); yield

app=FastAPI(title='AI Impact Tracker API',version='1.0.0',lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list({
        settings.frontend_origin,
        'http://localhost:3000',
        'http://127.0.0.1:3000',
    }),
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.include_router(router,prefix='/api')
