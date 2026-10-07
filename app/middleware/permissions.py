from app.models.note import NoteModel

# Sensibilidades bloqueadas por scope
SCOPE_RULES: dict[str, dict] = {
    "personal": {
        "blocked_sensibilidad": {"secreto"},
        "require_ia_permiso": False,
    },
    "ai_context": {
        "blocked_sensibilidad": {"privado", "sensible", "secreto"},
        "require_ia_permiso": True,
        "require_ia_indexar": True,
    },
    "public": {
        "blocked_sensibilidad": {"interno", "privado", "sensible", "secreto"},
        "require_ia_permiso": False,
    },
}

# Reglas estrictas para el endpoint /ai/context — no configurables
AI_BLOCKED_SENSIBILIDAD = {"sensible", "secreto", "privado"}


def is_visible(note: NoteModel, scope: str) -> bool:
    rules = SCOPE_RULES.get(scope, SCOPE_RULES["public"])
    if note.metadata.sensibilidad in rules["blocked_sensibilidad"]:
        return False
    if rules.get("require_ia_permiso") and note.metadata.ia_permiso != "allow":
        return False
    if rules.get("require_ia_indexar") and not note.metadata.ia_indexar:
        return False
    return True


def is_ai_eligible(note: NoteModel) -> bool:
    return (
        note.metadata.ia_permiso == "allow"
        and note.metadata.ia_indexar is True
        and note.metadata.sensibilidad not in AI_BLOCKED_SENSIBILIDAD
    )


def apply_content_rules(note: NoteModel, scope: str) -> tuple[str | None, str | None]:
    """Devuelve (content, excerpt) según los permisos."""
    excerpt = note.content_text[:400] + "..." if len(note.content_text) > 400 else note.content_text

    if scope == "personal":
        if note.metadata.ia_permiso == "summary_only":
            return None, excerpt
        return note.content, excerpt

    # ai_context y public: solo excerpt
    return None, excerpt
