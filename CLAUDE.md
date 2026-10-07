# PachiMind API

API REST sobre un vault de Obsidian. Lee archivos `.md` directamente del sistema de archivos, los indexa en memoria al arrancar, y los sirve con control de acceso por scopes. No usa base de datos.

## Stack

- Python 3.11+, FastAPI, Uvicorn
- Pydantic v2, pydantic-settings
- `python-frontmatter` — parseo de YAML frontmatter
- `rapidfuzz` — búsqueda fuzzy
- `watchdog` — hot-reload del índice cuando cambian archivos

## Comandos

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # editar VAULT_PATH y API_KEYS

# Dev
uvicorn app.main:app --reload

# Docker
docker compose up
```

Docs interactivas en `http://localhost:8000/docs` cuando corre localmente.

## Variables de entorno

| Variable | Formato | Descripción |
|---|---|---|
| `VAULT_PATH` | string | Ruta absoluta al vault de Obsidian |
| `API_KEYS` | JSON `{"clave": "scope"}` | Mapa de API keys a scopes |
| `LOG_LEVEL` | string | Default: `INFO` |
| `CORS_ORIGINS` | JSON array | Default: `["*"]` |
| `NODE_URL` | string | Default: `http://127.0.0.1:3000`. Base URL del servidor Node (`pachimind-web`, repo hermano en `../pachimind-web`) que expone `/api/ai/chat/internal` hablando con Gemini. Lo usa únicamente `vault_linker.suggest_semantic_links()` |
| `NOTEBOOKLM_BIN` | string | Default: `notebooklm`. Path al binario del CLI `notebooklm-py` (skill `~/.claude/skills/notebooklm`), usado por `core/notebooklm_importer.py` vía subprocess. En prod: `/srv/pachimind/api/.venv/bin/notebooklm` |

Scopes válidos: `personal`, `ai_context`, `public`.

## Arquitectura

```
app/
├── main.py              # FastAPI app + lifespan (build index, start watcher)
├── config.py            # Settings via pydantic-settings
├── core/
│   ├── vault_index.py   # Índice en memoria: build, filter, search, stats
│   ├── vault_parser.py  # .md → NoteModel (frontmatter + contenido)
│   ├── vault_watcher.py # watchdog → rebuild_file / remove_file en cambios
│   ├── vault_linker.py  # wikifica personas/proyectos/cliente, arma "Notas relacionadas", sugerencias semánticas vía Gemini
│   ├── note_writer.py   # TIPO_FOLDER, write_note(), archive_draft(), delete_note() — usado por POST /notes, /notes/{id}/promote, DELETE /notes/{id}
│   ├── inbox_writer.py  # write_draft() — usado por POST /inbox/draft y POST /notebooklm/import
│   ├── notebooklm_importer.py  # wrapper del CLI `notebooklm` (list_notebooks, list_sources, get_source_fulltext)
│   └── id_utils.py      # path → id (slug), extract_title, wikilinks
├── middleware/
│   ├── auth.py          # X-API-Key header → scope string
│   └── permissions.py   # is_visible(), is_ai_eligible(), apply_content_rules()
├── models/
│   ├── note.py          # NoteMetadata, NoteModel, NoteResponse, NoteSummary
│   ├── filters.py       # NoteFilters, AIContextRequest
│   └── responses.py     # Response models de cada router
└── routers/             # Un archivo por recurso
```

## Cómo funciona el índice

Al arrancar, `VaultIndex.build()` escanea todos los `.md` del vault y los carga en `dict[str, NoteModel]`. El ID de cada nota es su path relativo al vault root convertido a slug (`path_to_id`).

Carpetas excluidas del índice: `10 Sensible`, `.obsidian`, `.claude`, `99 Adjuntos`, `.trash`.

Un `watchdog` observer mantiene el índice actualizado en tiempo real sin reiniciar el servidor.

## Sistema de permisos

Toda request requiere `X-API-Key`. La clave determina el scope:

| Scope | Bloquea sensibilidad | Requiere `ia_permiso` | Requiere `ia_indexar` |
|---|---|---|---|
| `personal` | `secreto` | No | No |
| `ai_context` | `privado`, `sensible`, `secreto` | Sí (`allow`) | Sí (`true`) |
| `public` | `interno`, `privado`, `sensible`, `secreto` | No | No |

