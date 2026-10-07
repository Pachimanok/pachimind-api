# PachiMind — Despliegue de Memoria

Esta configuración candidata debe contrastarse con la instalación real antes del corte. No sincroniza el vault.

## Acceso

- Apache publica HTTPS y manda la web y las rutas heredadas al gateway Node.
- Node exige sesión válida para la web. En las rutas heredadas admite una X-API-Key del cliente, que reenvía sin elevar su scope.
- `/api/v1/` expone FastAPI directamente sin inyectar claves. Cada consumidor debe presentar su propia X-API-Key con el scope adecuado.
- `/api/ai/chat/internal` está bloqueado en Apache y requiere una clave interna en Node. El linker Python usa PM_API_KEY del entorno compartido para ese intercambio.
- Node y FastAPI escuchan en loopback. No abrir 3000 ni 8000 a Internet.

## Antes de aplicar

1. Confirmar SSH, paths activos y servicios. Comparar la configuración efectiva de Apache, incluidos sites-enabled y archivos SSL generados.
2. Comprobar, sin imprimir secretos, que PM_API_KEY sea una clave personal aceptada en API_KEYS y esté disponible para ambos servicios.
3. Respaldar código, frontend compilado, unidades systemd y configuración Apache con permisos restringidos. No volcar secretos a logs.
4. Comparar las copias de Markdown mediante el comparador de lectura. Mantener producción como está durante el despliegue de código; no ejecutar rsync --delete sobre el vault.
5. Revisar los consumidores externos existentes. Las rutas heredadas siguen aceptando X-API-Key; recomendar /api/v1 para integraciones nuevas.

## Corte

Construir el frontend antes de subirlo. Sincronizar únicamente código probado, preservando .env, .venv, node_modules, adjuntos y vault. Actualizar API y Node, reiniciarlos y comprobarlos por loopback. Instalar la nueva unidad Node con HOST=127.0.0.1.

Aplicar Apache al final, comprobando que sites-enabled use realmente la configuración nueva. Ejecutar apache2ctl configtest antes de recargar. Ante fallo restaurar la configuración respaldada; ante fallos funcionales restaurar también los servicios y código. No usar a ciegas 02-deploy.sh: la versión histórica genera/imprime claves y no implementa este procedimiento de respaldo y rollback.

## Verificaciones

- /health responde.
- /notes y /projects/memory sin sesión ni API key: 401.
- /api/v1/projects/memory sin API key: 401; con clave de contexto, solo fuentes permitidas.
- Login web, Memoria, captura, revisión y contexto portable funcionan.
- /api/ai/chat/internal desde HTTPS: bloqueado, incluso con variantes de ruta.
- Subida multipart conserva los bytes.
- Originales protegidos, scopes y citas siguen respetándose.

El cambio de código no resuelve por sí solo la divergencia del vault. La reconciliación requiere comparar primero y conservar las versiones exclusivas de cada copia.
