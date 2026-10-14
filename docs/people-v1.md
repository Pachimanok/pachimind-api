# Personas y conocimiento: primera versión para revisión

Implementación en `feat/people-knowledge`, coordinada entre pachimind-web,
pachimind-api y pachimind-mcp. Sin despliegue a producción, migración del vault real,
importación de personas reales ni reorganización masiva.

## Diagnóstico comprobado

| Componente | Arquitectura inspeccionada | Cambio necesario |
|---|---|---|
| Web | SPA en index.html, estado S, HTML renderizado por funciones; Express/TypeScript; gateway con sesión existente | Portada Personas y edición/revisión explícita, sin framework nuevo ni cambio de cuenta |
| API | FastAPI, Markdown YAML, índice en memoria, watcher; IDs derivados de rutas | Modelos de campos, revisiones y capa separada de propuestas/relaciones |
| MCP | FastMCP 1.30, OAuth con PKCE, scope read global y write por herramienta | Herramientas nuevas sin reutilizar captura de reuniones/TODO |

La carpeta existente es `04 Entidades/Personas/`, definida por note_writer. El
endpoint `/people` sólo devolvía resúmenes; el parser descartaba rol y otros campos
que el editor ya escribía. Alias histórico puede ser string o lista. Proyectos
aceptan `proyecto` singular y `proyectos`. Cliente y organización son propiedades
separadas: la nueva ficha no convierte un cliente en empleador u organización.

Wikilinks y propiedades son referencias explícitas; una mención en prosa no es
una conexión ni prueba participación. El resolver anterior usaba títulos y podía
seleccionar el último duplicado. El linker automático usaba fuzzy y no respetaba
ia_editar/revisado. Se conserva fuzzy sólo para señalar posibles duplicados; las
relaciones nuevas requieren IDs verificados. También se filtraron stats/activity,
destinos resueltos y contexto semántico para evitar divulgar notas reservadas.

No se leyó el vault real ni se verificó el contenido privado de las cinco fichas
mencionadas por el usuario. La reutilización de IDs, la portada y las reglas se
validaron con fixtures marcadas demo. Bienvenido.md no se modifica: la entrada
Personas está en la navegación; cualquier cambio del índice real requiere revisión
con el archivo real disponible. No se afirma que una idea/manual real fue corregida.

## Modelo y persistencia

Cada persona sigue siendo UN Markdown y UN ID en la carpeta existente. Nombre,
aliases, organización, función, relación conmigo, ámbitos múltiples, contactos
profesionales y notas manuales son opcionales salvo el nombre al crear. `rol` y
`alias` históricos se leen sin reescribir archivos. `area=Laboral/Apostolado` ofrece
el filtro equivalente Trabajo/Apostólico si no existe ambitos; no asigna Colegios
ni Formación por menciones. Guardar ambitos no crea copias ni modifica area.
Cambiar nombre conserva ID/ruta/cuerpo y referencias a títulos anteriores, sin
convertir ese historial técnico en nuevas identidades o fusionar fichas.

La ficha mínima nace `para_revisar`. Las nuevas fichas manuales mantienen
ia_editar=false; los borradores nuevos del asistente permiten edición mientras
no estén revisados, siempre con OAuth write y aplicación explícita. No se amplían
permisos de fichas existentes. Confirmar revisión sólo se hace manualmente.

