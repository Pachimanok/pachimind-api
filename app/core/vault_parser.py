from pathlib import Path
from datetime import datetime

import frontmatter

from app.models.note import NoteModel, NoteMetadata
from app.core.id_utils import path_to_id, extract_title, extract_wikilinks, content_to_plain_text


def parse_note(file_path: Path, vault_root: Path) -> NoteModel | None:
    try:
        relative_path = str(file_path.relative_to(vault_root))
        post = frontmatter.load(str(file_path))

        raw_meta = dict(post.metadata)
        content = post.content

        # Normalizar listas que pueden venir como string o tener elementos no-string (ej. 2024 como int)
        for list_field in ("personas", "proyectos", "tags"):
            val = raw_meta.get(list_field, [])
            if isinstance(val, str):
                raw_meta[list_field] = [val] if val else []
            elif val is None:
                raw_meta[list_field] = []
            elif isinstance(val, list):
                raw_meta[list_field] = [str(v) for v in val]

        # Aceptar el campo singular usado por notas y manuales históricos.
        singular = raw_meta.get("proyecto")
        if singular:
            values = singular if isinstance(singular, list) else [singular]
            raw_meta["proyectos"] = list(dict.fromkeys(
                raw_meta.get("proyectos", []) + [str(v) for v in values if v]
            ))

        # Normalizar fecha: YAML puede parsear "2022" o "2026-03" como datetime/int
        if "fecha" in raw_meta and raw_meta["fecha"] is not None:
            raw_meta["fecha"] = str(raw_meta["fecha"])

        metadata = NoteMetadata.model_validate(raw_meta)

        title = (str(raw_meta.get("titulo")) if raw_meta.get("titulo") else extract_title(content, file_path.name))
        wikilinks = extract_wikilinks(content)
        content_text = content_to_plain_text(content)
        last_modified = datetime.fromtimestamp(file_path.stat().st_mtime)

        return NoteModel(
            id=path_to_id(relative_path),
            path=relative_path,
            title=title,
            metadata=metadata,
            content=content,
            content_text=content_text,
            wikilinks=wikilinks,
            last_modified=last_modified,
        )
    except Exception:
        return None
