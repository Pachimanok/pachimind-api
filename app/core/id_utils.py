import re
import unicodedata


def path_to_id(relative_path: str) -> str:
    """
    '05 Proyectos/Laboral/BOTzero TTG - Implementación.md'
    → '05-proyectos-laboral-botzero-ttg-implementacion'
    """
    path = relative_path.removesuffix(".md")
    path = unicodedata.normalize("NFD", path)
    path = path.encode("ascii", "ignore").decode()
    path = re.sub(r"[^a-zA-Z0-9/]", "-", path)
    path = path.replace("/", "-").lower()
    path = re.sub(r"-+", "-", path).strip("-")
    return path


def extract_title(content: str, filename: str) -> str:
    """Extrae el primer H1 del contenido; si no hay, usa el nombre del archivo."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return filename.removesuffix(".md")


def extract_wikilinks(content: str) -> list[str]:
    """Extrae todos los [[wikilinks]] del contenido markdown."""
    return re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", content)


def content_to_plain_text(content: str) -> str:
    """Convierte markdown a texto plano para búsqueda."""
    # quitar frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2]
    # quitar bloques de código
    content = re.sub(r"```[\s\S]*?```", "", content)
    # quitar wikilinks → texto visible
    content = re.sub(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]",
                     lambda m: m.group(2) or m.group(1), content)
    # quitar markdown syntax
    content = re.sub(r"[#*_`~>\-|]", " ", content)
    content = re.sub(r"\s+", " ", content)
    return content.strip()
