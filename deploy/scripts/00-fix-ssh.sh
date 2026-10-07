#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# PachiMind — Limpiar conflicto de SSH key del servidor
# Ejecutar PRIMERO, antes de cualquier otro script
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SERVER_IP="212.85.22.34"
DOMAIN="pachimind.rail.ar"

echo "Limpiando keys SSH viejas del servidor..."
ssh-keygen -R "$SERVER_IP"  2>/dev/null || true
ssh-keygen -R "$DOMAIN"     2>/dev/null || true
echo "✅ Keys viejas eliminadas."
echo ""

echo "Conectando al servidor para aceptar la nueva key..."
echo "(Va a pedir la contraseña de root)"
echo ""
ssh -o StrictHostKeyChecking=accept-new root@$SERVER_IP "echo '✅ SSH OK — servidor conectado'"

echo ""
echo "Copiando tu SSH key pública al servidor (para no necesitar contraseña de nuevo)..."
ssh-copy-id root@$SERVER_IP

echo ""
echo "✅ Todo listo. Ya podés ejecutar los demás scripts sin contraseña."
echo ""
echo "Orden de ejecución:"
echo "  1. ./01-setup-server.sh   (instala deps, configura Apache, SSL)"
echo "  2. ./03-vault-upload.sh   (sube el vault)"
echo "  3. ./04-env-setup.sh      (configura .env con keys)"
echo "  4. ./05-vault-github-sync.sh  (opcional: sync Obsidian via GitHub)"
echo "  5. ./02-deploy.sh         (deploy completo)"
