from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.config import settings
from app.core.vault_index import vault_index
from app.core.vault_linker import (
    generate_links, get_broken_links, suggest_semantic_links, _update_related_section,
    _build_title_map, _to_wikilink, _clean_title, EXCLUDED_PREFIXES,
)
from app.middleware.auth import get_scope, SCOPE_PERSONAL

router = APIRouter(prefix="/vault/links", tags=["links"])


def _require_personal(scope: str) -> None:
    if scope != SCOPE_PERSONAL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este endpoint requiere scope 'personal'",
        )


@router.post("/generate")
def generate_vault_links(
    dry_run: bool = Query(True, description="Si false, escribe los cambios en disco"),
    scope: str = Depends(get_scope),
):
    """
    Genera wikilinks en el vault:
    - Convierte campos personas/proyectos/cliente a [[wikilinks]]
    - Agrega sección '## Notas relacionadas' con títulos mencionados en el cuerpo

    Con dry_run=true (default) solo reporta, sin escribir.
    """
    _require_personal(scope)
    vault_root = Path(settings.vault_path)
    results = generate_links(vault_index, vault_root, dry_run=dry_run)

    total_changes = sum(len(r.changes) for r in results)
    return {
        "dry_run": dry_run,
        "notes_affected": len(results),
        "total_changes": total_changes,
        "results": [
            {
                "note_id": r.note_id,
                "title": r.title,
                "path": r.path,
                "changes": [
                    {"field": c.field, "old": c.old, "new": c.new}
                    for c in r.changes
                ],
            }
            for r in results
        ],
    }


@router.get("/broken")
def broken_links(scope: str = Depends(get_scope)):
    """Lista todos los [[wikilinks]] que apuntan a notas inexistentes."""
    _require_personal(scope)
    broken = get_broken_links(vault_index)
    return {"total": len(broken), "results": broken}


@router.get("/suggest/{note_id}")
async def suggest_links(
    note_id: str,
    max_suggestions: int = Query(5, ge=1, le=10),
    scope: str = Depends(get_scope),
):
    """Usa Gemini para sugerir relaciones semánticas para una nota. Solo lee."""
    _require_personal(scope)
    note = vault_index.get(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Nota no encontrada")
    if note.metadata.fuente_inmutable:
        raise HTTPException(409, "Fuente original protegida. Usá la revisión de reuniones.")
    suggestions = await suggest_semantic_links(note, vault_index, max_suggestions)
    return {
        "note_id": note_id,
        "note_title": _clean_title(note.title),
        "suggestions": suggestions,
    }


class ApplyLinksItem(BaseModel):
    source_id: str
    target_id: str


class ApplyLinksRequest(BaseModel):
    links: List[ApplyLinksItem]


@router.post("/apply")
def apply_links(body: ApplyLinksRequest, scope: str = Depends(get_scope)):
    """Aplica sugerencias de links: agrega los target en 'Notas relacionadas' del source."""
    _require_personal(scope)
    vault_root = Path(settings.vault_path)
    title_map = _build_title_map(vault_index.all())
    applied = 0
    results = []

    import re
    import frontmatter
    import yaml

    _link_re = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")

    for item in body.links:
        source = vault_index.get(item.source_id)
        target = vault_index.get(item.target_id)
        if not source or not target:
            results.append({"source_id": item.source_id, "ok": False, "error": "nota no encontrada"})
            continue

        if source.metadata.fuente_inmutable:
            results.append({"source_id": item.source_id, "ok": False, "error": "Fuente original protegida"})
            continue
        file_path = vault_root / source.path
        try:
            post = frontmatter.load(str(file_path))
            target_title = _clean_title(target.title)
            wikilink = f"[[{target_title}]]"
            section_header = "## Notas relacionadas"
            section_re = re.compile(r"## Notas relacionadas\n((?:- \[\[.+?\]\]\n?)*)", re.MULTILINE)

            # Check if link already exists anywhere in the note
            all_links = set(t.rstrip("|").strip() for t in _link_re.findall(post.content))
            all_links.update(t.rstrip("|").strip() for t in _link_re.findall(
                yaml.dump(dict(post.metadata), allow_unicode=True)
            ))
            if target_title in all_links or target_title.replace("|","").strip() in all_links:
                results.append({"source_id": item.source_id, "ok": True, "note": "ya existía el link"})
                continue

            # Force-add to "Notas relacionadas" section
            existing_match = section_re.search(post.content)
            new_item = f"- {wikilink}"
            if existing_match:
                old_section = existing_match.group(0)
                new_section = old_section.rstrip("\n") + f"\n{new_item}\n"
                post.content = post.content.replace(old_section, new_section, 1)
            else:
                post.content = post.content.rstrip("\n") + f"\n\n{section_header}\n{new_item}\n"

            file_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            vault_index.rebuild_file(file_path)
            applied += 1
            results.append({"source_id": item.source_id, "ok": True})
        except Exception as e:
            results.append({"source_id": item.source_id, "ok": False, "error": str(e)})

    return {"applied": applied, "results": results}
