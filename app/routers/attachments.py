import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.config import settings
from app.middleware.auth import get_scope, SCOPE_PERSONAL

router = APIRouter(prefix="/attachments", tags=["adjuntos"])

ADJUNTOS_DIR = "99 Adjuntos"
MAX_SIZE_MB = 20
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".mp3", ".mp4", ".m4a", ".wav",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".md", ".csv", ".json",
    ".zip",
}


def _safe_filename(name: str) -> str:
    """Convierte el nombre original a un slug seguro manteniendo la extensión."""
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    stem = unicodedata.normalize("NFKD", stem)
    stem = stem.encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-zA-Z0-9\s\-_]", "", stem)
    stem = re.sub(r"\s+", "-", stem.strip())[:60]
    return f"{stem}{ext}" if stem else f"archivo{ext}"


@router.post("")
async def upload_attachment(
    file: UploadFile = File(...),
    scope: str = Depends(get_scope),
):
    if scope != SCOPE_PERSONAL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Scope insuficiente")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Tipo de archivo no permitido: {ext}")

    content = await file.read()
    if len(content) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Archivo demasiado grande (máx {MAX_SIZE_MB}MB)")

    vault_root = Path(settings.vault_path)
    adjuntos_dir = vault_root / ADJUNTOS_DIR
    adjuntos_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename(file.filename or "archivo")
    dest = adjuntos_dir / filename

    # Evitar sobreescribir archivos existentes
    counter = 2
    while dest.exists():
        dest = adjuntos_dir / f"{Path(filename).stem}-{counter}{ext}"
        counter += 1

    dest.write_bytes(content)

    # Sintaxis Obsidian según tipo
    is_image = ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    embed = f"![[{dest.name}]]" if is_image else f"[[{dest.name}]]"

    return {
        "filename": dest.name,
        "path": str(dest.relative_to(vault_root)),
        "size_kb": len(content) // 1024,
        "embed": embed,
        "is_image": is_image,
    }


@router.get("")
def list_attachments(scope: str = Depends(get_scope)):
    vault_root = Path(settings.vault_path)
    adjuntos_dir = vault_root / ADJUNTOS_DIR
    if not adjuntos_dir.exists():
        return {"total": 0, "results": []}

    files = [
        {
            "filename": f.name,
            "path": str(f.relative_to(vault_root)),
            "size_kb": f.stat().st_size // 1024,
            "embed": f"![[{f.name}]]" if f.suffix.lower() in {".png",".jpg",".jpeg",".gif",".webp",".svg"} else f"[[{f.name}]]",
        }
        for f in sorted(adjuntos_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        if f.is_file() and not f.name.startswith(".")
    ]
    return {"total": len(files), "results": files}