| Almacenamiento | Propósito |
|---|---|
| Markdown existente | Campos almacenados, permisos reales, datos_fuente, revisión/origen; cuerpo preservado |
| .pachimind/changes/*.json | Propuestas y preguntas pendientes, evidencia literal y revisión base |
| .pachimind/relations/*.json | Relaciones tipadas por IDs, altas/bajas y referencias neutrales |
| .pachimind/history/*.json | Historial y reversión; guarda encabezados/huellas, no duplica cuerpos originales |
| .pachimind/requests/*.json | Idempotencia por UUID + operación + payload |

JSON se escribe atómicamente, con archivos privados 0600 y directorios de operación
0700; no ingresa al índice Markdown, Inbox ni procesadores de Gemini. Reutiliza el
bloqueo entre procesos de meeting_capture. La revisión combina bytes del Markdown
y la capa de relaciones; fuentes de evidencia tienen su SHA separado. Los editores
externos no comparten el bloqueo: se detectan cambios anteriores a guardar por SHA,
pero no se promete CAS distribuido frente a escritores externos que ignoren locks.

Relaciones heredadas se muestran como referencia, sin convertirlas en empleo o
asistencia. Las nuevas distinguen participado/mencionado/trabaja con/proyecto/fuente/
relacionado/referencia, validando tipos. Una baja heredada queda en la capa separada:
no borra el wikilink del original. Se cuentan entrantes y salientes visibles para
el scope. Por eso Sin enlaces salientes y Sin conexiones son vistas diferentes.

## Protecciones

- OAuth, SQLite y selección de cuenta siguen intactos. No hay cambios en auth.py.
- Read nunca exige write. Write devuelve el desafío OAuth existente antes del backend.
- El MCP fija X-PachiMind-Actor: assistant y usa la clave ai_context para lecturas.
- Revisado, ia_editar, fuente_inmutable, ia_permiso, ia_indexar y sensibilidad se
  validan nuevamente al aplicar; no hay argumentos para modificar esos permisos.
- Propuestas de fichas protegidas quedan separadas para revisión humana. Las fuentes
  inmutables no se sobrescriben, incluso manualmente; sí admiten anotaciones de
  relaciones en otra capa con revisión manual.
- No se copian citas reservadas a fichas/borradores: se rechazan; sólo referencias
  neutrales con localizador/timestamps, sin contenido, query ni credenciales.
- Un campo depende de la visibilidad de sus fuentes. Si una fuente cambia privacidad,
  no se divulga el dato dependiente por búsqueda, grafo, contexto ni exportaciones.
- Oculto es una etiqueta, no ACL. Carpetas reservadas y permisos reales excluyen datos.
- Valores personales propuestos por IA deben aparecer explícitos en las citas. Las
  preguntas quedan preguntas; no se aplican como hechos. Una mención no prueba asistencia.
- Conflictos 409 exigen releer/revisar; no se fuerza una revisión nueva automáticamente.
- Reversión manual valida huellas posteriores, conserva historial y fuentes, y no
  sobrescribe modificaciones nuevas. No se agrega una herramienta MCP de borrado.

## Superficies y compatibilidad

Portada `?view=personas`: búsqueda, ámbitos, vistas de revisión/duplicados/conexiones,
ficha mínima y edición con vista previa. Ficha: datos, fuentes/fechas cuando existen,
relaciones con destino real, propuestas/preguntas e historial/reversión. Se pueden
proponer bajas entrantes y salientes desde la ficha. Funciona sin Gemini.

Contratos REST completos: ENDPOINTS.md. Contratos y ejemplos MCP: el documento
`docs/people-tools.md` de pachimind-mcp. GET /people mantiene su lista anterior.
Para no eludir las protecciones, POST /notes no crea personas y PATCH /notes exige
revision en personas (428 si falta). El editor viejo de Entidades redirige a Personas.
Fuentes, funciones, fechas y campos pendientes no se infieren de nombres o menciones.
La corrección de tipo no mueve archivos ni cambia IDs; ubicación pendiente se señala.

El frontend ya versionaba .env y node_modules de macOS. No se leyó ni añadió ningún
valor de .env a esta entrega. Preview usa variables ficticias. En cloud se instaló
esbuild 0.24.2 para Linux fuera del checkout; en una instalación limpia ejecutar
npm ci con el lockfile. El build ahora usa la API Node de esbuild y copia people.js/css.

## Validación reproducible

API, desde pachimind-api, en su virtualenv independiente (Pydantic 2.9.2):

```bash
VAULT_PATH=/tmp/pachimind-tests-unused PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
VAULT_PATH=/tmp/pachimind-tests-unused python scripts/check_endpoints_doc.py
```

Preview sintético (crea siempre un vault temporal NUEVO; no acepta un vault real):

```bash
PYTHONDONTWRITEBYTECODE=1 PREVIEW_API_PORT=18000 python scripts/people_preview.py
```

Web desde pachimind-web, con Node >=20, npm ci y Chromium/Playwright:

```bash
npm run build
AUTH_SECRET=preview-synthetic FRONTEND_PASSWORD=preview-password GEMINI_API_KEY=preview-not-real PM_API_KEY=test-personal EXT_API_KEY=preview-not-real VITE_PACHIMIND_URL=http://127.0.0.1:18000 HOST=127.0.0.1 PORT=18300 node dist/server.cjs
```

En otra terminal: `PEOPLE_SCREENSHOT_DIR=/tmp/pachimind-capturas npm run test:people`.
El runner sólo admite loopback y exige el marcador synthetic del API de demo. Parte
de una demo fresca; crea una persona y prueba completar/revisar/vincular/conflictos.
No puede apuntarse a producción. Browser puede usar CHROMIUM_PATH o el Chromium de
Playwright. Capturas: portada, ficha y móvil, todas de fixtures demo.

Para integración MCP usar otra demo fresca en puerto 18002, sin compartir el vault
del navegador. Desde pachimind-mcp, con su virtualenv MCP 1.30/Pydantic >=2.11:

```bash
PACHIMIND_TEST_API_URL=http://127.0.0.1:18002 NO_PROXY=localhost,127.0.0.1 PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

Sin PACHIMIND_TEST_API_URL se ejecutan unidades/regresión; las cuatro integraciones
se reportan skipped, no passed. No instalar API y MCP en el mismo virtualenv: sus
pins de Pydantic son distintos. Registrar resultado real, no sólo puerto/PID.

## Resultados de esta entrega

- API: 45 pruebas aprobadas (29 de Personas y 16 regresiones existentes).
- MCP: 27 pruebas aprobadas, incluidas las cuatro integraciones contra API sintética;
  ninguna integración omitida en la ejecución final.
- Chromium: recorrido completo aprobado, incluyendo conflicto concurrente, sesión,
  vista previa, aprobación explícita, escape HTML y ausencia de overflow móvil.
- Build web y comprobación de ENDPOINTS.md aprobados.
- Capturas sintéticas: personas-portada.png, persona-ficha.png, personas-mobile.png.

## Despliegue propuesto (NO ejecutado)

1. Revisar los tres commits de la misma rama y probarlos juntos con fixtures.
   Identificar el código actualmente instalado: la versión real de API/web no se
   deduce de main. Comparar hashes y conservar la revisión/artefactos previos.
2. Confirmar ubicaciones con systemctl show. MCP conocido: /srv/pachimind/mcp, sin
   .git; instalar archivos del commit verificados por SHA. API/web según las unidades
   versionadas: /srv/pachimind/api y /srv/pachimind/node; verificar en el servidor.
3. Respaldar código y artefactos. Antes de habilitar escrituras nuevas, tomar un
   respaldo privado y consistente del vault, incluyendo .pachimind y metadatos.
   Mantenerlo en el servidor; nunca subirlo al repo o a logs. No copiar credenciales.
4. Instalar primero API y verificar rutas/scope; luego web con sus assets nuevos y
   dependencias runtime; después MCP incluyendo people_types.py. Mantener .env y
   state/oauth.sqlite3. No resetear OAuth ni pedir una cuenta diferente.
5. Apache debe usar el gateway autenticado existente y NO inyectar claves en rutas
   públicas. Confirmar la configuración real antes de abrir las nuevas rutas. Todas
   usan prefixes existentes /people, /notes, /vault; no requiere una ruta pública nueva.
6. Verificar salud, lectura con scope read, desafío write, rechazo de clave AI/public
   en escritura, UI Personas y una operación sintética autorizada. Sólo después de
   aprobación específica habilitar pruebas/escrituras sobre fichas reales.

No hay migración automática ni conversión masiva: lectura de YAML legacy es aditiva,
JSON se crea sólo por operaciones autorizadas. No modificar Bienvenido.md ni usar
rsync --delete, ni importar las fixtures demo al vault real.

## Reversión

Restaurar los tres artefactos de código previos coordinadamente (MCP/web/API), con
sus dependencias anteriores y reinicio controlado; verificar salud y lectura. No
restaurar ni borrar OAuth SQLite: esta entrega no lo modifica. Mantener los datos y
el respaldo privado. Si hubo operaciones reales, revertirlas por historial con
revisión, de más nueva a más vieja, antes de retirar la API nueva cuando corresponda.
El código anterior no interpreta la capa .pachimind; retirarla u ocultarla perdería
vínculos, propuestas y trazabilidad. Conservarla para restauración posterior. No
restaurar todo el vault encima de ediciones nuevas sin conciliación y aprobación.
