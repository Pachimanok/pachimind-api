import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.vault_index import vault_index
from app.core.vault_watcher import start_watcher
from app.routers import meetings, health, vault, notes, search, ai, projects, people, clients, decisions, actions, inbox, links, attachments, notebooklm

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

_observer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _observer
    vault_path = Path(settings.vault_path)
    logger.info(f"Iniciando PachiMind API — vault: {vault_path}")
    vault_index.build(vault_path)
    _observer = start_watcher(str(vault_path))
    yield
    if _observer:
        _observer.stop()
        _observer.join()


app = FastAPI(
    title="PachiMind API",
    description="API para consumir el vault de Obsidian PachiMind",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(vault.router)
app.include_router(notes.router)
app.include_router(search.router)
app.include_router(ai.router)
app.include_router(projects.router)
app.include_router(people.router)
app.include_router(clients.router)
app.include_router(decisions.router)
app.include_router(actions.router)
app.include_router(inbox.router)
app.include_router(links.router)
app.include_router(attachments.router)
app.include_router(notebooklm.router)

app.include_router(meetings.router)
