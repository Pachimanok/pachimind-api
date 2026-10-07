import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

EXCLUDED_PREFIXES = ("01 Inbox", "00 Sistema", ".obsidian", ".claude", "99 Adjuntos")
FUZZY_THRESHOLD = 72  # mínimo score para aceptar un match
MIN_TITLE_LEN = 6     # títulos menores a esto no se buscan en el cuerpo


def _clean_title(title: str) -> str:
    """Elimina wikilinks del título: 'Genaro — [[TTG]]' → 'Genaro — TTG'."""
    return re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", title).strip()


@dataclass
class LinkChange:
    field: str   # "personas" | "proyectos" | "cliente" | "body"
    old: str
    new: str


@dataclass
class NoteLinks:
    note_id: str
    title: str
    path: str
    changes: list[LinkChange] = field(default_factory=list)


def _is_wikilink(value: str) -> bool:
    return value.startswith("[[") and value.endswith("]]")


def _to_wikilink(title: str) -> str:
    return f"[[{_clean_title(title)}]]"


def _build_title_map(notes) -> dict[str, object]:
    """Devuelve {título_limpio_lower: NoteModel}. Limpia wikilinks del título."""
    result = {}
    for n in notes:
        clean = _clean_title(n.title)
        result[clean.lower()] = n
    return result


def _find_match(value: str, title_map: dict, self_title: str) -> object | None:
    """Encuentra la nota que mejor coincide con `value`."""
    val = value.strip().lower()
    clean_self = _clean_title(self_title).lower()

    # Match exacto
    if val in title_map:
        n = title_map[val]
        clean_n = _clean_title(n.title).lower()
        if clean_n != clean_self:
            return n
        # El valor coincide con la nota misma → no hacer fallback
        return None

    # El valor está contenido en algún título (ej. "Fernando" en "Fernando — Total Trade Group")
    # Preferir matches donde el título EMPIEZA con el valor (más preciso)
    candidates = [
        t for t in title_map
        if val in t and _clean_title(title_map[t].title).lower() != clean_self
    ]
    starts_with = [t for t in candidates if t.startswith(val)]
    if starts_with:
        candidates = starts_with
    if len(candidates) == 1:
        return title_map[candidates[0]]
    if len(candidates) > 1:
        # Preferir el más corto (más específico)
        return title_map[min(candidates, key=len)]

    # Fuzzy fallback solo si el valor es lo suficientemente largo (evita falsos positivos)
    if len(val) < 5:
        return None

    result = process.extractOne(val, list(title_map.keys()), scorer=fuzz.partial_ratio)
    if result and result[1] >= FUZZY_THRESHOLD:
        n = title_map[result[0]]
        if _clean_title(n.title).lower() != clean_self:
            return n

    return None


def _link_list_field(values: list, title_map: dict, self_title: str) -> tuple[list, list[LinkChange]]:
    """Convierte strings planos de un campo YAML list a wikilinks."""
    new_values = []
    changes = []
    for v in values:
        v_str = str(v)
        if _is_wikilink(v_str):
            new_values.append(v_str)
            continue
        matched = _find_match(v_str, title_map, self_title)
        if matched:
            linked = _to_wikilink(matched.title)
            changes.append(LinkChange("personas_proyectos", v_str, linked))
            new_values.append(linked)
        else:
            new_values.append(v_str)
    return new_values, changes


def _link_string_field(value: str | None, title_map: dict, self_title: str, field_name: str) -> tuple[str | None, LinkChange | None]:
    """Convierte un campo YAML string a wikilink si hay match."""
    if not value or not isinstance(value, str) or _is_wikilink(value):
        return value, None
    matched = _find_match(value, title_map, self_title)
    if matched:
        linked = _to_wikilink(matched.title)
        return linked, LinkChange(field_name, value, linked)
    return value, None


def _update_related_section(body: str, frontmatter_str: str, title_map: dict, self_title: str) -> tuple[str, LinkChange | None]:
    """Agrega/actualiza sección '## Notas relacionadas' con títulos mencionados en el cuerpo."""
    section_header = "## Notas relacionadas"
    section_re = re.compile(r"## Notas relacionadas\n((?:- \[\[.+?\]\]\n?)*)", re.MULTILINE)

    # Regex que maneja alias vacíos: [[Title|]] o [[Title|Alias]] o [[Title]]
    _link_re = re.compile(r"\[\[([^\]|#]+?)(?:[|#][^\]]*?)?\]\]")

    # Links ya presentes en cuerpo Y frontmatter (para evitar duplicados)
    existing_linked = set(_link_re.findall(body))
    existing_linked.update(_link_re.findall(frontmatter_str))
    # Normalizar: quitar pipes del final (ej. "Pablo — Rail" de "Pablo — Rail|")
    existing_linked = {t.rstrip("|").strip() for t in existing_linked}

    body_lower = body.lower()
    new_related: list[str] = []
    for title_key, note in title_map.items():
        if note.title == self_title:
            continue
        clean_t = _clean_title(note.title)
        if clean_t in existing_linked or note.title in existing_linked:
            continue
        if len(title_key) < MIN_TITLE_LEN:
            continue
        if title_key in body_lower:
            new_related.append(clean_t)

    if not new_related:
        return body, None

    # Eliminar títulos ya presentes en la sección existente
    existing_match = section_re.search(body)
    if existing_match:
        section_links = set(_link_re.findall(existing_match.group(1)))
        section_links = {t.rstrip("|").strip() for t in section_links}
        new_related = [t for t in new_related if t.replace("|", "").strip() not in section_links]

    if not new_related:
        return body, None

    new_related.sort()
    new_items = "\n".join(f"- {_to_wikilink(t)}" for t in new_related)

    if existing_match:
        old_section = existing_match.group(0)
        new_section = old_section.rstrip("\n") + "\n" + new_items + "\n"
        new_body = body.replace(old_section, new_section, 1)
    else:
        new_body = body.rstrip("\n") + f"\n\n{section_header}\n{new_items}\n"

    return new_body, LinkChange("body", "", new_items)


