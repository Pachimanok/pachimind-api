"""
Digest semanal de PachiMind: junta las notas sin revisar (mismo criterio que
el panel "Para revisar" del front — revisado:false, no borrador/archivado) y
manda un resumen por email. Pensado para correr vía systemd timer semanal en
el VPS (deploy/systemd/weekly-digest.timer), pero funciona igual corrido a
mano en local.

Variables de entorno:
    PACHIMIND_API_URL   default http://127.0.0.1:8000
    PACHIMIND_API_KEY   requerida — key con scope personal/ai_context
    DIGEST_TO           requerida — email destino
    SMTP_HOST           default smtp.hostinger.com
    SMTP_PORT           default 587
    SMTP_USER           requerida
    SMTP_PASSWORD       requerida
    SMTP_FROM           default = SMTP_USER

Uso:
    .venv/bin/python scripts/weekly_digest.py
"""
import os
import smtplib
import sys
from email.message import EmailMessage

import httpx

API_URL = os.environ.get("PACHIMIND_API_URL", "http://127.0.0.1:8000")
API_KEY = os.environ.get("PACHIMIND_API_KEY", "")
DIGEST_TO = os.environ.get("DIGEST_TO", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

EXCLUDED_ESTADOS = {"borrador", "archivado"}


def fetch_pending_review() -> list[dict]:
    notes = []
    page = 1
    with httpx.Client(timeout=30.0) as client:
        while True:
            resp = client.get(
                f"{API_URL}/notes",
                params={"revisado": "false", "per_page": 100, "page": page},
                headers={"X-API-Key": API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
            notes.extend(data.get("results", []))
            if len(notes) >= data.get("total", 0) or not data.get("results"):
                break
            page += 1

    return [
        n for n in notes
        if (n.get("metadata") or {}).get("estado") not in EXCLUDED_ESTADOS
    ]


def build_email(notes: list[dict]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"PachiMind — {len(notes)} nota{'s' if len(notes) != 1 else ''} para revisar"
    msg["From"] = SMTP_FROM
    msg["To"] = DIGEST_TO

    if not notes:
        msg.set_content("No tenés notas pendientes de revisar esta semana. 🎉")
        return msg

    lines = ["Notas que siguen sin marcar como revisadas:", ""]
    for n in notes:
        m = n.get("metadata") or {}
        tipo = m.get("tipo") or "nota"
        area = m.get("area") or ""
        lines.append(f"- {n['title']} ({tipo}, {area}) — {n['path']}")

    lines.append("")
    lines.append("Marcalas como revisadas desde el Tablero en PachiMind cuando les hayas sacado el jugo.")
    msg.set_content("\n".join(lines))
    return msg


def send_email(msg: EmailMessage) -> None:
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def main() -> int:
    missing = [
        name for name, val in [
            ("PACHIMIND_API_KEY", API_KEY), ("DIGEST_TO", DIGEST_TO),
            ("SMTP_USER", SMTP_USER), ("SMTP_PASSWORD", SMTP_PASSWORD),
        ] if not val
    ]
    if missing:
        print(f"Faltan variables de entorno: {', '.join(missing)}", file=sys.stderr)
        return 1

    notes = fetch_pending_review()
    msg = build_email(notes)
    send_email(msg)
    print(f"Digest enviado a {DIGEST_TO} — {len(notes)} nota(s) pendientes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
