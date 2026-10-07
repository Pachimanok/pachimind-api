"""
Compara las rutas reales de la app contra lo documentado en ENDPOINTS.md.
No falla el build ni bloquea nada — es un chequeo manual para correr antes
de cada deploy y detectar drift como el que dejó afuera /notebooklm/*.

Uso:
    .venv/bin/python scripts/check_endpoints_doc.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENDPOINTS_DOC = REPO_ROOT / "ENDPOINTS.md"

IGNORED_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def real_routes() -> set[str]:
    sys.path.insert(0, str(REPO_ROOT))
    from app.main import app

    routes = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods or path in IGNORED_PATHS:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            routes.add(f"{method} {path}")
    return routes


def documented_routes() -> set[str]:
    text = ENDPOINTS_DOC.read_text(encoding="utf-8")
    matches = re.findall(r"^## (GET|POST|PUT|PATCH|DELETE) (\S+)", text, re.MULTILINE)
    return {f"{m} {p}" for m, p in matches}


def main() -> int:
    real = real_routes()
    documented = documented_routes()

    missing = sorted(real - documented)
    stale = sorted(documented - real)

    if not missing and not stale:
        print("ENDPOINTS.md está al día con las rutas reales.")
        return 0

    if missing:
        print("Rutas reales SIN documentar en ENDPOINTS.md:")
        for r in missing:
            print(f"  + {r}")

    if stale:
        print("Rutas documentadas que ya NO existen en la app:")
        for r in stale:
            print(f"  - {r}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