def generate_links(index, vault_root: Path, dry_run: bool = True) -> list[NoteLinks]:
    """
    Para cada nota del vault (excluye Inbox y Sistema):
    - Convierte campos personas/proyectos/cliente a [[wikilinks]]
    - Agrega sección "Notas relacionadas" con títulos mencionados en el cuerpo

    dry_run=True: solo reporta, no escribe.
    """
    all_notes = index.all()
    title_map = _build_title_map(all_notes)

    target_notes = [
        n for n in all_notes
        if not n.metadata.fuente_inmutable and not any(n.path.startswith(p) for p in EXCLUDED_PREFIXES)
    ]

    results: list[NoteLinks] = []

    for note in target_notes:
        note_links = NoteLinks(note_id=note.id, title=note.title, path=note.path)
        file_path = vault_root / note.path

        try:
            post = frontmatter.load(str(file_path))
        except Exception as e:
            logger.warning(f"No se pudo leer {note.path}: {e}")
            continue

        frontmatter_changed = False
        new_meta = dict(post.metadata)

        # --- personas ---
        personas = post.metadata.get("personas") or []
        if isinstance(personas, list) and personas:
            new_personas, p_changes = _link_list_field(personas, title_map, note.title)
            if p_changes:
                for c in p_changes:
                    c.field = "personas"
                    note_links.changes.append(c)
                new_meta["personas"] = new_personas
                frontmatter_changed = True

        # --- proyectos ---
        proyectos = post.metadata.get("proyectos") or []
        if isinstance(proyectos, list) and proyectos:
            new_proyectos, pr_changes = _link_list_field(proyectos, title_map, note.title)
            if pr_changes:
                for c in pr_changes:
                    c.field = "proyectos"
                    note_links.changes.append(c)
                new_meta["proyectos"] = new_proyectos
                frontmatter_changed = True

        # --- cliente ---
        cliente = post.metadata.get("cliente")
        new_cliente, c_change = _link_string_field(cliente, title_map, note.title, "cliente")
        if c_change:
            note_links.changes.append(c_change)
            new_meta["cliente"] = new_cliente
            frontmatter_changed = True

        # --- body: notas relacionadas ---
        import yaml
        fm_str = yaml.dump(dict(post.metadata), allow_unicode=True)
        new_body, body_change = _update_related_section(post.content, fm_str, title_map, note.title)
        if body_change:
            note_links.changes.append(body_change)

        if not dry_run and note_links.changes:
            if frontmatter_changed:
                for k, v in new_meta.items():
                    post.metadata[k] = v
            if body_change:
                post.content = new_body
            try:
                file_path.write_text(frontmatter.dumps(post), encoding="utf-8")
                index.rebuild_file(file_path)
                logger.info(f"Links actualizados: {note.path}")
            except Exception as e:
                logger.error(f"Error escribiendo {note.path}: {e}")

        if note_links.changes:
            results.append(note_links)

    return results


