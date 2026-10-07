import re
import unicodedata
from pathlib import Path

from app.config import settings
from app.core.id_utils import path_to_id
from app.core.vault_index import vault_index

TIPO_FOLDER: dict[str, str] = {
    "cliente":      "04 Entidades/Clientes",
    "persona":      "04 Entidades/Personas",
    "organizacion": "04 Entidades/Organizaciones",
    "marca":        "04 Entidades/Marcas",
    "proyecto":     "05 Proyectos/{area}",
    "reunion":      "06 Reuniones y Registros/{area}",
    "registro":     "06 Reuniones y Registros/{area}",
    "recurso":      "07 Conocimiento/Recursos",
    "idea":         "07 Conocimiento/Ideas",
    "decision":     "07 Conocimiento/Decisiones",
    "accion":       "09 Acciones/{area}",
}


def write_note(
    title: str,
    tipo: str = "nota",
    area: str = "Laboral",
    estado: str = "activo",
    content: str = "",
    tags: list[str] | None = None,
    cliente: str | None = None,
    personas: list[str] | None = None,
    source_draft_id: str | None = None,
) -> dict:
    if source_draft_id:
        source = vault_index.get(source_draft_id)
        if source and source.metadata.fuente_inmutable:
            from fastapi import HTTPException
            raise HTTPException(409, "La fuente original no puede archivarse como borrador")
    tags = tags or []
    personas = personas or []

    vault_root = Path(settings.vault_path)
    folder_template = TIPO_FOLDER.get(tipo, "01 Inbox/Procesado")
    folder = folder_template.replace("{area}", area)
    target_dir = vault_root / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    # Slugify title → filename
    slug = unicodedata.normalize("NFKD", title.lower())
    slug = "".join(c for c in slug if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9\s\-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())[:50]

    file_path = target_dir / f"{slug}.md"
    counter = 2
    while file_path.exists():
        file_path = target_dir / f"{slug}-v{counter}.md"
        counter += 1

    tags_yaml   = "\n".join(f"  - {t}" for t in tags)   if tags    else "  []"
    people_yaml = "\n".join(f'  - "{p}"' for p in personas) if personas else "  []"

    # Las reuniones nacen sin revisar: son justo el tipo de nota que se
    # quiere volver a mirar para "sacarle el jugo" más adelante.
    revisado = "false" if tipo == "reunion" else "true"

    note_text = f"""---
tipo: {tipo}
estado: {estado}
area: {area}
cliente: {cliente or ""}
personas:
{people_yaml}
sensibilidad: normal
ia_permiso: allow
ia_indexar: true
ia_editar: false
revisado: {revisado}
origen: inbox_ia
tags:
{tags_yaml}
---

{content.strip()}
"""
    file_path.write_text(note_text, encoding="utf-8")

    relative_path = str(file_path.relative_to(vault_root))
    note_id = path_to_id(relative_path)
    vault_index.rebuild_file(file_path)

    if source_draft_id:
        archive_draft(source_draft_id)

    return {"id": note_id, "path": relative_path, "filename": file_path.name}


def archive_draft(draft_id: str) -> None:
    vault_root = Path(settings.vault_path)
    src = vault_index.get(draft_id)
    if not src:
        return
    src_path = vault_root / src.path
    if not src_path.exists():
        return
    txt = src_path.read_text(encoding="utf-8")
    txt = txt.replace("estado: borrador", "estado: archivado", 1)
    src_path.write_text(txt, encoding="utf-8")
    vault_index.rebuild_file(src_path)


def delete_note(note_id: str) -> bool:
    note = vault_index.get(note_id)
    if not note:
        return False
    file_path = Path(settings.vault_path) / note.path
    if file_path.exists():
        file_path.unlink()
    vault_index.remove_file(file_path)
    return True