`/ai/context` tiene reglas adicionales hardcodeadas en `permissions.is_ai_eligible()` que no dependen del scope.

El contenido completo de una nota solo se devuelve con scope `personal`. `ai_context` y `public` reciben solo excerpt.

`GET /vault/stats` y `GET /vault/activity` **no** filtran por `is_visible()` — cualquier scope autenticado ve conteos y títulos de todas las notas del vault, incluidas las bloqueadas por sensibilidad para ese scope. No exponen contenido, pero sí más metadata que el resto de la API. Tenerlo en cuenta si se agregan campos nuevos a esas respuestas.

## Linker estructural (`vault_linker.py`)

Mantiene el grafo de wikilinks del vault. Corre automáticamente vía el watcher (con debounce de 1s tras cada `on_modified`/`on_created`) y también se puede disparar manualmente desde `/vault/links/*`. Excluye siempre `01 Inbox` y `00 Sistema`. Dos operaciones:

- **Wikify de frontmatter** — si `personas`, `proyectos` o `cliente` tienen texto plano en vez de `[[wikilink]]`, busca la nota que mejor matchea (exacto → substring → fuzzy con `rapidfuzz`, umbral 72) y reemplaza el valor por el link real.
- **`## Notas relacionadas`** — escanea el cuerpo buscando menciones literales de títulos de otras notas (mínimo 6 caracteres) y las agrega como lista de wikilinks al final del cuerpo, sin duplicar lo ya presente.

`suggest_semantic_links()` es la única función de este módulo que sale de la API: le pega a `NODE_URL/api/ai/chat/internal` (el servidor `pachimind-web`) para que Gemini sugiera relaciones semánticas que el matching por texto no puede ver. Solo lee — no escribe nada, la escritura la hace `POST /vault/links/apply` sobre las sugerencias aceptadas.

## Modelo de nota (frontmatter)

```yaml
tipo: proyecto          # proyecto | accion | decision | persona | cliente |
                        # organizacion | marca | reunion | registro | recurso | idea | nota
estado: activo          # activo | en_proceso | borrador | archivado | pendiente | para_revisar
area: Laboral           # Personal | Laboral | Familia | Amigos | Apostolado
sensibilidad: normal    # normal | interno | privado | sensible | secreto
ia_permiso: allow       # allow | deny | summary_only
ia_indexar: true
ia_editar: false
revisado: false
origen: ""              # desde_ia | inbox_ia | (vacío = creada manualmente)
```

## Flujo IA → vault

```
POST /ai/context             →  consulta contexto relevante
POST /inbox/draft            →  deposita borrador en 01 Inbox/Desde IA/
POST /notebooklm/import      →  trae transcripción completa de NotebookLM,
                                 la deposita como borrador (tipo: reunion)
GET  /inbox                  →  lista borradores pendientes (contenido completo,
                                 sin el N+1 de listar + pedir cada uno)
POST /notes                  →  convierte borrador en nota definitiva
                                 (source_draft_id archiva el borrador automáticamente)
POST /notes/{id}/promote     →  atajo: promueve un borrador tal cual (o con
                                 overrides puntuales) SIN pasar por Gemini —
                                 usar esto para borradores largos (reuniones)
                                 donde no querés que se reescriba el contenido
DELETE /notes/{id}           →  borrado real de archivo (no confundir con
                                 "descartar" un borrador, que es PATCH estado:archivado)
```

**Importante:** `POST /notes` (vía el front, `/api/ai/review-note` o `/api/ai/process-all` en pachimind-web) le pide a Gemini que devuelva `suggested_content` — es decir, **reescribe el cuerpo**. Para notas cortas está bien (limpia formato), pero para transcripciones largas de reuniones destruye el detalle. `POST /notes/{id}/promote` existe específicamente para evitar eso: toma `draft.content` tal cual, solo cambia frontmatter/carpeta.

## "Sacar el jugo" (extracción de datos duros)

