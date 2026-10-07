#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# PachiMind — Subir el vault al servidor
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SERVER="root@212.85.22.34"
LOCAL_VAULT="/Users/pablorio/Documents/PachiMind-vault"
REMOTE_VAULT="/srv/pachimind/vault"

echo "Sincronizando vault..."
echo "  Local:  $LOCAL_VAULT"
echo "  Remoto: $SERVER:$REMOTE_VAULT"
echo ""
echo "⚠️  Este --delete espeja el vault local sobre el remoto: cualquier"
echo "    carpeta/nota que exista SOLO en el servidor (creada vía la app"
echo "    en producción) se borra. Verificá con --dry-run antes si los"
echo "    vaults pueden haber divergido:"
echo "    rsync -avzn --delete --exclude='.git/' ... (agregar el resto de excludes)"
echo ""

rsync -avz --delete \
    --exclude='.DS_Store' \
    --exclude='*.sync-conflict-*' \
    --exclude='.obsidian/workspace.json' \
    --exclude='.obsidian/workspace-mobile.json' \
    --exclude='.git/' \
    --exclude='10 Sensible/' \
    "$LOCAL_VAULT/" "$SERVER:$REMOTE_VAULT/"

# Corregir permisos y hacer commit inicial en el servidor
ssh "$SERVER" "
    chown -R pachimind:pachimind $REMOTE_VAULT
    cd $REMOTE_VAULT
    sudo -u pachimind git add -A
    sudo -u pachimind git diff --cached --quiet || sudo -u pachimind git commit -m 'upload inicial: \$(date --iso-8601=seconds)'
    echo 'Vault subido y commiteado.'
"

echo ""
echo "✅ Vault sincronizado. La API lo indexa automáticamente al reiniciar."
