#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# PachiMind — Crear /srv/pachimind/.env en el servidor
# Ejecutar UNA SOLA VEZ después del setup inicial
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SERVER="root@212.85.22.34"
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_KEY_FILE="$DEPLOY_DIR/.api-key"

if [ ! -f "$API_KEY_FILE" ]; then
    echo "Error: primero ejecutá 02-deploy.sh para generar la API key."
    exit 1
fi

PROD_API_KEY=$(cat "$API_KEY_FILE")

echo "Ingresá tu GEMINI_API_KEY:"
read -rs GEMINI_KEY
echo ""
echo "Ingresá la contraseña del frontend PachiMind (para el login):"
read -rs FRONTEND_PASS
echo ""

AUTH_SECRET=$(openssl rand -hex 32)

echo "Creando /srv/pachimind/.env en el servidor..."
ssh "$SERVER" "cat > /srv/pachimind/.env << 'ENVEOF'
# PachiMind — Variables de producción

# FastAPI
VAULT_PATH=/srv/pachimind/vault
API_KEYS={\"pm-prod-${PROD_API_KEY}\": \"personal\", \"pm-ai-${PROD_API_KEY:0:16}\": \"ai_context\"}
LOG_LEVEL=INFO
CORS_ORIGINS=[\"https://pachimind.rail.ar\"]

# Node.js / Gemini
GEMINI_API_KEY=${GEMINI_KEY}
AUTH_SECRET=${AUTH_SECRET}
FRONTEND_PASSWORD=${FRONTEND_PASS}
PM_API_KEY=pm-prod-${PROD_API_KEY}
NODE_ENV=production
PORT=3000
ENVEOF
chmod 600 /srv/pachimind/.env
chown pachimind:pachimind /srv/pachimind/.env
echo '.env creado OK'"

echo ""
echo "✅ .env creado. Ejecutá ./02-deploy.sh para reiniciar los servicios."
