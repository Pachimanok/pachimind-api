# PachiMind API — Referencia de Endpoints

Base URL local: `http://localhost:8000`  
Todas las rutas excepto `/health` requieren el header `X-API-Key`.

## Índice

- [GET /health](#get-health)
- [GET /system/status](#get-systemstatus)
- [GET /vault/stats](#get-vaultstats)
- [GET /vault/activity](#get-vaultactivity)
- [GET /notes](#get-notes)
- [POST /notes](#post-notes)
- [POST /notes/{note_id}/promote](#post-notesnote_idpromote)
- [GET /notes/{note_id}](#get-notesnote_id)
- [PATCH /notes/{note_id}](#patch-notesnote_id)
- [DELETE /notes/{note_id}](#delete-notesnote_id)
- [GET /search](#get-search)
- [POST /ai/context](#post-aicontext)
- [POST /inbox/draft](#post-inboxdraft)
- [GET /inbox](#get-inbox)
- [GET /projects/active](#get-projectsactive)
- [GET /actions/pending](#get-actionspending)
- [GET /decisions](#get-decisions)
- [GET /people](#get-people)
- [GET /clients](#get-clients)
- [POST /vault/links/generate](#post-vaultlinksgenerate)
- [GET /vault/links/broken](#get-vaultlinksbroken)
- [GET /vault/links/suggest/{note_id}](#get-vaultlinkssuggestnote_id)
- [POST /vault/links/apply](#post-vaultlinksapply)
- [POST /attachments](#post-attachments)
- [GET /attachments](#get-attachments)
- [GET /notebooklm/notebooks](#get-notebooklmnotebooks)
- [GET /notebooklm/notebooks/{notebook_id}/sources](#get-notebooklmnotebooksnotebook_idsources)
- [POST /notebooklm/import](#post-notebooklmimport)

---

## GET /health

Verifica que la API está corriendo y que el vault está montado y accesible.

**Autenticación:** No requerida.

**Request:** Sin parámetros ni body.

**Response 200:**
```json
{
  "status": "ok",
  "vault_connected": true,
  "indexed_notes": 142
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `status` | string | Siempre `"ok"` si la API responde |
| `vault_connected` | bool | `true` si el path del vault existe en disco |
| `indexed_notes` | int | Cantidad de notas en el índice en memoria |

---

## GET /system/status

Estado operativo completo: uptime del proceso, tamaño del vault en disco, y estado de git **del propio vault** (no del repo de esta API). Pensado para un panel de administración, no para consumo por IA.

**Scopes:** `personal`, `ai_context`, `public`

**Request:** Sin parámetros.

**Response 200:**
```json
{
  "api": {
    "status": "ok",
    "uptime": "2h 14m",
    "uptime_seconds": 8040,
    "started_at": "2026-07-21T08:10:00",
    "indexed_notes": 268
  },
  "vault": {
    "path": "/Users/pablorio/Documents/PachiMind-vault",
    "total_notes": 268,
    "by_type": { "nota": 102, "proyecto": 37 },
    "notes_to_review": 66,
    "vault_size_kb": 3840
  },
  "git": {
    "last_commit_hash": "a1b2c3d4",
    "last_commit_message": "Reunión con Acme",
    "last_commit_date": "2026-07-20 18:02:11 -0300",
    "last_commit_author": "Pablo Rio",
    "total_commits": 214,
    "pending_modified": 1,
    "pending_new": 3,
    "pending_deleted": 0,
    "is_clean": false
  }
}
```

| Campo | Descripción |
|---|---|
| `git.*` | Corre `git log`/`git status` con `GIT_DIR` apuntando a `VAULT_PATH`. Si el vault no es un repo git, **todos** los campos de `git` vuelven vacíos/`0` en silencio — no hay error visible |
| `vault.notes_to_review` | Notas con `revisado: false` y estado distinto de `borrador`/`archivado` (mismo criterio que `/vault/stats`, pero recalculado acá) |

**Nota:** a diferencia del resto de la API, esta respuesta no filtra por `is_visible()` — cualquier scope autenticado ve `by_type` y conteos del vault completo.

---

## GET /vault/stats

Métricas globales del vault: distribución por tipo y área, notas sensibles, notas disponibles para IA, y notas pendientes de revisión.

**Scopes:** `personal`, `ai_context`, `public`

**Request:** Sin parámetros.

**Response 200:**
```json
{
  "total_notes": 142,
  "by_type": {
    "proyecto": 18,
    "accion": 34,
    "nota": 45,
    "persona": 12
  },
  "by_area": {
    "Laboral": 80,
    "Personal": 40,
    "Familia": 22
  },
  "sensitive_notes": 5,
  "ai_indexable_notes": 98,
  "notes_to_review": 12
}
```

| Campo | Descripción |
|---|---|
| `sensitive_notes` | Notas con `sensibilidad` en `privado`, `sensible` o `secreto` |
| `ai_indexable_notes` | Notas con `ia_permiso: allow` e `ia_indexar: true` |
| `notes_to_review` | Notas con `revisado: false` y estado distinto de `borrador`/`archivado` |

---

## GET /vault/activity

Las últimas notas modificadas agrupadas en tres categorías: recién añadidas, procesadas por IA, y pendientes de revisión. Máximo 6 por categoría.

**Scopes:** `personal`, `ai_context`, `public`

**Request:** Sin parámetros.

**Response 200:**
```json
{
  "recently_added": [
    {
      "id": "05-proyectos-laboral-proyecto-acme",
      "title": "Proyecto Acme",
      "tipo": "proyecto",
      "area": "Laboral",
      "last_modified": "2026-05-30T10:22:00"
    }
  ],
  "processed_by_ai": [ ... ],
  "pending_review": [ ... ]
}
```

| Campo | Descripción |
|---|---|
| `recently_added` | Últimas 6 notas por fecha de modificación |
| `processed_by_ai` | Últimas 6 notas con `origen: inbox_ia` |
| `pending_review` | Últimas 6 notas con `revisado: false` y estado activo |

---

## GET /notes

Lista paginada de notas con filtros opcionales por cualquier campo del frontmatter. El scope determina qué notas son visibles. Devuelve resumen + excerpt (200 chars), sin contenido completo.

**Scopes:** `personal`, `ai_context`, `public`

**Query params:**

| Param | Tipo | Descripción |
|---|---|---|
| `area` | string | Match exacto por área |
| `tipo` | string | Match exacto por tipo |
| `estado` | string | Match exacto por estado |
| `sensibilidad` | string | Match exacto por sensibilidad |
| `cliente` | string | Match exacto por cliente |
| `organizacion` | string | Match exacto por organización |
| `persona` | string | Match parcial case-insensitive sobre la lista `personas` |
| `proyecto` | string | Match parcial case-insensitive sobre la lista `proyectos` |
| `marca` | string | Match exacto por marca |
| `tag` | string | Match exacto dentro de la lista `tags` |
| `revisado` | bool | `true` o `false` |
| `prioridad` | string | Match exacto por prioridad |
| `page` | int | Página (default: `1`) |
| `per_page` | int | Resultados por página (default: `20`, máx: `100`) |

**Response 200:**
```json
{
  "total": 45,
  "page": 1,
  "per_page": 20,
  "results": [
    {
      "id": "05-proyectos-laboral-proyecto-acme",
      "title": "Proyecto Acme",
      "path": "05 Proyectos/Laboral/proyecto-acme.md",
      "metadata": {
        "tipo": "proyecto",
        "estado": "activo",
        "area": "Laboral",
        "cliente": "Acme",
        "personas": ["Juan Pérez"],
        "proyectos": [],
        "sensibilidad": "normal",
        "ia_permiso": "allow",
        "ia_indexar": true,
        "ia_editar": false,
        "revisado": true,
        "tags": ["estrategia"],
        "prioridad": "alta",
        "fecha": "2026-04-01",
        "origen": null
      },
      "content": null,
      "excerpt": "Primeros 200 caracteres del contenido..."
    }
  ]
}
```

---

## POST /notes

Crea una nota nueva en el vault. La carpeta destino se determina por el `tipo`. El título se convierte en slug para el nombre del archivo. Si ya existe un archivo con ese nombre, agrega `-v2`, `-v3`, etc.

**Scopes:** `personal` únicamente.

**Body JSON:**

```json
{
  "title": "Reunión con Acme",
  "tipo": "reunion",
  "area": "Laboral",
  "estado": "activo",
  "content": "## Agenda\n\n- Revisar contrato\n- Demo producto",
  "tags": ["cliente", "q2"],
  "cliente": "Acme",
  "personas": ["Juan Pérez", "María García"],
  "source_draft_id": "01-inbox-desde-ia-2026-06-01-reunion-acme"
}
```

| Campo | Requerido | Default | Descripción |
|---|---|---|---|
| `title` | Sí | — | Título de la nota |
| `tipo` | No | `nota` | Determina la carpeta destino (ver tabla abajo) |
| `area` | No | `Laboral` | Área del vault |
| `estado` | No | `activo` | Estado inicial |
| `content` | No | `""` | Cuerpo en markdown |
| `tags` | No | `[]` | Lista de tags |
| `cliente` | No | `null` | Cliente asociado |
| `personas` | No | `[]` | Personas asociadas |
| `source_draft_id` | No | `null` | ID de borrador a archivar automáticamente al crear la nota |

**Carpetas destino por tipo:**

| tipo | carpeta en el vault |
|---|---|
| `cliente` | `04 Entidades/Clientes` |
| `persona` | `04 Entidades/Personas` |
| `organizacion` | `04 Entidades/Organizaciones` |
| `marca` | `04 Entidades/Marcas` |
| `proyecto` | `05 Proyectos/{area}` |
| `reunion` / `registro` | `06 Reuniones y Registros/{area}` |
| `recurso` | `07 Conocimiento/Recursos` |
| `idea` | `07 Conocimiento/Ideas` |
| `decision` | `07 Conocimiento/Decisiones` |
| `accion` | `09 Acciones/{area}` |
| otros | `01 Inbox/Procesado` |

**Response 201:**
```json
{
  "id": "06-reuniones-y-registros-laboral-reunion-con-acme",
  "path": "06 Reuniones y Registros/Laboral/reunion-con-acme.md",
  "filename": "reunion-con-acme.md"
}
```

**Errores:**
- `403` — scope distinto de `personal`

---

## POST /notes/{note_id}/promote

Acepta un borrador del Inbox tal cual (o con overrides puntuales) y lo convierte en nota definitiva, sin tener que reenviar todo el título/contenido. Reusa la misma lógica de `POST /notes` (`core/note_writer.write_note`) tomando como base el borrador indicado, y lo archiva automáticamente (equivalente a pasar `source_draft_id`).

**Scopes:** `personal` únicamente.

**Path param:**

| Param | Descripción |
|---|---|
| `note_id` | ID del borrador a promover |

**Body JSON** (todos los campos opcionales — si no se pasan, se toman del borrador):

```json
{
  "tipo": "reunion",
  "area": "Laboral",
  "estado": "activo",
  "cliente": "Acme"
}
```

**Response 201:** igual formato que `POST /notes`.

**Errores:**
- `403` — scope distinto de `personal`
- `404` — borrador no encontrado

---

## GET /notes/{note_id}

Devuelve una nota completa. El contenido retornado depende del scope y de los permisos de la nota.

**Scopes:** `personal`, `ai_context`, `public`

**Path param:**

| Param | Descripción |
|---|---|
| `note_id` | ID de la nota (obtenido de cualquier listado) |

**Reglas de contenido:**

| Scope | `ia_permiso` de la nota | Devuelve |
|---|---|---|
| `personal` | `allow` o cualquiera | `content` completo + `excerpt` |
| `personal` | `summary_only` | `content: null` + `excerpt` (400 chars) |
| `ai_context` | — | `content: null` + `excerpt` (400 chars) |
| `public` | — | `content: null` + `excerpt` (400 chars) |

**Response 200:**
```json
{
  "id": "05-proyectos-laboral-proyecto-acme",
  "title": "Proyecto Acme",
  "path": "05 Proyectos/Laboral/proyecto-acme.md",
  "metadata": {
    "tipo": "proyecto",
    "estado": "activo",
    "area": "Laboral",
    "cliente": "Acme",
    "personas": ["Juan Pérez"],
    "proyectos": [],
    "sensibilidad": "normal",
    "ia_permiso": "allow",
    "ia_indexar": true,
    "ia_editar": false,
    "revisado": true,
    "tags": ["estrategia"],
    "prioridad": "alta",
    "fecha": "2026-04-01",
    "origen": null
  },
  "content": "# Proyecto Acme\n\nContenido completo...",
  "excerpt": "Primeros 400 chars del contenido...",
  "resolved_links": {
    "Juan Pérez": "04-entidades-personas-juan-perez",
    "Empresa XYZ": null
  }
}
```

| Campo | Descripción |
|---|---|
| `content` | Markdown completo o `null` según scope/permisos |
| `excerpt` | Texto plano truncado a 400 chars |
| `resolved_links` | Mapa de `[[wikilink]]` → ID de nota o `null` si no existe |

**Errores:**
- `404` — nota no encontrada en el índice
- `403` — nota existe pero está bloqueada por scope

---

## PATCH /notes/{note_id}

Edita frontmatter y/o contenido de una nota existente in-place. Solo actualiza los campos presentes en el body (`exclude_none`); el resto queda intacto. No valida los valores contra los enums documentados en el modelo de nota — acepta cualquier string.

**Scopes:** `personal` únicamente.

**Path param:**

| Param | Descripción |
|---|---|
| `note_id` | ID de la nota a editar |

**Body JSON** (todos los campos opcionales):

```json
{
  "estado": "archivado",
  "revisado": true,
  "tags": ["cliente", "cerrado"],
  "content": "# Proyecto Acme\n\nContenido actualizado..."
}
```

| Campo | Descripción |
|---|---|
| `tipo`, `estado`, `area`, `cliente`, `organizacion`, `rol` | Reemplazan el valor del campo en el frontmatter |
| `personas`, `proyectos`, `tags` | Reemplazan la lista completa (no hace merge) |
| `sensibilidad`, `ia_permiso` | Reemplazan el control de acceso de la nota |
| `revisado` | bool |
| `content` | Si se envía, reemplaza el cuerpo markdown completo (no el frontmatter) |

**Response 200:**
```json
{
  "id": "05-proyectos-laboral-proyecto-acme",
  "path": "05 Proyectos/Laboral/proyecto-acme.md"
}
```

**Errores:**
- `403` — scope distinto de `personal`
- `404` — nota no encontrada en el índice

---

## DELETE /notes/{note_id}

Borra el archivo de la nota del vault y la quita del índice (`vault_index.remove_file`). A diferencia de "descartar" un borrador (que solo cambia `estado` a `archivado` vía `PATCH`), esto es un borrado real del archivo — recuperable únicamente vía el historial de git del vault (el sync automático cada 5 min en producción).

**Scopes:** `personal` únicamente.

**Response 200:**
```json
{ "id": "05-proyectos-laboral-proyecto-acme", "deleted": true }
```

**Errores:**
- `403` — scope distinto de `personal`
- `404` — nota no encontrada en el índice

---

## GET /search

Búsqueda fuzzy sobre título y contenido de texto plano de todas las notas visibles para el scope. Usa RapidFuzz `partial_ratio`. Solo retorna resultados con score ≥ 0.5. Ordenado por relevancia descendente.

**Scopes:** `personal`, `ai_context`, `public`

**Query params:**

| Param | Requerido | Descripción |
|---|---|---|
| `q` | Sí (mín 2 chars) | Texto a buscar |
| `area` | No | Filtrar por área antes de buscar |
| `tipo` | No | Filtrar por tipo antes de buscar |
| `estado` | No | Filtrar por estado antes de buscar |
| `sensibilidad` | No | Filtrar por sensibilidad antes de buscar |
| `limit` | No | Máx resultados (default: `20`, máx: `50`) |

**Response 200:**
```json
{
  "query": "reunión acme contrato",
  "total": 3,
  "results": [
    {
      "id": "06-reuniones-y-registros-laboral-reunion-con-acme",
      "title": "Reunión con Acme",
      "type": "reunion",
      "area": "Laboral",
      "excerpt": "Primeros 300 chars del contenido...",
      "path": "06 Reuniones y Registros/Laboral/reunion-con-acme.md",
      "score": 0.95
    }
  ]
}
```

| Campo | Descripción |
|---|---|
| `score` | Float 0-1. Calculado como `partial_ratio / 100`. |

---

## POST /ai/context

Recupera las notas más relevantes para un query de lenguaje natural. Diseñado para alimentar contexto a un LLM. Aplica las reglas de privacidad más estrictas, independientemente del scope: solo notas con `ia_permiso: allow`, `ia_indexar: true`, y `sensibilidad` fuera de `privado/sensible/secreto`. El ranking se hace por relevancia al query usando fuzzy matching (score mínimo 0.45).

**Scopes:** `personal`, `ai_context`

**Body JSON:**

```json
{
  "query": "proyectos activos con cliente Acme en Q2",
  "filters": {
    "area": "Laboral",
    "tipo": "proyecto",
    "cliente": "Acme",
    "estado": "activo"
  },
  "max_results": 10
}
```

| Campo | Requerido | Default | Descripción |
|---|---|---|---|
| `query` | Sí | — | Texto libre para rankear relevancia |
| `filters` | No | `{}` | Mismos campos que `NoteFilters` (ver `GET /notes`) |
| `max_results` | No | `10` | Límite de resultados |

**Response 200:**
```json
{
  "query": "proyectos activos con cliente Acme en Q2",
  "results": [
    {
      "id": "05-proyectos-laboral-proyecto-acme-q2",
      "title": "Proyecto Acme Q2",
      "type": "proyecto",
      "area": "Laboral",
      "excerpt": "Descripción del proyecto con los primeros 400 chars...",
      "path": "05 Proyectos/Laboral/proyecto-acme-q2.md",
      "score": 0.87
    }
  ]
}
```

**Errores:**
- `403` — scope `public`

---

## POST /inbox/draft

Crea un borrador en `01 Inbox/Desde IA/` con nombre `YYYY-MM-DD-{slug}.md`. El borrador queda con `estado: borrador`, `ia_indexar: false`, `revisado: false`, y `origen: desde_ia`. No se escribe en carpeta definitiva.

El flujo esperado es que posteriormente se llame a `POST /notes` con `source_draft_id` apuntando a este borrador, lo cual lo archiva automáticamente.

**Scopes:** `personal`, `ai_context`

**Body JSON:**

```json
{
  "title": "Nota sobre reunión pendiente con Acme",
  "content": "Hay que revisar el contrato antes del viernes.",
  "area": "Laboral",
  "tipo": "nota",
  "cliente": "Acme",
  "proyecto": "Proyecto Q2",
  "tags": ["urgente", "contrato"]
}
```

| Campo | Requerido | Default | Descripción |
|---|---|---|---|
| `title` | Sí | — | Título del borrador |
| `content` | No | `""` | Cuerpo en markdown |
| `area` | No | `Personal` | Área |
| `tipo` | No | `nota` | Tipo de nota |
| `cliente` | No | `null` | Cliente asociado |
| `proyecto` | No | `null` | Proyecto asociado |
| `tags` | No | `[]` | Tags |

**Response 201:**
```json
{
  "id": "01-inbox-desde-ia-2026-06-01-nota-sobre-reunion-pendiente-con-acme",
  "path": "01 Inbox/Desde IA/2026-06-01-nota-sobre-reunion-pendiente-con-acme.md",
  "filename": "2026-06-01-nota-sobre-reunion-pendiente-con-acme.md"
}
```

**Errores:**
- `403` — scope `public`

---

## GET /inbox

Lista los borradores pendientes en `01 Inbox/Desde IA/` (`estado: borrador`) con contenido completo en una sola llamada — evita el patrón N+1 de listar con `GET /notes?estado=borrador` y después pedir cada nota por separado con `GET /notes/{id}`.

**Scopes:** `personal`, `ai_context`

**Response 200:** array de `NoteResponse` (mismo formato que `GET /notes/{note_id}`).

**Errores:**
- `403` — scope `public`

---

## GET /projects/active

Proyectos con estado `activo`, `en_proceso` o `en_revision`. Ordenados por prioridad alfabética (`alta` < `baja` < `media`; sin prioridad al final).

**Scopes:** `personal`, `ai_context`, `public`

**Query params:**

| Param | Descripción |
|---|---|
| `area` | Filtrar por área |
| `cliente` | Filtrar por cliente (match exacto) |
| `prioridad` | Filtrar por prioridad |

**Response 200:** Array de `NoteSummary`:
```json
[
  {
    "id": "05-proyectos-laboral-proyecto-acme",
    "title": "Proyecto Acme",
    "path": "05 Proyectos/Laboral/proyecto-acme.md",
    "tipo": "proyecto",
    "estado": "activo",
    "area": "Laboral",
    "sensibilidad": "normal",
    "prioridad": "alta",
    "revisado": true
  }
]
```

---

## GET /actions/pending

Acciones con estado `pendiente`, `para_revisar`, `en_proceso` o `inbox`. Ordenadas por prioridad (`alta` → `media` → `baja`) y dentro de cada prioridad por `fecha` ascendente.

**Scopes:** `personal`, `ai_context`, `public`

**Query params:**

| Param | Descripción |
|---|---|
| `area` | Filtrar por área |
| `proyecto` | Filtrar por proyecto (match parcial) |
| `prioridad` | Filtrar por prioridad |

**Response 200:** Array de `NoteSummary` (mismo formato que `/projects/active`).

---

## GET /decisions

Decisiones del vault ordenadas por `fecha` descendente (más recientes primero). Las notas sin `fecha` quedan al final.

**Scopes:** `personal`, `ai_context`, `public`

**Query params:**

| Param | Descripción |
|---|---|
| `area` | Filtrar por área |
| `proyecto` | Filtrar por proyecto (match parcial) |
| `fecha_desde` | ISO date (`YYYY-MM-DD`). Excluye decisiones anteriores a esa fecha. |

**Response 200:** Array de `NoteSummary`.

---

## GET /people

Personas del vault (notas con `tipo: persona`).

**Scopes:** `personal`, `ai_context`, `public`

**Query params:**

| Param | Descripción |
|---|---|
| `area` | Filtrar por área |
| `organizacion` | Filtrar por organización (match exacto) |
| `cliente` | Filtrar por cliente (match exacto) |

**Response 200:** Array de `NoteSummary`.

---

## GET /clients

Clientes del vault (notas con `tipo: cliente`) con conteo de proyectos y personas vinculadas.

**Scopes:** `personal`, `ai_context`, `public`

**Request:** Sin parámetros.

**Response 200:**
```json
[
  {
    "id": "04-entidades-clientes-acme",
    "title": "Acme",
    "status": "activo",
    "projects_count": 3,
    "people_count": 5
  }
]
```

| Campo | Descripción |
|---|---|
| `status` | Valor del campo `estado` de la nota del cliente |
| `projects_count` | Notas con `tipo: proyecto` y `cliente` igual al nombre del cliente, visibles para el scope |
| `people_count` | Notas con `tipo: persona` y `cliente` igual al nombre del cliente, visibles para el scope |

---

## POST /vault/links/generate

Recorre todo el vault (excepto `01 Inbox` y `00 Sistema`) wikificando los campos `personas`/`proyectos`/`cliente` que estén en texto plano, y agregando una sección `## Notas relacionadas` con los títulos mencionados en el cuerpo de cada nota. Es la versión masiva de lo que el watcher hace nota por nota tras cada edición.

**Scopes:** `personal` únicamente.

**Query params:**

| Param | Tipo | Default | Descripción |
|---|---|---|---|
| `dry_run` | bool | `true` | Si `false`, escribe los cambios en disco. Con `true` solo reporta qué cambiaría |

**Response 200:**
```json
{
  "dry_run": true,
  "notes_affected": 4,
  "total_changes": 7,
  "results": [
    {
      "note_id": "05-proyectos-laboral-proyecto-acme",
      "title": "Proyecto Acme",
      "path": "05 Proyectos/Laboral/proyecto-acme.md",
      "changes": [
        { "field": "personas", "old": "Juan Pérez", "new": "[[Juan Pérez]]" },
        { "field": "body", "old": "", "new": "- [[Total Trade Group]]" }
      ]
    }
  ]
}
```

**Errores:**
- `403` — scope distinto de `personal`

---

## GET /vault/links/broken

Lista todos los `[[wikilinks]]` del vault que apuntan a notas inexistentes (comparando contra títulos y nombres de archivo de todas las notas indexadas). Ignora links de plantillas conocidas (ej. `[[Nombre de la Nota]]`).

**Scopes:** `personal` únicamente.

**Request:** Sin parámetros.

**Response 200:**
```json
{
  "total": 2,
  "results": [
    {
      "note_id": "05-proyectos-laboral-proyecto-acme",
      "note_title": "Proyecto Acme",
      "note_path": "05 Proyectos/Laboral/proyecto-acme.md",
      "broken_link": "Empresa XYZ"
    }
  ]
}
```

**Errores:**
- `403` — scope distinto de `personal`

---

## GET /vault/links/suggest/{note_id}

Sugiere relaciones semánticas para una nota usando Gemini, vía una llamada HTTP al servidor Node (`NODE_URL/api/ai/chat/internal`, fuera de este repo). Solo lee — no escribe nada en el vault; las sugerencias se confirman con `POST /vault/links/apply`.

**Scopes:** `personal` únicamente.

**Path param:**

| Param | Descripción |
|---|---|
| `note_id` | ID de la nota para la que se buscan relaciones |

**Query params:**

| Param | Tipo | Default | Descripción |
|---|---|---|---|
| `max_suggestions` | int | `5` | Máximo de sugerencias (1–10) |

**Response 200:**
```json
{
  "note_id": "05-proyectos-laboral-proyecto-acme",
  "note_title": "Proyecto Acme",
  "suggestions": [
    {
      "note_id": "04-entidades-clientes-acme",
      "title": "Acme",
      "path": "04 Entidades/Clientes/acme.md",
      "reason": "El proyecto pertenece a este cliente."
    }
  ]
}
```

**Errores:**
- `403` — scope distinto de `personal`
- `404` — nota no encontrada
- Si el servidor Node no responde, devuelve `suggestions: []` en vez de propagar el error

---

## POST /vault/links/apply

Aplica sugerencias de links aceptadas: agrega cada `target_id` a la sección `## Notas relacionadas` de la nota `source_id`. No duplica links ya existentes en la nota (frontmatter o cuerpo).

**Scopes:** `personal` únicamente.

**Body JSON:**

```json
{
  "links": [
    { "source_id": "05-proyectos-laboral-proyecto-acme", "target_id": "04-entidades-clientes-acme" }
  ]
}
```

**Response 200:**
```json
{
  "applied": 1,
  "results": [
    { "source_id": "05-proyectos-laboral-proyecto-acme", "ok": true }
  ]
}
```

| Resultado por item | Cuándo ocurre |
|---|---|
| `{"ok": true}` | Link agregado |
| `{"ok": true, "note": "ya existía el link"}` | El link ya estaba presente, no se duplicó |
| `{"ok": false, "error": "nota no encontrada"}` | `source_id` o `target_id` no existen en el índice |

**Errores:**
- `403` — scope distinto de `personal`

---

## POST /attachments

Sube un archivo binario a `99 Adjuntos/` del vault (carpeta excluida del índice de notas). Devuelve la sintaxis Obsidian lista para pegar en una nota.

**Scopes:** `personal` únicamente.

**Request:** `multipart/form-data` con campo `file`.

**Límites:**

| Regla | Valor |
|---|---|
| Tamaño máximo | 20 MB |
| Extensiones permitidas | `.pdf .png .jpg .jpeg .gif .webp .svg .mp3 .mp4 .m4a .wav .doc .docx .xls .xlsx .ppt .pptx .txt .md .csv .json .zip` |

**Response 200:**
```json
{
  "filename": "contrato-acme.pdf",
  "path": "99 Adjuntos/contrato-acme.pdf",
  "size_kb": 340,
  "embed": "[[contrato-acme.pdf]]",
  "is_image": false
}
```

| Campo | Descripción |
|---|---|
| `embed` | `![[archivo]]` para imágenes (embed visual en Obsidian), `[[archivo]]` para el resto |

**Errores:**
- `403` — scope distinto de `personal`
- `400` — extensión no permitida
- `413` — archivo mayor a 20 MB

---

## GET /attachments

Lista los archivos existentes en `99 Adjuntos/`, ordenados por fecha de modificación descendente.

**Scopes:** `personal`, `ai_context`, `public`

**Request:** Sin parámetros.

**Response 200:**
```json
{
  "total": 1,
  "results": [
    {
      "filename": "contrato-acme.pdf",
      "path": "99 Adjuntos/contrato-acme.pdf",
      "size_kb": 340,
      "embed": "[[contrato-acme.pdf]]"
    }
  ]
}
```

---

## GET /notebooklm/notebooks

Lista los notebooks de NotebookLM disponibles (vía CLI `notebooklm`, requiere sesión autenticada en el host que corre la API).

**Scopes:** `personal`, `ai_context`

**Response 200:**
```json
[
  { "id": "6d8ba0e7-...", "title": "TotalView - Socios Concreto y Reuniones" }
]
```

**Errores:** `502` si la CLI de `notebooklm` no está disponible o falla.

---

## GET /notebooklm/notebooks/{notebook_id}/sources

Lista las fuentes (audios, PDFs, imágenes, etc.) de un notebook.

**Scopes:** `personal`, `ai_context`

**Response 200:**
```json
[
  { "id": "7db5b635-...", "title": "Audio Introduccion Propuesta TotalView", "type": "media", "status": "ready" }
]
```

---

## POST /notebooklm/import

Trae la transcripción completa de cada fuente seleccionada y la deposita como borrador (`tipo: reunion`, `estado: borrador`) en `01 Inbox/Desde IA/`, vía la misma lógica de `POST /inbox/draft`.

**Scopes:** `personal`, `ai_context`

**Request:**
```json
{
  "notebook_id": "6d8ba0e7-...",
  "area": "Laboral",
  "sources": [
    { "source_id": "7db5b635-...", "title": "Reunion con Genaro", "tags": ["genaro"], "cliente": null, "proyecto": null }
  ]
}
```

**Response 201:**
```json
{
  "results": [
    { "source_id": "7db5b635-...", "title": "Reunion con Genaro", "ok": true, "path": "01 Inbox/Desde IA/2026-07-24-reunion-con-genaro.md", "error": null }
  ]
}
```

Cada fuente se procesa independientemente — una fuente que falla (transcripción vacía, ID inválido) no interrumpe el resto del lote.

---

## Modelo compartido: NoteSummary

Usado en `/projects/active`, `/actions/pending`, `/decisions`, `/people`:

```json
{
  "id": "string",
  "title": "string",
  "path": "string",
  "tipo": "string | null",
  "estado": "string | null",
  "area": "string | null",
  "sensibilidad": "string",
  "prioridad": "string | null",
  "revisado": "bool"
}
```

## Errores comunes

| Código | Causa |
|---|---|
| `401` | Header `X-API-Key` ausente |
| `403` | API key inválida, scope insuficiente, o nota bloqueada por permisos |
| `404` | Nota no encontrada en el índice |
| `422` | Body o query params con formato incorrecto |

## GET /projects/memory

Catálogo de fichas de proyecto disponibles para Memoria, ordenado por título. Scopes: `personal`, `ai_context`; `public` recibe 403. Incluye proyectos cerrados como historia; excluye borradores, archivados, para_revisar, Inbox y Sistema. La visibilidad se filtra antes de devolver metadatos. Respuesta: `NoteSummary[]`.

## GET /projects/{project_id}/memory

Memoria de lectura con fuentes originales conectadas por `proyectos` o wikilinks explícitos en ambas direcciones (un salto). Resuelve título, nombre de archivo y ruta sin `.md`; referencias ambiguas no se asignan. No agrupa por mera coincidencia de cliente o similitud textual.

Scopes: `personal`, `ai_context`; `public` recibe 403. Un proyecto inexistente o no accesible devuelve 404. Parámetro `for_ai=true` aplica además las reglas estrictas de IA aun con scope personal; scope ai_context siempre las aplica. Las notas de ai_context solo incluyen excerpt según la política existente.

Respuesta: `{project_id, title, for_ai, sources, warnings}`. Cada fuente incluye `id`, `title`, `path`, `tipo`, `estado`, `fecha` (ISO válida o null), `fecha_registrada` (valor original), `revisado`, `relation`, `content`, `excerpt`, `truncated`. Ficha principal primero, restantes por fecha descendente; sin fecha válida al final. No se infieren fechas del nombre ni del mtime. Los estados registrados no prueban vigencia ni reemplazo de decisiones. No realiza escrituras ni llamadas a modelos.

## GET /projects/{project_id}/memory.md

Exportación Markdown portable de la misma memoria, siempre con reglas de IA. Scopes: `personal`, `ai_context`. Personal recibe el cuerpo completo de fuentes elegibles; ai_context conserva el límite de excerpts. Cada fuente incluye ruta Obsidian, fecha registrada, estado y relación. Las advertencias explican cobertura y límites. `Cache-Control: no-store`. No exporta borradores ni notas con `ia_permiso != allow`, `ia_indexar: false` o sensibilidad bloqueada para IA.

## POST /projects/{project_id}/meetings

Captura de fuente original, scope `personal`. Body: `request_id` UUID, `title` (1–200 caracteres), `fecha` ISO de la reunión, `participantes` lista de nombres, `source` descripción o enlace de origen, `content` original (hasta 500.000 caracteres), `allow_ai` booleano (default true). La elegibilidad IA no supera la del proyecto. Respuesta 201 `{id,path,created}`; repetir el UUID y payload no duplica, cambiarlo devuelve 409.

Escribe en `06 Reuniones y Registros/Capturas/`, con nombre legible y UUID; registra proyecto, procedencia, fecha de captura, SHA-256 y `fuente_inmutable: true`. Preserva exactamente el cuerpo suministrado, incluidos espacios y saltos de línea; el parser de consulta puede normalizar su presentación. Enlaces automáticos, PATCH, DELETE y promoción genérica bloquean fuentes inmutables. Una edición externa del original se detecta al revisarlo (409), sin sobrescribirla.

## GET /projects/{project_id}/meetings/{meeting_id}

Lectura exacta de una captura de este proyecto, solo scope `personal`. Devuelve `{id,path,title,fecha,source,participantes,content,allow_ai}`. Con `for_ai=true`, verifica reglas estrictas de IA antes de servir contenido. 404 si proyecto/fuente no disponible o no coinciden; 409 si el hash original no coincide. Este endpoint no incluye reuniones antiguas sin metadatos de captura.

## GET /projects/{project_id}/meetings/{meeting_id}/proposals

Scope `personal`. Lista las propuestas pendientes y resueltas de una captura. Campos: `id,path,title,tipo,estado,review,detalle,evidencia,responsable,vencimiento,approved_path`. Permite retomar la revisión tras recargar. `review`: null, `approve` o `discard`.

## POST /projects/{project_id}/meetings/{meeting_id}/proposals

Scope `personal`. Body `{items:[...]}`, entre 1 y 40. Cada item: `request_id` UUID, `tipo` accion/decision, `title`, `detalle`, `evidencia` (cita exacta que debe aparecer en la fuente), `responsable` opcional, `vencimiento` ISO opcional. No se infieren campos faltantes. Validación de todo el lote antes de escribir; un error de disco puede dejar un lote parcial, y el reintento con los mismos UUID lo completa sin duplicar.

Escribe en `01 Inbox/Desde IA/`, estado `para_revisar`, `ia_indexar:false`, sin alterar el original. Este estado evita que el procesador genérico de borradores reescriba las propuestas. Devuelve lista de propuestas; 422 para evidencia inexistente o payload inválido, 409 para reutilización de UUID con otros datos. La evidencia textual es necesaria pero no prueba que una interpretación sea correcta: requiere revisión humana.

## POST /projects/{project_id}/meetings/{meeting_id}/proposals/{proposal_id}/review

Scope `personal`. Body `{action:"approve"}` o `{action:"discard"}`. Aprobar crea una nota vinculada al proyecto y fuente: acción `pendiente` en `09 Acciones/Capturas/` o decisión `activo` en `07 Conocimiento/Decisiones/`, `revisado:true`. La propuesta queda archivada con el resultado y fecha de revisión; descartar solo archiva la propuesta. Repetir la misma revisión es idempotente; intentar otra tras resolverla devuelve 409. No actualiza automáticamente la ficha del proyecto ni cierra acciones previas.

### Integración del front

El front usa `/api/memory/projects/...`, gateway autenticado de Node hacia `/projects/...`, evitando la ruta Apache heredada para estas operaciones. `/api/ai/meeting-proposals` consulta la fuente guardada con `for_ai=true`, solicita sugerencias JSON a Gemini y descarta items sin cita literal válida. No escribe notas ni aprueba propuestas. Solo se invoca por acción explícita del usuario. La captura y revisión manual funcionan sin Gemini. El servidor Node acepta `PORT` para pruebas aisladas.

## TODO de actividades (2026-10-03)

`GET /actions/todo`, `POST /actions/todo`, `PATCH /actions/todo/{note_id}` requieren scope personal. Creación con UUID request_id, title, detalle, area, project_id opcional, responsable, vencimiento ISO y prioridad alta/media/baja. El PATCH requiere revision (SHA-256 devuelto por GET) y admite estado pendiente/en_proceso/completado, responsable, vencimiento y prioridad. Revision obsoleta devuelve 409. Las notas se guardan en `09 Acciones/TODO`; las acciones aprobadas de reuniones también aparecen. Propuestas del Inbox, archivos y fuentes inmutables no se editan desde TODO. No se cambia el cuerpo de la nota al actualizar sus campos.

# Personas y conocimiento — primera versión, octubre 2026

Estas rutas son aditivas y reutilizan IDs/rutas del vault. `X-PachiMind-Actor: assistant`
activa las restricciones IA, incluso si el servicio posee una clave personal. Las
lecturas con clave `ai_context` siempre usan ese modo. Todas las escrituras requieren
scope API `personal`; MCP exige adicionalmente OAuth `pachimind:write` y fija el actor.
No se alteran las conexiones OAuth ni la selección de cuenta.

## GET /people/directory

Buscador paginado por `q` (nombre, alias, organización), `ambito` (Trabajo, Apostólico,
Colegios, Formación), `view` (incomplete, pending, unconnected, no_outgoing, duplicates),
`page` >= 1 y `per_page` 1..100. Devuelve `{total,page,per_page,results}`. Cada resultado
incluye campos, permisos, revisión, fuentes, conexiones entrantes/salientes, datos
pendientes, propuestas, posibles duplicados y advertencias de clasificación.
`unconnected` cuenta ambas direcciones; `no_outgoing` no implica ausencia de conexiones.
Se consideran sólo nodos y evidencia visibles para el scope actual.

## GET /people/{person_id}/profile

Ficha existente con `revision` SHA-256 compuesto por archivo y capa de relaciones.
`fields` contiene datos almacenados; `metadata.revisado` distingue su revisión.
`field_sources` incluye IDs, ruta, fecha registrada y cita literal cuando existen.
`original_content` respeta las reglas de contenido/excerpt de la API. Los cuerpos
originales se conservan. Las propuestas no sustituyen los campos antes de aplicar.

## POST /people/drafts

Creación mínima: `{"request_id":"UUID","nombre":"Nombre"}`. Otros datos quedan
pendientes. Usa `04 Entidades/Personas/`; no crea directorios paralelos. Coincidencia
exacta devuelve el ID existente, `created:false` y `needs_identity_review:true`, sin
modificarlo ni afirmar identidad. Similitudes requieren revisión: `distinct_from`
puede enumerar IDs que el usuario comprobó que son personas distintas. Nunca fusiona.
Un UUID repetido con otro contenido devuelve 409. Para reintentos conservar el UUID.

## PATCH /people/{person_id}/profile

Edición manual: `request_id`, `revision`, `fields` y opcional `confirm_review`.
Campos permitidos: nombre, aliases, organizacion, funcion, relacion_conmigo, ambitos,
contactos_profesionales (email_profesional, telefono_profesional, perfil_profesional),
notas_manuales y tipo (persona, idea, recurso, nota). No cambia permisos IA.
Confirmar revisión es una acción humana. Actor assistant no puede editar directamente.
Un conflicto devuelve 409; no reintentar cambiando revision sin revisar lo ocurrido.
El archivo conserva ruta/ID y cuerpo. La clasificación no mueve archivos.

## POST /people/{person_id}/proposals

`request_id`, `revision`, `fields`, `evidence` y opcional `questions`.
Cada evidencia usa `{field,source_id,quote}`; la cita debe existir literalmente en
una fuente disponible. Cada campo necesita evidencia propia. El asistente debe
proponer valores personales explícitos, no deducir cargos o parentescos. Una pregunta
puede quedar pendiente sin campos; no se aplica como hecho. Los cambios se guardan
separados en `.pachimind/changes`, no dentro de la ficha ni del procesador de Inbox.

## GET /people/changes

Propuestas pendientes paginadas; filtros `note_id`, `page`, `per_page`.
Incluye cambios de ficha y relaciones que afectan al ID, entrantes o salientes.
Devuelve destinos y origen reales para revisión. Excluye evidencia o notas reservadas.

## POST /people/changes/{change_id}/review

`request_id`, `revision`, `action` (apply/reject), `authorized_fields` y opcional
`expected_kind` (person/links). Para aplicar deben autorizarse todos y sólo los campos
mostrados; para relaciones usar `["relations"]`. Revalida origen, destinos, tipo,
permisos, revisión base y hash de cada fuente. Ante conflicto exige propuesta nueva.
Actor assistant no aplica sobre revisado=true, ia_editar=false o fuente_inmutable.
Una persona inmutable conserva su corrección separada; no se sobrescribe ni manualmente.
La revisión manual puede confirmar fichas mutables. `reject` conserva el original.
Devuelve ID, revisión, estado y `history_id` cuando hubo cambios.

## POST /vault/relations/proposals

`request_id`, `source_id`, `revision`, `links` y opcional `reserved_segments`.
Cada enlace usa `{target_id,target_revision,relation,action,evidence?}`. Tipos:
participó en, mencionado en, trabaja con, vinculado al proyecto, fuente,
relacionado con, referencia. Action: add/remove. Valida tipos de origen/destino.
La IA necesita evidencia literal para agregar; participación sólo se acepta desde
participantes explícitamente identificados en una captura, nunca por una mención.
Las anotaciones de fuentes inmutables se aplican manualmente en una capa separada.
Quitar una referencia heredada la suprime en esa capa, sin reescribir el original.

## GET /vault/relations

Grafo filtrado por permisos: `{nodes,relations}`. Integra wikilinks, propiedades
explícitas y relaciones revisadas por ID. No convierte menciones en enlaces, no usa
fuzzy matching para resolver destinos y no expone contenido/IDs de notas reservadas.
Los enlaces ambiguos se señalan para revisión. La memoria y su exportación integran
esta capa, sin incluir borradores o fuentes no habilitadas para IA.

## POST /notes/knowledge-drafts

`request_id`, `title`, `kind` (contexto/resumen/lectura), `content`, `source_ids` y
opcional `reserved_segments`. Crea un borrador derivado en `07 Conocimiento/`, no
una reunión ni una tarea. No recibe ni inventa `fecha`; guarda sólo creación técnica.
Conserva las fuentes, hereda su sensibilidad más restrictiva y queda sin revisión,
con ia_indexar=false. Segmentos reservados: `{source_reference,start_seconds,end_seconds}`;
sólo localizador opaco o HTTPS sin credenciales/query, timestamps y etiqueta neutral.
No importa contenido del segmento ni modifica permisos de las fuentes.

## POST /people/history/{history_id}/undo

Sólo manual: `request_id`, `revision`. Revierte únicamente los archivos de esa
operación si sus hashes posteriores coinciden; no pisa modificaciones nuevas.
Conserva historial y originales. Puede deshacer borradores creados por esta portada
si no cambiaron; nunca borra una fuente referenciada. Relaciones JSON se revierten
sin tocar el texto original. No se expone como herramienta MCP de borrado.

## GET /actions/todo

Endpoint existente: actividades personales, incluyendo acciones aprobadas de reuniones.
Propuestas sin revisar quedan fuera. Devuelve revisión SHA para edición concurrente.

## POST /actions/todo

Endpoint existente: request_id UUID, title, detalle, area, project_id opcional,
responsable, vencimiento y prioridad. Creación idempotente, scope personal.

## PATCH /actions/todo/{note_id}

Endpoint existente: revision y campos editables de la actividad. Ante cambio devuelve 409.

Compatibilidad: `GET /people` sigue devolviendo su lista anterior. Crear personas vía
`POST /notes` ahora requiere usar `/people/drafts`. `PATCH /notes/{note_id}` requiere
revision para personas (428 si falta), para no eludir el control de concurrencia.
`GET /notes/{note_id}` incorpora revision. Stats/activity, enlaces y contexto respetan
las exclusiones. El autolinker no edita revisados, fuentes inmutables, ia_editar=false
ni las fichas/borradores administrados por esta portada. No se migra el vault al iniciar.
