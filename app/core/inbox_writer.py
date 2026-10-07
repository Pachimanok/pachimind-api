from datetime import date
from pathlib import Path

from app.config import settings
from app.core.id_utils import path_to_id
from app.core.vault_index import vault_index


def write_draft(
    title: str,
    content: str = "",
    area: str = "Personal",
    tipo: str = "nota",
    cliente: str | None = None,
    proyecto: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    tags = tags or []
    vault_root = Path(settings.vault_path)
    inbox_dir = vault_root / "01 Inbox" / "Desde IA"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    slug = title.lower()[:40].replace(" ", "-")
    filename = f"{today}-{slug}.md"

    # Evitar sobreescribir
    file_path = inbox_dir / filename
    counter = 2
    while file_path.exists():
        file_path = inbox_dir / f"{today}-{slug}-v{counter}.md"
        counter += 1

    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else "  []"
    cliente_line = f"cliente: {cliente}" if cliente else "cliente:"
    proyecto_line = f"proyecto: {proyecto}" if proyecto else "proyecto:"

    frontmatter = f"""---
tipo: {tipo}
estado: borrador
area: {area}
{cliente_line}
{proyecto_line}
sensibilidad: normal
ia_permiso: allow
ia_indexar: false
ia_editar: false
revisado: false
origen: desde_ia
tags:
{tags_yaml}
---

# {title}

{content}
"""

    file_path.write_text(frontmatter, encoding="utf-8")

    relative_path = str(file_path.relative_to(vault_root))
    note_id = path_to_id(relative_path)

    # Indexar inmediatamente
    vault_index.rebuild_file(file_path)

    return {"id": note_id, "path": relative_path, "filename": file_path.name}
