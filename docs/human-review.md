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

## Ajuste del 11/11: decisiones concretas y propuestas desactualizadas

La vista principal y su badge cuentan sólo vínculos, fichas/aclaraciones y
propuestas de reuniones. Tener revisado=false no impone releer toda nota. La
revisión completa permanece accesible expresamente en Revisión opcional
(kind=note); no se marca nada aprobado ni se habilita IA para quitarlo de la cola.

Cuando hay conflicto, la lectura calcula una vista previa con los mismos IDs,
tipos de relación, acciones y citas, usando revisiones actuales. Actualizar
propuesta, sin aplicar es una escritura separada que crea otro pendiente y
conserva el anterior como superseded. Exige el hash de ambas vistas, evidencia
literal y destinos compatibles/visibles. No modifica Markdown, revisión documental,
permisos, ni relaciones. Luego debe autorizarse/aprobarse la propuesta nueva.
No se reintenta una aprobación con una revisión distinta ni se amplía su alcance.

La creación es idempotente por request_id; si se pierde la respuesta puede
reintentarse el mismo identificador. El par anterior/nuevo se guarda bajo el
bloqueo compartido; un reintento completa una interrupción sin crear más borradores.
El helper de mantenimiento puede regenerar una propuesta explícitamente solicitada
con ai=True: conserva los controles de visibilidad/evidencia del asistente y sólo
prepara el pendiente. Nunca llama a la operación de aprobación.

Esta entrega reemplaza sólo human_review.py, routers/human.py y los assets web
index.html/human.js/human.css/server.cjs. Reinicia API y Node; conserva MCP/OAuth.
La reversión de código conserva las propuestas y su historial, sin restaurar vault.

## Limpiar avisos sin revisar

En Revisión opcional, Limpiar avisos sin revisar oculta los avisos del resultado
actual de búsqueda, en todas sus páginas. Con búsqueda vacía abarca todos los avisos
opcionales visibles. Ver avisos ocultos y Volver a mostrar avisos revierten esa
preferencia, con el mismo alcance de filtro. No hay que abrir ni releer cada nota.

La limpieza nunca escribe Markdown ni revision_humana. Conserva revisado, estado,
IA, fuente inmutable, relaciones y propuestas pendientes. Al cambiar los bytes o
la revisión efectiva de una nota reaparece su aviso. No es una aprobación global,
una integración automática ni un archivo/borrado. Los avisos ocultos siguen
accesibles explícitamente para el propietario y no cuentan en la pestaña activa.

Se guarda .pachimind/optional_visibility/<hash interno>.json con IDs/revisiones y
recibos, sin cuerpos de notas. La selección paginada lleva un snapshot de todos los
resultados y una generación; cambios posteriores producen 409. Un único reemplazo
atómico persiste preferencias y recibo, para recuperar respuestas perdidas sin
repetir acciones. Las rutas requieren sesión humana/personal; no se agrega MCP.

Entrega de human_review.py, routers/human.py y assets web index/human.js/css y
server.cjs; reinicia API/Node sin cambios MCP/OAuth. La reversión conserva el
sidecar: el código previo vuelve a mostrar avisos porque ignora la preferencia,
pero no altera contenidos/estados/permisos. Nunca restaurar el vault completo.

## Dónde quedan las acciones y decisiones aprobadas

Aprobar una acción de reunión ya crea una nota de acción pendiente que aparece en
TODO. Aprobar una decisión ya crea un registro vinculado al proyecto/reunión, que
aparece en Memoria > proyecto > Decisiones registradas. No se duplica ese guardado.

Los recibos ahora permiten Ver en TODO, Ver decisión, Ver proyecto y Ver reunión.
TODO abre con la actividad enfocada y sin filtros que puedan esconderla; seguir el
acceso no la completa ni cambia fechas/responsables. Las decisiones se abren como
notas y no generan actividades. Ver proyecto abre su memoria para consultar contexto.

Ver acciones y decisiones aprobadas conserva una lista consultable tras recargar,
con filtros por tipo, título/proyecto y paginación. Enlace directo:
/?view=humano&human=aprobadas. Incluye aprobaciones del circuito existente, también
las anteriores a esta entrega. Excluye pendientes/descartadas y comprueba la fuente,
proyecto y registro de aprobación reales; se preservan permisos e inmutabilidad.

La lista y todos sus accesos son sólo lectura. No extraen sugerencias ni aprueban en
lote. Un recibo con respuesta perdida recupera el mismo resultado/destino existente.
La publicación no ejecuta aprobaciones reales ni migra/reescribe notas antiguas.

## Crear una actividad desde una decisión

Los recibos y la lista de decisiones aprobadas ofrecen Crear tarea desde esta
decisión. Abre el formulario editable de TODO; no crea nada al abrir. Guardar
actividad crea una tarea pendiente con enlace a la decisión y al mismo proyecto.
Responsable/fecha quedan vacíos salvo que el usuario los ingrese. La decisión
original conserva sus bytes, estado y permisos; no se mueve ni se completa.

El backend valida la revisión de la decisión y descarta propuestas/Inbox/archivadas.
No reemplaza una revisión en conflicto para forzar la operación. Reintentar una
respuesta perdida conserva request_id y devuelve la misma tarea. Se mantienen
sensibilidad y restricciones del proyecto/fuente y la dependencia de visibilidad;
no se copia el cuerpo de la decisión. TODO permite Ver decisión de origen.

El contenedor de TODO ahora crece dentro del desplazamiento principal, evitando
el recorte por flex/overflow:hidden. La prueba de navegador usa rueda y gestos
táctiles reales con 35 filas y verifica acceso a los controles de la última tarea.

## Procedencia de decisiones

Los elementos `meeting` de cola/detalle y los destinos aprobados incluyen
`context`: `project`, `source` (id, título, ruta y tipo), `meeting_date` y
`proposal_type`. La fecha sólo se toma de la propiedad fecha válida de la fuente;
no se infiere del archivo ni de la aprobación. Se comprueba de nuevo la visibilidad
de proyecto/fuente y sus dependencias. La búsqueda permite sus títulos además del
texto que ya se buscaba. El catálogo no devuelve cuerpos ni citas: la evidencia
literal continúa en el detalle de la propuesta y en los registros originales.

Esta información es de lectura: no cambia revisiones, estados, ACL ni propuestas,
no requiere migrar notas existentes y conserva las mismas autorizaciones humanas.
