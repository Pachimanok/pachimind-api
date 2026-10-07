#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# PachiMind — Configurar sync del vault con GitHub
#
# Esto permite usar Obsidian Git (plugin) en tu Mac y mobile
# para sincronizar el vault con el servidor automáticamente.
#
# Arquitectura:
#   Servidor ──push cada 5min──► GitHub (repo privado)
#   Mac/Mobile ◄──pull/push───── GitHub (Obsidian Git plugin)
#
# Uso: ./deploy/scripts/05-vault-github-sync.sh
# Requiere: haber creado un repo privado en GitHub
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SERVER="root@212.85.22.34"

echo "════════════════════════════════════════"
echo " PachiMind — Vault sync con GitHub"
echo "════════════════════════════════════════"
echo ""
echo "Ingresá la URL SSH del repo privado de GitHub para el vault."
echo "Ejemplo: git@github.com:pachimanok/pachimind-vault.git"
echo ""
read -rp "GitHub repo SSH URL: " GITHUB_REPO

echo ""
echo "[1/3] Generando SSH key en el servidor para GitHub..."
ssh "$SERVER" "
    KEYFILE=/srv/pachimind/.ssh/github_vault
    mkdir -p /srv/pachimind/.ssh
    chmod 700 /srv/pachimind/.ssh

    if [ ! -f \"\$KEYFILE\" ]; then
        ssh-keygen -t ed25519 -C 'pachimind-server@rail.ar' -f \"\$KEYFILE\" -N ''
        chown -R pachimind:pachimind /srv/pachimind/.ssh
    fi

    echo ''
    echo '══════════════════════════════════════════════════'
    echo ' Clave pública del servidor — agregar a GitHub:'
    echo '══════════════════════════════════════════════════'
    cat \"\$KEYFILE.pub\"
    echo '══════════════════════════════════════════════════'
"

echo ""
echo "[2/3] Agregá esa clave pública como Deploy Key en tu repo de GitHub:"
echo "  → https://github.com/pachimanok/$(basename $GITHUB_REPO .git)/settings/keys"
echo "  → New deploy key → Title: 'PachiMind Server' → Pegá la clave → ✅ Allow write access"
echo ""
read -rp "Presioná Enter cuando hayas agregado la clave en GitHub..."

echo ""
echo "[3/3] Configurando remote y testeando conexión..."
ssh "$SERVER" "
    KEYFILE=/srv/pachimind/.ssh/github_vault

    # Configurar SSH para usar esta key con GitHub
    cat > /srv/pachimind/.ssh/config << 'SSHCONF'
Host github.com
    IdentityFile /srv/pachimind/.ssh/github_vault
    StrictHostKeyChecking no
SSHCONF
    chmod 600 /srv/pachimind/.ssh/config
    chown pachimind:pachimind /srv/pachimind/.ssh/config

    # Agregar remote al vault
    cd /srv/pachimind/vault
    sudo -u pachimind git config core.sshCommand 'ssh -i /srv/pachimind/.ssh/github_vault -o StrictHostKeyChecking=no'

    # Agregar o actualizar remote
    sudo -u pachimind git remote remove origin 2>/dev/null || true
    sudo -u pachimind git remote add origin $GITHUB_REPO

    # Testear conexión
    echo 'Testeando conexión SSH con GitHub...'
    sudo -u pachimind ssh -i \$KEYFILE -o StrictHostKeyChecking=no -T git@github.com 2>&1 || true

    # Push inicial
    echo 'Haciendo push inicial...'
    sudo -u pachimind git push -u origin main || sudo -u pachimind git push -u origin master

    echo 'Remote configurado y push inicial exitoso.'
"

echo ""
echo "════════════════════════════════════════════════════════"
echo " ✅ GitHub sync configurado!"
echo ""
echo " El servidor pushea el vault cada 5 minutos automáticamente."
echo ""
echo " Para sincronizar desde Obsidian en tu Mac:"
echo "   1. Instalar plugin: Obsidian → Settings → Community plugins → Obsidian Git"
echo "   2. Clonar el repo: git clone $GITHUB_REPO ~/PachiMind-Vault"
echo "   3. Abrir ~/PachiMind-Vault como vault en Obsidian"
echo "   4. En el plugin: Auto pull interval: 5min, Auto push: on commit"
echo ""
echo " En mobile (iOS/Android):"
echo "   → Working Copy (iOS) o MGit (Android) + Obsidian Git plugin"
echo "════════════════════════════════════════════════════════"