def generate_links_for_note(
    index, vault_root: Path, note, dry_run: bool = False
) -> NoteLinks | None:
    """
    Versión single-note de generate_links(). Usada por el watcher para auto-linking.
    Procesa solo la nota dada pero usa el índice completo para el title_map.
    """
    if note.metadata.fuente_inmutable or any(note.path.startswith(p) for p in EXCLUDED_PREFIXES):
        return None

    title_map = _build_title_map(index.all())
    note_links = NoteLinks(note_id=note.id, title=note.title, path=note.path)
    file_path = vault_root / note.path

    try:
        post = frontmatter.load(str(file_path))
    except Exception as e:
        logger.warning(f"No se pudo leer {note.path}: {e}")
        return None

    frontmatter_changed = False
    new_meta = dict(post.metadata)

    personas = post.metadata.get("personas") or []
    if isinstance(personas, list) and personas:
        new_personas, p_changes = _link_list_field(personas, title_map, note.title)
        if p_changes:
            for c in p_changes:
                c.field = "personas"
                note_links.changes.append(c)
            new_meta["personas"] = new_personas
            frontmatter_changed = True

    proyectos = post.metadata.get("proyectos") or []
    if isinstance(proyectos, list) and proyectos:
        new_proyectos, pr_changes = _link_list_field(proyectos, title_map, note.title)
        if pr_changes:
            for c in pr_changes:
                c.field = "proyectos"
                note_links.changes.append(c)
            new_meta["proyectos"] = new_proyectos
            frontmatter_changed = True

    cliente = post.metadata.get("cliente")
    new_cliente, c_change = _link_string_field(cliente, title_map, note.title, "cliente")
    if c_change:
        note_links.changes.append(c_change)
        new_meta["cliente"] = new_cliente
        frontmatter_changed = True

    import yaml
    fm_str = yaml.dump(dict(post.metadata), allow_unicode=True)
    new_body, body_change = _update_related_section(post.content, fm_str, title_map, note.title)
    if body_change:
        note_links.changes.append(body_change)

    if not dry_run and note_links.changes:
        if frontmatter_changed:
            for k, v in new_meta.items():
                post.metadata[k] = v
        if body_change:
            post.content = new_body
        try:
            file_path.write_text(frontmatter.dumps(post), encoding="utf-8")
            index.rebuild_file(file_path)
        except Exception as e:
            logger.error(f"Error escribiendo {note.path}: {e}")

    return note_links if note_links.changes else None


async def suggest_semantic_links(
    note, index, max_suggestions: int = 5
) -> list[dict]:
    """
    Usa Gemini (via Node server) para encontrar relaciones semánticas
    con otras notas del vault. Solo lee, no escribe.
    Devuelve: [{"note_id", "title", "path", "reason"}]
    """
    import json
    import httpx
    from app.config import settings

    # Construir lista de candidatas (excluir la propia nota y notas de Inbox)
    candidates = [
        n for n in index.all()
        if n.id != note.id and not n.path.startswith("01 Inbox")
    ]

    candidate_list = "\n".join(
        f"{n.id} | {_clean_title(n.title)} | {n.metadata.tipo or ''} | {n.content_text[:80]}"
        for n in candidates
    )

    note_body = note.content_text[:800] if note.content_text else ""

    prompt = f"""Sos un asistente de gestión de conocimiento personal. Encontrá las notas más relacionadas semánticamente con la nota objetivo.

NOTA OBJETIVO:
Título: {_clean_title(note.title)}
Tipo: {note.metadata.tipo or 'nota'} | Área: {note.metadata.area or ''}
Contenido: {note_body}

NOTAS DISPONIBLES (id | título | tipo | resumen):
{candidate_list}

Devolvé SOLO un JSON array con las {max_suggestions} notas más relevantes (puede ser menos si no hay suficientes relaciones reales):
[{{"note_id": "...", "reason": "una oración explicando la relación"}}]

Solo JSON, sin markdown ni texto extra."""

    node_url = getattr(settings, "node_url", "http://127.0.0.1:3000")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{node_url}/api/ai/chat/internal",
                json={"message": prompt},
                headers={"X-PachiMind-Internal-Key": settings.pm_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text", "")

            # Extraer JSON de la respuesta
            json_start = text.find("[")
            json_end = text.rfind("]") + 1
            if json_start == -1 or json_end == 0:
                return []
            suggestions_raw = json.loads(text[json_start:json_end])

            results = []
            for s in suggestions_raw:
                note_id = s.get("note_id", "")
                target = index.get(note_id)
                if target:
                    results.append({
                        "note_id": note_id,
                        "title": _clean_title(target.title),
                        "path": target.path,
                        "reason": s.get("reason", ""),
                    })
            return results
    except Exception as e:
        logger.error(f"suggest_semantic_links error: {e}")
        return []


def get_broken_links(index) -> list[dict]:
    """Devuelve todos los [[wikilinks]] que apuntan a notas inexistentes."""
    from pathlib import Path
    title_set: set[str] = set()
    for n in index.all():
        title_set.add(n.title)
        # Título limpio (sin wikilinks embebidos en H1)
        title_set.add(_clean_title(n.title).replace("|", "").strip())
        # Nombre de archivo como alternativa (filename sin extensión)
        filename_title = Path(n.path).stem
        title_set.add(filename_title)
        title_set.add(_clean_title(filename_title).strip())

    # Ignorar links de plantillas
    TEMPLATE_LINKS = {"Nota", "Nombre de la Nota", "Proyecto Relacionado",
                      "Persona Relacionada", "Juan Perez - Mi Cliente",
                      "Portal Clientes - Implementacion", "00 Sistema/Configuracion IA/MANUAL_IA"}

    broken = []
    for note in index.all():
        for link in note.wikilinks:
            clean = link.split("|")[0].split("#")[0].strip()
            if not clean or clean in TEMPLATE_LINKS:
                continue
            clean_norm = _clean_title(clean).replace("|", "").strip()
            if clean not in title_set and clean_norm not in title_set:
                broken.append({
                    "note_id": note.id,
                    "note_title": note.title,
                    "note_path": note.path,
                    "broken_link": clean,
                })
    return broken
