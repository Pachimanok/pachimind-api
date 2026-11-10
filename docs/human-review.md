# Humano: decisiones pendientes

La portada `/?view=humano` reúne vínculos propuestos, cambios de fichas y preguntas,
acciones/decisiones de reuniones, y notas sin revisar o en borrador. Tiene filtros,
búsqueda, contador y paginación. `/?view=vinculos` conserva el acceso a vínculos.
Abrir una propuesta o comprobar revisiones es sólo lectura: no aprueba nada.

Cada detalle comprueba revisiones de fuentes, destinos y evidencias en el servidor.
La autorización se habilita sólo tras una comprobación válida. La decisión vuelve
a validar el estado; ante un conflicto hay que releer. Los errores aparecen en el
detalle con Reintentar comprobación; tienen tiempo máximo, sin espera indefinida.
Aprobar exige marcar los campos/vínculos mostrados; Declinar conserva originales.
Las preguntas sin campos se responden como aclaraciones separadas, no como hechos.

La sesión humana autenticada pasa por `/api/human` en Node. Este gateway no acepta
una API key como sustituto de sesión, sólo permite estas rutas y envía el actor
manual usando la clave interna. En API se exige scope personal y actor manual;
las claves IA y el actor assistant reciben 403. MCP conserva sus restricciones.
Las rutas deshabilitan caché y no se amplían permisos de lectura o escritura.

## Notas originales y permisos

Revisar una nota guarda su decisión en `.pachimind/human_notes`, con historial,
SHA de la fuente e identificador idempotente. No reescribe el Markdown ni cambia
`ia_permiso`, `ia_indexar`, `ia_editar` o `fuente_inmutable`. Aprobar marca revisado
y activa borradores; declinar archiva la vista sin borrar la fuente. Si el archivo
cambia, la revisión pierde validez y vuelve a aparecer como pendiente cuando sus
metadatos originales lo indican. Una nota con sólo resumen disponible no permite
aprobar su contenido completo desde esta vista. La cola respeta fuentes ocultas.

Los vínculos se aplican en la capa de relaciones existente; las fichas usan el
historial y validaciones existentes. Las acciones aprobadas crean actividades;
las decisiones aprobadas se registran con evidencia. No se infieren fechas,
responsables ni identidades. Las aclaraciones quedan en `.pachimind/human_answers`
y no se copian al cuerpo ni se divulgan por el catálogo MCP de cambios pendientes.

Cada decisión usa un request_id estable. Ante respuesta perdida se consulta el
recibo; si está incompleto, Reintentar misma decisión conserva su ID y contenido.
Nunca se inventa un nuevo ID para saltar un conflicto.

## Validación

API: `VAULT_PATH=/tmp/pachimind-tests-unused python -m unittest discover -s tests -v`.
Demo: `python scripts/human_preview.py`, API loopback 18001 con vault sintético nuevo.
Web: build y ejecutar Node con las variables ficticias de la demo Personas,
`VITE_PACHIMIND_URL=http://127.0.0.1:18001 PORT=18301`, luego `npm run test:human`.
Chromium verifica carga por URL/login, fallo y reintento de comprobación, casilla,
aplicación explícita, conflicto/declinación, propuestas de reunión, aclaraciones,
notas protegidas, recuperación tras respuesta perdida y vistas móvil/tableta.
No usar pruebas de decisiones contra el vault de producción.

## Publicación y rollback

Entrega coordinada de API y web: módulos human_review/human_note_review y router,
inclusión del router, parser/modelo de notas y revisión de propuestas; en web,
index.html, human.js/css, compatibilidad relationship-review.js y server.cjs.
Requiere reiniciar API y Node. No cambia dependencias, MCP, OAuth ni datos al
instalar. Comparar hashes previos, probar en staging sintético y respaldar sólo
los archivos reemplazados. Reversión restaura esos archivos y elimina únicamente
los módulos nuevos si coinciden con los hashes instalados; reinicia API y Node.
Conservar sidecars e historial: no restaurar el vault encima de decisiones nuevas.
El código anterior no muestra las revisiones humanas, pero sus registros quedan
conservados para volver a habilitar esta versión.
