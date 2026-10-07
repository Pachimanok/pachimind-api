import json
import subprocess

from app.config import settings


class NotebookLMError(RuntimeError):
    pass


def _run_json(args: list[str], timeout: int = 120) -> dict:
    try:
        result = subprocess.run(
            [settings.notebooklm_bin, *args, "--json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise NotebookLMError(
            f"No se encontró el binario '{settings.notebooklm_bin}'. "
            "¿Está instalado y en el PATH del proceso de la API?"
        )
    except subprocess.TimeoutExpired:
        raise NotebookLMError("La CLI de notebooklm no respondió a tiempo")

    if result.returncode != 0:
        raise NotebookLMError(result.stderr.strip() or "notebooklm CLI falló")

    return json.loads(result.stdout)


def list_notebooks() -> list[dict]:
    data = _run_json(["list"])
    return data["notebooks"]


def list_sources(notebook_id: str) -> list[dict]:
    data = _run_json(["source", "list", "--notebook", notebook_id])
    return data["sources"]


def get_source_fulltext(notebook_id: str, source_id: str) -> str:
    data = _run_json(["source", "fulltext", source_id, "--notebook", notebook_id])
    return data.get("content", "")