Vive en `pachimind-web` (`POST /api/ai/extract-facts`, ver su CLAUDE.md), no en esta API. Le pide a Gemini que separe una nota en `## Puntos clave` (la idea/concepto) y `## Datos duros` (decisiones, números, fechas, compromisos, nombres — lo que se pierde al recordar una reunión de memoria). El front hace merge idempotente (busca `\n## Puntos clave` y trunca ahí antes de reescribir) y guarda con el `PATCH /notes/{id}` que ya existe acá — no hay endpoint nuevo de este lado.

Se dispara solo al final de un import de reunión (encadenado en el JS del front, `extractFactsForImported()`), o manual con el botón 🧠 en el overlay de cualquier nota. **Si importás reuniones pegándole directo a la API (curl/script, sin pasar por la UI de "Reuniones" en pachimind-web), esa cadena automática no corre** — hay que llamar `/api/ai/extract-facts` + `PATCH` a mano por cada una (pasó el 2026-07-24: 15 de 19 reuniones reimportadas por script quedaron sin "sacar el jugo" hasta que se corrigió a mano).

## Producción

Desplegado en un VPS propio (Ubuntu 24.04, `212.85.22.34`, dominio `pachimind.rail.ar`), **separado de la infra de TotalView/Lightsail**. Detalle completo en `deploy/README.md`; resumen:

- Apache2 (no nginx, pese a lo que puede sugerir código viejo) enruta `/health,/notes,/vault,/search,/ai,/inbox,/projects,/clients,/actions,/people,/decisions,/notebooklm,/attachments,/system` → FastAPI `:8000`, y todo lo demás → Node/Express `:3000` (`pachimind-web`, sirve el front y `/api/ai/*`).
- `deploy/scripts/02-deploy.sh` hace el deploy completo (rsync API + build/rsync frontend + systemd + apache) desde tu Mac. Requiere que `pachimind-web` tenga su `dist/` buildeable (`npm run build`) — si falta `esbuild`/scripts en su `package.json`, este paso rompe en silencio.
- **Gotcha real (2026-07-24):** el script inyecta la API key en el header que agrega Apache; el `.env` del servidor la espera con prefijo `pm-prod-`, pero el sed del script no lo agregaba — verificar que `02-deploy.sh` siga generando `pm-prod-$PROD_API_KEY`, no `$PROD_API_KEY` pelado, o se rompe TODA la auth de FastAPI en prod.
- **Gotcha real:** `/etc/apache2/sites-enabled/pachimind.conf` puede terminar como archivo real en vez de symlink (pasó una vez, probablemente de un setup manual viejo) — `a2ensite` falla silenciosamente en ese caso ("not properly enabled") y Apache sigue sirviendo la config vieja. Verificar con `ls -la /etc/apache2/sites-enabled/pachimind.conf` que sea un symlink a `sites-available/`.
- NotebookLM CLI corre en el servidor con su propia sesión (copiada una vez desde `~/.notebooklm/profiles/default/` de la Mac a `/srv/pachimind/.notebooklm/`, ver `NOTEBOOKLM_HOME`/`NOTEBOOKLM_BIN` en `.env`). Un timer systemd (`notebooklm-keepalive.timer`, cada 15 min) la mantiene viva.
- Digest semanal (`scripts/weekly_digest.py`, domingos 8am vía `weekly-digest.timer`) manda por SMTP las notas con `revisado: false` que no sean borrador/archivado — mismo criterio que el panel "Para revisar" del front.
- **El vault local (Mac, `~/Documents/PachiMind-vault`) y el vault de producción (`/srv/pachimind/vault`) NO están sincronizados entre sí** — divergieron el 2026-07-24. `deploy/scripts/03-vault-upload.sh` hace `rsync --delete` y en su momento no excluía `.git/` ni apuntaba al path correcto del vault local; ya se corrigió, pero antes de correrlo de nuevo hacer `rsync -avzn --delete` (dry-run) para ver qué se borraría — hay carpetas (`99 Adjuntos`, `90 Plantillas`, `08 Decisiones`, `03 Areas`, `02 Diario`) que solo existen en uno de los dos vaults. Preferir importar/crear contenido nuevo directo contra producción (vía la API pública) antes que sincronizar vaults completos.

## Convenciones

