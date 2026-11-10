# Ámbitos, conexiones y notas huérfanas

La auditoría es de sólo lectura. No agrega relaciones por similitud de nombres,
no reescribe notas y no modifica permisos o propuestas.

Una nota es **huérfana en la vista actual** cuando no tiene conexiones visibles,
ni entrantes ni salientes. Tener un área o ámbito no crea una conexión. Las
referencias rotas, ambiguas y propuestas pendientes tampoco la crean. Una baja
registrada en la capa de relaciones se respeta aunque siga el enlace original.

**Sin nodo general** identifica notas que no son ellas mismas un proyecto,
persona, organización o cliente, y no alcanzan un nodo de esos tipos en un máximo
de dos enlaces explícitos. Los ciclos no amplían ese recorrido. Las relaciones
indirectas se muestran con la nota intermedia, sin afirmar pertenencia o roles.

Los ámbitos se toman exclusivamente de `ambitos` y `area`. Laboral se muestra
como Trabajo; Apostólico como Apostolado. No se deducen de la carpeta, de los
nombres ni de otra nota. No se fusionan identidades ni proyectos.

## API

- `GET /vault/associations`: `view=orphans` (predeterminada), `all`, `no_general`
  o `unresolved`; filtros `q`, `ambito`; `page >= 1`, `per_page` entre 1 y 100.
  Incluye totales del conjunto visible, resultados paginados y ámbitos disponibles.
  Los filtros no redefinen los totales globales. Incluye estados de cada nota,
  también borradores/archivadas cuando sus permisos los hacen visibles.
- `GET /vault/associations/{note_id}`: ámbitos, enlaces entrantes/salientes,
  destinos directos, nodos generales hasta dos pasos y referencias sin resolver.
  Los nodos generales del listado se limitan a seis; en detalle, a cien. El total
  real acompaña la respuesta y la interfaz avisa si hay más.

Ambas rutas exigen las claves existentes y usan `Cache-Control: no-store`.
`ai_context` y `X-PachiMind-Actor: assistant` conservan las restricciones IA;
una nota no disponible devuelve 404. Nodos ocultos, sus evidencias y sus enlaces
no sirven de puente a otros nodos. Nunca se devuelve el cuerpo de una nota.
La ausencia de conexiones visibles no prueba ausencia de enlaces privados.

## Interfaz y validación

Vault muestra las vistas Huérfanas, Sin nodo general, Referencias sin resolver y
Todas las notas, con filtros y paginación. Al abrir una nota aparecen sus ámbitos,
proyectos, personas, organizaciones/clientes y conexiones indirectas navegables.
Un error al consultar conexiones se informa como error, nunca como nota huérfana.
No se confunde la ausencia de vínculos rotos con un vault completamente conectado.

API: `VAULT_PATH=/tmp/pachimind-tests-unused python -m unittest discover -s tests -v`.
Demo aislada: `python scripts/association_preview.py` en el virtualenv de API.
Siempre crea un vault sintético nuevo; no admite un vault real. Luego iniciar el
frontend con las variables ficticias documentadas en `docs/people-v1.md` y ejecutar
`npm run test:associations` en pachimind-web. También se mantienen las pruebas
existentes de Personas y de propuestas de reuniones.

Para auditar producción, usar exclusivamente las rutas autorizadas con el actor
correcto. La revisión del asistente cubre sólo las notas permitidas para IA; el
propietario puede ver su conjunto completo permitido desde la interfaz. No copiar
credenciales ni contenido reservado a informes. Toda asociación nueva requiere
una propuesta verificable y autorización acorde al circuito existente.

## Despliegue y reversión

Instalar app/core/associations.py y app/routers/associations.py antes de activar
su router en app/main.py. Reiniciar sólo API; luego publicar dist/index.html,
dist/associations.js y dist/associations.css. Los archivos estáticos no requieren
reiniciar Node. No actualizar dependencias, MCP, OAuth ni el vault para esta vista.

Antes de instalar, verificar hashes de los archivos actuales y respaldar sólo
los destinos modificados. Probar con un vault sintético y validar luego salud,
rechazo sin autenticación y lectura con permisos. Si el código actual difiere
del esperado, detenerse y comparar; no restaurar una versión antigua completa.
Para revertir, restaurar esos archivos, quitar sólo los módulos/assets nuevos de
esta entrega si sus hashes siguen coincidiendo y reiniciar API. No restaurar el
vault completo ni borrar relaciones reales.
