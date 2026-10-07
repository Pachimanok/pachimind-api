"""
Conector NotebookLM -> PachiMind: trae transcripciones completas de reuniones
grabadas (fuentes de audio/video en NotebookLM) y las deposita como borradores
en 01 Inbox/Desde IA vía POST /inbox/draft.

Uso:
    .venv/bin/python scripts/import_notebooklm_meetings.py

Requiere:
    - `notebooklm auth check` OK (sesión ya logueada)
    - PachiMind API corriendo (ver PACHIMIND_URL / PACHIMIND_API_KEY abajo)
"""
import json
import subprocess
import sys
from datetime import datetime

import httpx

PACHIMIND_URL = "http://localhost:8001"
PACHIMIND_API_KEY = "pm-personal-dev"

# (notebook_id, source_id, título legible, tags)
MEETINGS = [
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "d3fd662b-a51e-4fd8-a105-5573aacd16e8", "Anexo Reunion Propuesta TTV GGP CAB", ["ggp-cab"]),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "14e7a58b-f5e2-435e-8591-fdac04bd658d", "Audio Conclusiones de Reunion Presentacion TotalView", []),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "7db5b635-c4f9-43cd-9d06-dc1b9274b1a6", "Audio Introduccion Propuesta TotalView", []),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "c7652dc5-5531-440a-91f0-00239cde052d", "Reunion 3M + Giovanna (planes de accion) - 3 de Julio", ["giovanna"]),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "8aa41c8a-2bff-4f80-bac9-3037caa18a6f", "Reunion Genaro Presupuesto 1-3", ["genaro"]),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "e109feaa-de07-4655-9123-afc067a92a4a", "Reunion Genaro Presupuesto 2-3", ["genaro"]),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "507e74d8-cbaf-4487-9298-2cefca4396d9", "Reunion Genaro Presupuesto 3-3", ["genaro"]),
    ("6d8ba0e7-8ea2-4f70-86fd-e57585c4a2af", "7749a970-5f75-48d5-96c1-d2573a1d9d3b", "Reunion con AB 23-7", ["ab"]),
    ("5aa754d2-b673-4fdc-8fcb-f0320fc0d886", "c6e16150-8dc0-48d8-9e9c-71179883e65c", "Reunion 14 de julio 11.07am", []),
    ("5aa754d2-b673-4fdc-8fcb-f0320fc0d886", "fc6c3ae0-9aca-48c3-9b70-8fff2d14181e", "Reunion 30-06-2026 11.59am", []),
    ("5aa754d2-b673-4fdc-8fcb-f0320fc0d886", "c62e586c-8dac-4577-93f0-bd2caba8080e", "Capacitacion Comerciales", ["capacitacion"]),
    ("5aa754d2-b673-4fdc-8fcb-f0320fc0d886", "63430c3b-139a-499a-8e28-582cab3735e9", "Reunion 0 Giovanna y Sabrina", ["giovanna", "sabrina"]),
    ("5aa754d2-b673-4fdc-8fcb-f0320fc0d886", "635f4249-d1dd-470d-9efc-d46aae66f27e", "Reunion Alejo luego Paola", ["alejo", "paola"]),
    ("c0128e4c-2913-4ff6-9210-cf7acfcafeb4", "0c30156c-0b5c-410f-8365-f0ff1c855caa", "Audio Reunion Giovana Operaciones", ["giovanna", "khai"]),
    ("c0128e4c-2913-4ff6-9210-cf7acfcafeb4", "98e7a862-fca5-4e82-9a6e-1feed923a6c4", "Reunion Avenida General San Martin", ["khai"]),
]


def get_fulltext(notebook_id: str, source_id: str) -> dict:
    result = subprocess.run(
        ["notebooklm", "source", "fulltext", source_id, "--notebook", notebook_id, "--json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fulltext failed for {source_id}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def build_content(notebook_id: str, source_id: str, transcript: str) -> str:
    fecha = datetime.now().strftime("%Y-%m-%d")
    return (
        f"> Importado desde NotebookLM el {fecha}. "
        f"Notebook `{notebook_id}` / fuente `{source_id}`.\n\n"
        f"## Transcripción completa\n\n{transcript}\n"
    )


def create_draft(title: str, content: str, tags: list[str]) -> dict:
    payload = {
        "title": title,
        "content": content,
        "area": "Laboral",
        "tipo": "reunion",
        "tags": ["notebooklm", *tags],
    }
    resp = httpx.post(
        f"{PACHIMIND_URL}/inbox/draft",
        json=payload,
        headers={"X-API-Key": PACHIMIND_API_KEY},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    for notebook_id, source_id, title, tags in MEETINGS:
        print(f"-> {title}", flush=True)
        try:
            fulltext = get_fulltext(notebook_id, source_id)
        except Exception as e:
            print(f"   ERROR obteniendo transcripción: {e}", file=sys.stderr)
            continue

        transcript = fulltext.get("content", "")
        if not transcript.strip():
            print("   (transcripción vacía, se omite)", file=sys.stderr)
            continue

        content = build_content(notebook_id, source_id, transcript)
        try:
            result = create_draft(title, content, tags)
        except Exception as e:
            print(f"   ERROR creando borrador: {e}", file=sys.stderr)
            continue

        print(f"   OK -> {result['path']}")


if __name__ == "__main__":
    main()
