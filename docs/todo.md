# TODO: equipo y fechas

El formulario humano y `/actions/todo` permiten guardar los siguientes datos, sin
inferir nombres, responsabilidades, relaciones entre fichas ni fechas:

| Campo | POST | PATCH | Formato |
|---|---|---|---|
| responsable | opcional | sólo cambia si se envía | nombre de hasta 200 caracteres; null para borrar |
| subresponsables | [] por defecto | sólo cambia si se envía | lista de hasta 20 nombres no vacíos de hasta 200 caracteres; [] para borrar |
| fecha_inicio | null por defecto | sólo cambia si se envía | fecha ISO YYYY-MM-DD; null para borrar |
| vencimiento | null por defecto | sólo cambia si se envía | fecha ISO YYYY-MM-DD; null para borrar |

Las fechas deben existir y el inicio no puede superar el vencimiento. PATCH
valida el período resultante contra los campos existentes, incluso si sólo se
envía una fecha. Datos inválidos o revisiones desactualizadas no escriben nada.
Un PATCH de estado/prioridad conserva todos los campos omitidos.

GET devuelve los valores persistidos. Las notas anteriores sin campos nuevos se
leen con [] y null, sin migrar ni reescribir sus archivos. Se conserva el hash de
idempotencia de solicitudes anteriores cuando los campos nuevos están vacíos;
repetir una creación con datos distintos requiere otro request_id.

Sólo cambia el frontmatter de la actividad al editar; su cuerpo y la decisión o
reunión de origen se conservan. No cambia permisos, scope OAuth ni el circuito de
aprobación. La fecha de creación (`fecha`) y la marca de finalización
(`completada_en`) conservan su significado y no se usan como fecha de inicio.

Pruebas: tests/test_todo.py (persistencia, omisiones, borrado, fechas combinadas,
validación, revisiones, fuentes, privacidad e idempotencia) y el navegador de la
web con datos sintéticos. El MCP mantiene su contrato actual: esta entrega amplía
el formulario TODO y su API, sin renovar su catálogo de herramientas.
