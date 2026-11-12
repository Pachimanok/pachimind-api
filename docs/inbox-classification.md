# Clasificación de Inbox propuesta por un agente

`ia_editar: false` protege el original; no bloquea leer una nota permitida ni
preparar una clasificación aparte. `propose_inbox_classification` requiere OAuth
read+write y acceso IA efectivo. Recibe ID, revisión de read_inbox_note, request_id
y classification (title, tipo, area, tags, comment, content opcional). Antes de
proponer, el agente lee toda la fuente y las preferencias vigentes. La API vuelve
a validar acceso y revisión; el MCP no usa una vía de edición manual.

La propuesta queda en una capa separada, pendiente de revisión. No modifica ni
archiva la fuente, no aumenta permisos ni aprueba tareas o decisiones. Los tipos
admitidos son nota, recurso, idea y registro; fichas, acciones y decisiones tienen
sus flujos específicos. Omitir content conserva el cuerpo original en la derivada.

En Inbox aparece «Clasificación MCP pendiente de confirmar». «Revisar clasificación
MCP» abre los campos y el contenido propuestos. El propietario puede ajustarlos,
confirmar el procesamiento y guardar, o declinar. La confirmación está restringida
a la sesión humana del propietario. Se crea una nota derivada vinculada a la fuente;
el original sale del Inbox mediante un estado externo. Sus bytes, inmutabilidad,
ia_editar y consentimiento de lectura se conservan, incluso en fuentes inmutables.
Declinar no crea notas ni retira el original del Inbox. Guardar no crea TODOs ni
aprueba propuestas operativas.

Una revisión desactualizada se rechaza. Si cambió la fuente o su acceso, preparar
otra propuesta con revisión nueva; se conserva la anterior en el historial. Los
reintentos reutilizan request_id y recuperan operaciones cuya respuesta o recibo
se perdió, sin duplicar notas. Una derivada continúa dependiendo de las restricciones
de su fuente; revocar el acceso de ésta impide leerla mediante IA.

GET /notes y GET /notes/{id} incluyen mcp_access.available calculado en el servidor,
separado de editable_original, e inbox_classification (estado y vigencia). La UI
muestra «MCP: habilitado» o «MCP: no habilitado» sin abrir Acceso MCP, y «sin comprobar»
si un servidor antiguo no envía ese dato. Abrir el control no es lo que lo habilita.

Pruebas: propuestas con originales protegidos, lectura y escritura OAuth, rechazo
por permisos/revisiones/tipos operativos, confirmación sólo humana, preservación
de fuentes, declinación, regeneración y reintentos. Navegador Chromium de escritorio
y móvil con API real y fixture sintético, incluyendo respuesta perdida y estado
visible sin diálogo. Ninguna nota productiva es necesaria para probar este flujo.
