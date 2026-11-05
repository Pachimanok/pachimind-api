# Revisión documental de capturas inmutables

Una captura puede cerrar la revisión de fecha y asistentes sin atribuir voces,
validar cifras económicas ni aprobar propuestas, decisiones, tareas o enlaces.
El texto y frontmatter originales permanecen intactos. La API expone la revisión
en `metadata.revision_documental`, los asistentes efectivos en `metadata.personas`
y la fecha efectiva en `metadata.fecha`. `get_meeting` conserva también
`participantes_originales` y `fecha_original`.

El operador instala un registro **sólo después de recibir confirmación humana** en
`<vault>/.pachimind/meeting_reviews/<sha256-del-id-de-la-nota>.json`. El registro
incluye `source_id`, `source_sha256` del archivo completo, `review_kind: documental`,
`reviewed: true`, `approved_by`, `approved_date`, `meeting_date`, `participants`,
`speaker_assignment: unassigned` y `financial_facts_validated: false`.
No hay endpoint para que un agente apruebe estos registros. Usar propietario del
servicio, directorio privado 0700 y archivo 0600; actualizar mediante renombrado
atómico. No incluir confirmaciones reales ni datos personales en el repositorio.

La revisión sólo se aplica a una captura de reunión inmutable con el ID y hash
exactos. Un registro inválido, corrupto o con campos extra se ignora, conservando
la nota sin revisar. No cambia permisos IA, sensibilidad ni contenido. Cambiar el
original invalida la revisión. Una revisión válida actualiza `revisado`, por lo
que la captura deja de aparecer entre las pendientes del tablero. Esto significa
**revisión documental**, no validación de toda afirmación de la transcripción.

Reiniciar la API o reconstruir el índice después de instalar, modificar o quitar
un registro: el watcher actual sólo sigue archivos Markdown. La revisión modifica
la revisión lógica de la nota; propuestas de enlaces anteriores deben releerse y,
si corresponde, regenerarse en vez de forzar la revisión antigua.

Para desplegar, respaldar los archivos de código modificados y registrar el hash
del original. Probar primero contra un vault sintético, instalar sólo esos archivos
y el registro autorizado, reiniciar exclusivamente la API y verificar lectura,
permisos, hash original y pendientes. Para revertir, restaurar ese código, quitar
únicamente el registro recién creado si conserva su hash y reiniciar la API.
No restaurar el vault entero ni modificar registros OAuth.
