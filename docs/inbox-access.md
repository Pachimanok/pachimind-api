# Consentimiento humano de lectura IA para INBOX

GET y POST `/human/inbox-access/{note_id}` usan el guard owner existente: scope
personal y actor manual. El gateway `/api/human/inbox-access/{note_id}` exige la
sesión del frontend. No se agrega una herramienta MCP de autoautorización.

GET devuelve estado de lectura, acciones permitidas, diferencias de permisos y
una revisión que incluye la nota/relaciones y el registro de acceso. POST exige
request_id, revisión, acción enable/revoke, confirmed=true y exactamente los
campos mostrados en authorized_fields. La habilitación es individual y sólo para
borradores. Las autorizaciones existentes pueden revocarse después de activar
la nota documentalmente.

La capa `.pachimind/inbox_access` se vincula al SHA-256 del original. El parser
ignora una declaración acceso_inbox_ia dentro de la nota; sólo acepta el registro
validado externo, para ese ID y esos bytes. Un allow válido aplica ia_permiso=allow
e ia_indexar=true, conservando sensibilidad, ia_editar, fuente_inmutable, estado,
contenido y revisión documental. Revoke restaura los valores del archivo. El
hash de revisión de Personas incluye esta capa para evitar ediciones obsoletas.

Se validan fuentes/datos_fuente, rutas reservadas, salud y sensibilidad; no se
desclasifica ni se abren dependencias. Las fuentes_ids de una nota con este permiso
siguen comprobándose en las lecturas IA si una fuente cambia posteriormente.
Segmentos reservados requieren revisión separada. El permiso no concede escritura.

Historial en inbox_access_history y recibos en inbox_access_requests permiten
recuperar una respuesta perdida y una escritura de permiso previa al recibo, con
el mismo ID y fingerprint. Un ID usado para otra acción o sustituido por otra
revocación/autorización produce conflicto. El original debe seguir idéntico.

GET/POST son no-store. Las pruebas cubren roles, consentimiento exacto, omisiones,
preview sin escrituras, fechas/versiones de permiso, idempotencia, respuesta
interrumpida, revocación, fuente cambiada, inmutable, bloqueos, metadatos forjados,
symlinks y coexistencia con revisión documental. No se modifican políticas de
OAuth ni se otorga acceso a notas productivas durante el despliegue.

Despliegue coordinado API/web, reiniciando sólo API y Node. MCP queda intacto.
Rollback restaura código/bundle/HTML y retira sólo los módulos nuevos de código.
Conservar siempre los registros de autorización y recibos del vault. La versión
anterior del parser no interpreta esta capa, por lo que ignora los permisos nuevos
y aplica los originales; no restaurar el vault ni las bases OAuth.