- Cada router vive en su propio archivo en `routers/`. No mezclar lógica de negocio en los routers — va en `core/` o `middleware/`.
- El índice es el único source of truth en runtime. Fuera de él, tocan el filesystem: `vault_parser.py`, `vault_watcher.py`, `vault_linker.py`, y los endpoints de escritura (`POST /notes`, `PATCH /notes/{id}`, `POST /inbox/draft`, `POST /vault/links/generate|apply`, `POST /attachments`).
- Los response models siempre se declaran en `models/responses.py` o `models/note.py`, nunca inline en el router.
- Las reglas de privacidad de `/ai/context` (`AI_BLOCKED_SENSIBILIDAD`) son hardcodeadas intencionalmente — no las mover a config.
- Al agregar un nuevo tipo de nota, actualizar `TIPO_FOLDER` en `core/note_writer.py` (la lógica de escritura de notas vive ahí, no en el router, para poder reusarla desde `POST /notes` y `POST /notes/{id}/promote`).
- `vault_parser.parse_note()` traga cualquier excepción y devuelve `None` en vez de propagarla — una nota con YAML roto desaparece del índice sin log de error. Es deliberado (una nota corrupta no debe tumbar el arranque), pero hace que notas rotas sean silenciosas: si una nota "desaparece" de la API, lo primero a revisar es su frontmatter.
- `GET /system/status` asume que `VAULT_PATH` es un repo git independiente del repo de esta API (corre `git log`/`git status` con `GIT_DIR` apuntando al vault). Si el vault no es un repo git, los campos de `git` vuelven vacíos en silencio — no es un error visible para el cliente.


## Memoria y captura de reuniones (octubre 2026)

`core/project_memory.py` reúne fuentes por relaciones explícitas; rutas en `routers/projects.py`, JSON y Markdown para IA. `core/meeting_capture.py` y `routers/meetings.py` capturan fuentes intactas y propuestas revisables. Ver contratos completos en ENDPOINTS.md.

- Nuevas capturas: `06 Reuniones y Registros/Capturas/`, cuerpo original exacto, SHA-256, `titulo` en YAML, `fuente_inmutable:true`. Parser prioriza titulo sin insertar un H1 en la transcripción. Reconoce proyecto singular además de proyectos.
- No modificar fuentes inmutables desde linker, PATCH, DELETE, promociones ni herramientas de extracción que reescriban cuerpo. Correcciones en notas separadas. La validación del hash detecta cambios externos.
- Propuestas: `01 Inbox/Desde IA/`, estado `para_revisar`, excluidas del procesador genérico de borradores y del contexto IA. Aprobar crea una acción pendiente o decisión activa vinculada a proyecto y fuente; descartar solo archiva la propuesta. No cambia la ficha del proyecto.
- UUID de operación, escrituras atómicas, bloqueo entre procesos del escritor de capturas y revisión idempotente. Un lote interrumpido se completa reintentando los mismos UUID. Los editores externos no comparten ese bloqueo.
- El índice normaliza rutas resueltas para admitir vaults con symlinks.
- Pruebas: `VAULT_PATH=/tmp/pachimind-tests-unused .venv/bin/python -m unittest discover -s tests -v` desde el repo (sin un .env con variables desconocidas). Usan un vault temporal y no levantan el watcher sobre datos reales.
- Antes de producción comparar vaults y revisar Apache: la plantilla heredada inyecta una clave en rutas directas a FastAPI. El gateway nuevo protege la sesión web, pero no corrige por sí solo ese bypass del despliegue heredado.

## TODO y conciliación — 2026-10-03

Publicado TODO en /actions/todo (scope personal): Markdown en 09 Acciones/TODO, UUID idempotente y revisión SHA para evitar sobrescrituras concurrentes. Estado, responsable, prioridad y vencimiento se editan en frontmatter, preservando el cuerpo. Pruebas: tests/test_todo.py; suite total 16. Las acciones de reuniones aprobadas aparecen; las propuestas sin aprobar no.

Vault Mac y servidor conciliados: 371 Markdown permitidos idénticos. Se preservaron 15 versiones previas en respaldos y apuntes extra de Giovana en una nota de Inbox para revisar. No hay sincronización automática nueva; no usar rsync --delete. Comparar antes de repetir conciliación.
