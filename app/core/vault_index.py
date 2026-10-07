import logging
from pathlib import Path

from rapidfuzz import fuzz

from app.core.vault_parser import parse_note
from app.models.note import NoteModel
from app.models.filters import NoteFilters

logger = logging.getLogger(__name__)

# Carpetas excluidas del índice (relativas al vault root)
EXCLUDED_PREFIXES = (
    "10 Sensible",
    ".obsidian",
    ".claude",
    "99 Adjuntos",
    ".trash",
)


class VaultIndex:
    def __init__(self):
        self._notes: dict[str, NoteModel] = {}
        self._vault_root: Path | None = None

    def build(self, vault_root: Path) -> None:
        vault_root = vault_root.resolve()
        self._vault_root = vault_root
        self._notes.clear()
        count = 0
        for md_file in vault_root.rglob("*.md"):
            if self._is_excluded(md_file, vault_root):
                continue
            note = parse_note(md_file, vault_root)
            if note:
                self._notes[note.id] = note
                count += 1
        logger.info(f"Índice construido: {count} notas")

    def rebuild_file(self, file_path: Path) -> None:
        file_path = file_path.resolve()
        if self._vault_root is None:
            return
        if self._is_excluded(file_path, self._vault_root):
            return
        note = parse_note(file_path, self._vault_root)
        if note:
            self._notes[note.id] = note

    def remove_file(self, file_path: Path) -> None:
        file_path = file_path.resolve()
        if self._vault_root is None:
            return
        from app.core.id_utils import path_to_id
        relative = str(file_path.relative_to(self._vault_root))
        note_id = path_to_id(relative)
        self._notes.pop(note_id, None)

    def get(self, note_id: str) -> NoteModel | None:
        return self._notes.get(note_id)

    def all(self) -> list[NoteModel]:
        return list(self._notes.values())

    def filter(self, filters: NoteFilters) -> list[NoteModel]:
        results = list(self._notes.values())

        if filters.area:
            results = [n for n in results if n.metadata.area == filters.area]
        if filters.tipo:
            results = [n for n in results if n.metadata.tipo == filters.tipo]
        if filters.estado:
            results = [n for n in results if n.metadata.estado == filters.estado]
        if filters.sensibilidad:
            results = [n for n in results if n.metadata.sensibilidad == filters.sensibilidad]
        if filters.cliente:
            results = [n for n in results if n.metadata.cliente == filters.cliente]
        if filters.organizacion:
            results = [n for n in results if n.metadata.organizacion == filters.organizacion]
        if filters.persona:
            results = [n for n in results
                       if any(filters.persona.lower() in p.lower()
                              for p in n.metadata.personas)]
        if filters.proyecto:
            results = [n for n in results
                       if any(filters.proyecto.lower() in p.lower()
                              for p in n.metadata.proyectos)]
        if filters.marca:
            results = [n for n in results if n.metadata.marca == filters.marca]
        if filters.tag:
            results = [n for n in results if filters.tag in n.metadata.tags]
        if filters.revisado is not None:
            results = [n for n in results if n.metadata.revisado == filters.revisado]
        if filters.prioridad:
            results = [n for n in results if n.metadata.prioridad == filters.prioridad]

        return results

    def search(self, query: str, filters: NoteFilters, limit: int = 20) -> list[tuple[NoteModel, float]]:
        candidates = self.filter(filters)
        q = query.lower()
        scored = []
        for note in candidates:
            score = fuzz.partial_ratio(q, f"{note.title} {note.content_text}".lower())
            if score >= 50:
                scored.append((note, score / 100))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def resolve_wikilinks(self, wikilinks: list[str]) -> dict[str, str | None]:
        title_map = {n.title: n.id for n in self._notes.values()}
        return {link: title_map.get(link) for link in wikilinks}

    def stats(self) -> dict:
        notes = list(self._notes.values())
        by_type: dict[str, int] = {}
        by_area: dict[str, int] = {}
        sensitive = 0
        ai_indexable = 0
        to_review = 0

        for n in notes:
            if n.metadata.tipo:
                by_type[n.metadata.tipo] = by_type.get(n.metadata.tipo, 0) + 1
            if n.metadata.area:
                by_area[n.metadata.area] = by_area.get(n.metadata.area, 0) + 1
            if n.metadata.sensibilidad in ("sensible", "secreto", "privado"):
                sensitive += 1
            if n.metadata.ia_indexar and n.metadata.ia_permiso == "allow":
                ai_indexable += 1
            if not n.metadata.revisado:
                to_review += 1

        return {
            "total_notes": len(notes),
            "by_type": by_type,
            "by_area": by_area,
            "sensitive_notes": sensitive,
            "ai_indexable_notes": ai_indexable,
            "notes_to_review": to_review,
        }

    @property
    def connected(self) -> bool:
        return self._vault_root is not None and self._vault_root.exists()

    @staticmethod
    def _is_excluded(file_path: Path, vault_root: Path) -> bool:
        try:
            relative = str(file_path.relative_to(vault_root))
        except ValueError:
            return True
        return any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


vault_index = VaultIndex()
