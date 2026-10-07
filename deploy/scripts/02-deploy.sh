#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# PachiMind — Deploy completo (API + frontend)
# Ejecutar desde tu Mac local
#
# Uso: ./deploy/scripts/02-deploy.sh
# Requiere: ~/.ssh/config con entrada para pachimind (ver README)
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuración ────────────────────────────────────────────────
SERVER="root@212.85.22.34"
DOMAIN="pachimind.rail.ar"
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
FRONTEND_DIR="/Users/pablorio/Developer/pachimind-web"

# API key de producción (se genera una sola vez)
API_KEY_FILE="$DEPLOY_DIR/.api-key"
if [ ! -f "$API_KEY_FILE" ]; then
    echo "Generando API key de producción..."
    openssl rand -hex 32 > "$API_KEY_FILE"
    echo "  API key guardada en $API_KEY_FILE (no commitear)"
fi
PROD_API_KEY=$(cat "$API_KEY_FILE")

echo "════════════════════════════════════════════"
echo " PachiMind — Deploy a $DOMAIN"
echo "════════════════════════════════════════════"

# ── 1. Deploy API ────────────────────────────────────────────────
echo "[1/5] Sincronizando código de la API..."
rsync -az --delete \
    --exclude='.env' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='deploy' \
    --exclude='tests' \
    "$API_DIR/" "$SERVER:/srv/pachimind/api/"

echo "[1/5] Instalando dependencias Python..."
ssh "$SERVER" "
    /srv/pachimind/api/.venv/bin/pip install -q --upgrade pip
    /srv/pachimind/api/.venv/bin/pip install -q -r /srv/pachimind/api/requirements.txt
    chown -R pachimind:pachimind /srv/pachimind/api/
"

# ── 2. Deploy systemd services ───────────────────────────────────
echo "[2/5] Instalando servicios systemd..."
scp "$DEPLOY_DIR/systemd/pachimind-api.service"        "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/pachimind-node.service"       "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/vault-sync.service"           "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/vault-sync.timer"             "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/notebooklm-keepalive.service" "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/notebooklm-keepalive.timer"   "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/weekly-digest.service"        "$SERVER:/tmp/"
scp "$DEPLOY_DIR/systemd/weekly-digest.timer"          "$SERVER:/tmp/"

ssh "$SERVER" "
    mv /tmp/pachimind-api.service        /etc/systemd/system/
    mv /tmp/pachimind-node.service       /etc/systemd/system/
    mv /tmp/vault-sync.service           /etc/systemd/system/
    mv /tmp/vault-sync.timer             /etc/systemd/system/
    mv /tmp/notebooklm-keepalive.service /etc/systemd/system/
    mv /tmp/notebooklm-keepalive.timer   /etc/systemd/system/
    mv /tmp/weekly-digest.service        /etc/systemd/system/
    mv /tmp/weekly-digest.timer          /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable pachimind-api pachimind-node vault-sync.timer notebooklm-keepalive.timer weekly-digest.timer
"

# ── 3. Deploy Apache2 config ─────────────────────────────────────
echo "[3/5] Actualizando configuración Apache2..."
sed "s/REPLACE_API_KEY/pm-prod-$PROD_API_KEY/g" \
    "$DEPLOY_DIR/apache/pachimind.conf" > /tmp/pachimind-apache.conf

scp /tmp/pachimind-apache.conf "$SERVER:/tmp/pachimind.conf"
rm /tmp/pachimind-apache.conf

ssh "$SERVER" "
    mv /tmp/pachimind.conf /etc/apache2/sites-available/pachimind.conf
    a2ensite pachimind.conf
    a2dissite pachimind-bootstrap.conf 2>/dev/null || true
    apache2ctl configtest && systemctl reload apache2
"

# ── 4. Build y deploy frontend ───────────────────────────────────
echo "[4/5] Building frontend..."
(
    cd "$FRONTEND_DIR"
    npm install --silent
    npm run build
)

echo "[4/5] Sincronizando frontend con servidor..."
rsync -az --delete \
    --exclude='*.map' \
    "$FRONTEND_DIR/dist/" "$SERVER:/srv/pachimind/node/dist/"

rsync -az \
    "$FRONTEND_DIR/package.json" \
    "$FRONTEND_DIR/package-lock.json" \
    "$SERVER:/srv/pachimind/node/"

ssh "$SERVER" "
    cd /srv/pachimind/node
    npm install --production --silent
    chown -R pachimind:pachimind /srv/pachimind/node/
"

# ── 5. Reiniciar servicios ───────────────────────────────────────
echo "[5/5] Reiniciando servicios..."
ssh "$SERVER" "
    systemctl restart pachimind-api
    systemctl restart pachimind-node
    systemctl start vault-sync.timer
    sleep 3
    echo '--- API ---'
    systemctl status pachimind-api --no-pager -l | tail -5
    echo '--- Node ---'
    systemctl status pachimind-node --no-pager -l | tail -5
"

echo ""
echo "════════════════════════════════════════════════════════"
echo " ✅ Deploy completado!"
echo "    🌐 https://pachimind.rail.ar"
echo ""
echo " API key de producción: $PROD_API_KEY"
echo " (guardada en $API_KEY_FILE)"
echo "════════════════════════════════════════════════════════"
