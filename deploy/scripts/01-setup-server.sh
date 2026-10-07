#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# PachiMind — Setup inicial del servidor
# Servidor: Ubuntu 24.04 — Apache2 ya instalado, convive con otros proyectos
#
# Uso: ssh root@212.85.22.34 "bash -s" < deploy/scripts/01-setup-server.sh
#
# NO toca: iptables, Apache2 virtual hosts existentes, MySQL, bases de datos
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

DOMAIN="pachimind.rail.ar"
APP_USER="pachimind"
APP_DIR="/srv/pachimind"

echo "════════════════════════════════════════"
echo " PachiMind — Setup servidor ($DOMAIN)"
echo "════════════════════════════════════════"

# ── 1. Dependencias del sistema ──────────────────────────────────
echo "[1/7] Instalando dependencias del sistema..."
apt-get update -qq
apt-get install -y -qq \
    git curl wget unzip build-essential \
    certbot python3-certbot-apache \
    python3.12 python3.12-venv python3-pip

# ── 2. Node.js 20 ───────────────────────────────────────────────
echo "[2/7] Instalando Node.js 20..."
if ! command -v node &>/dev/null || [[ "$(node --version)" != v20* ]]; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
fi
echo "  Node: $(node --version) | npm: $(npm --version)"

# ── 3. Módulos Apache2 ───────────────────────────────────────────
echo "[3/7] Habilitando módulos Apache2..."
a2enmod proxy proxy_http proxy_wstunnel ssl headers rewrite
# NO tocar sitios existentes

# ── 4. Usuario y directorios ─────────────────────────────────────
echo "[4/7] Creando usuario '$APP_USER' y directorios..."
id "$APP_USER" &>/dev/null || useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER"

mkdir -p \
    "$APP_DIR/api" \
    "$APP_DIR/node" \
    "$APP_DIR/vault" \
    "$APP_DIR/backups"

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"

# ── 5. Python venv ───────────────────────────────────────────────
echo "[5/7] Creando venv Python..."
if [ ! -d "$APP_DIR/api/.venv" ]; then
    sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/api/.venv"
fi

# ── 6. Git config para vault ─────────────────────────────────────
echo "[6/7] Configurando git para el vault..."
sudo -u "$APP_USER" git config --global user.name  "PachiMind Server"
sudo -u "$APP_USER" git config --global user.email "server@pachimind"
sudo -u "$APP_USER" git config --global init.defaultBranch main

if [ ! -d "$APP_DIR/vault/.git" ]; then
    sudo -u "$APP_USER" git -C "$APP_DIR/vault" init
    cat > "$APP_DIR/vault/.gitignore" << 'GITIGNORE'
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.DS_Store
*.sync-conflict-*
10 Sensible/
GITIGNORE
    chown "$APP_USER:$APP_USER" "$APP_DIR/vault/.gitignore"
fi

# ── 7. SSL con Let's Encrypt (Apache) ────────────────────────────
echo "[7/7] Obteniendo certificado SSL para $DOMAIN..."
# Crear VHost bootstrap mínimo si no existe aún
APACHE_BOOTSTRAP="/etc/apache2/sites-available/pachimind-bootstrap.conf"
if [ ! -f "$APACHE_BOOTSTRAP" ]; then
    cat > "$APACHE_BOOTSTRAP" << APACHECONF
<VirtualHost *:80>
    ServerName $DOMAIN
    DocumentRoot /var/www/html
</VirtualHost>
APACHECONF
    a2ensite pachimind-bootstrap.conf
    systemctl reload apache2
fi

certbot certonly --apache -d "$DOMAIN" --non-interactive --agree-tos \
    -m admin@rail.ar || echo "  ⚠️  Certbot falló — puede que el dominio aún no apunte a este servidor"

# Desactivar el bootstrap (el deploy.sh instala el VHost final)
a2dissite pachimind-bootstrap.conf 2>/dev/null || true

echo ""
echo "════════════════════════════════════════════════════════"
echo " ✅ Setup completo. Próximos pasos:"
echo ""
echo " 1. Subir vault:    ./deploy/scripts/03-vault-upload.sh"
echo " 2. Config GitHub:  ./deploy/scripts/05-vault-github-sync.sh"
echo " 3. Deploy:         ./deploy/scripts/02-deploy.sh"
echo "════════════════════════════════════════════════════════"
