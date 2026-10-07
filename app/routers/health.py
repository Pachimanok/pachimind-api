import subprocess
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends

from app.config import settings
from app.core.vault_index import vault_index
from app.middleware.auth import get_scope
from app.models.responses import HealthResponse

router = APIRouter(tags=["sistema"])

_start_time = time.time()


@router.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        vault_connected=vault_index.connected,
        indexed_notes=len(vault_index.all()),
    )


def _git(args: list[str]) -> str:
    vault = settings.vault_path
    env = {"GIT_DIR": f"{vault}/.git", "GIT_WORK_TREE": vault}
    import os
    full_env = {**os.environ, **env}
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=5, env=full_env
        )
        return result.stdout.strip()
    except Exception:
        return ""


@router.get("/system/status")
def system_status(scope: str = Depends(get_scope)):
    """Estado completo del sistema: API, vault, git sync."""
    vault_root = Path(settings.vault_path)

    # --- Git sync info ---
    last_commit_hash = _git(["log", "-1", "--format=%H"])
    last_commit_msg = _git(["log", "-1", "--format=%s"])
    last_commit_date = _git(["log", "-1", "--format=%ci"])
    last_commit_author = _git(["log", "-1", "--format=%an"])

    # Archivos pendientes (no commiteados)
    status_output = _git(["status", "--short"])
    pending_lines = [l for l in status_output.splitlines() if l.strip()] if status_output else []
    pending_modified = len([l for l in pending_lines if l.startswith(" M") or l.startswith("M")])
    pending_new = len([l for l in pending_lines if l.startswith("??") or l.startswith("A")])
    pending_deleted = len([l for l in pending_lines if l.startswith(" D") or l.startswith("D")])

    # Total commits
    total_commits = _git(["rev-list", "--count", "HEAD"]) or "0"

    # --- API uptime ---
    uptime_secs = int(time.time() - _start_time)
    uptime_str = _format_uptime(uptime_secs)

    # --- Vault disk size ---
    try:
        vault_files = list(vault_root.rglob("*.md"))
        vault_size_kb = sum(f.stat().st_size for f in vault_files) // 1024
    except Exception:
        vault_size_kb = 0

    # --- Stats ---
    notes = vault_index.all()
    by_type = {}
    for n in notes:
        t = n.metadata.tipo or "nota"
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "api": {
            "status": "ok",
            "uptime": uptime_str,
            "uptime_seconds": uptime_secs,
            "started_at": datetime.fromtimestamp(_start_time).isoformat(),
            "indexed_notes": len(notes),
        },
        "vault": {
            "path": str(vault_root),
            "total_notes": len(notes),
            "by_type": by_type,
            "notes_to_review": sum(1 for n in notes if not n.metadata.revisado and n.metadata.estado not in ("borrador", "archivado")),
            "vault_size_kb": vault_size_kb,
        },
        "git": {
            "last_commit_hash": last_commit_hash[:8] if last_commit_hash else None,
            "last_commit_message": last_commit_msg,
            "last_commit_date": last_commit_date,
            "last_commit_author": last_commit_author,
            "total_commits": int(total_commits) if total_commits.isdigit() else 0,
            "pending_modified": pending_modified,
            "pending_new": pending_new,
            "pending_deleted": pending_deleted,
            "is_clean": len(pending_lines) == 0,
        },
    }


def _format_uptime(secs: int) -> str:
    if secs < 60:
        return f"{secs}s"
    elif secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    elif secs < 86400:
        h = secs // 3600
        m = (secs % 3600) // 60
        return f"{h}h {m}m"
    else:
        d = secs // 86400
        h = (secs % 86400) // 3600
        return f"{d}d {h}h"
