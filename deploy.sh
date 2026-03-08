#!/usr/bin/env bash
# =============================================================================
# Grader — VPS Deployment Script (Hetzner CX33 / Ubuntu 24.04)
# =============================================================================
# Usage:
#   1. Create VPS on Hetzner Cloud (CX33, Ubuntu 24.04)
#   2. SSH in: ssh root@YOUR_VPS_IP
#   3. Run:    bash deploy.sh
#
#   On subsequent deployments (updates):
#              bash deploy.sh update
# =============================================================================

set -euo pipefail

REPO_DIR="/root/grader"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
# UPDATE MODE — pull latest code and restart
# ─────────────────────────────────────────────────────────────────────────────
if [ "${1:-}" = "restore" ]; then
    BACKUP_FILE="${2:-}"
    if [ -z "$BACKUP_FILE" ]; then
        info "Available backups:"
        ls -lh /root/backups/*.sql.gz 2>/dev/null || true
        ls -lh /root/backups/*.tar.gz 2>/dev/null || true
        echo ""
        echo "Usage:"
        echo "  Database:     bash deploy.sh restore /root/backups/grader_YYYYMMDD.sql.gz"
        echo "  Data/exports: bash deploy.sh restore /root/backups/grader_data_YYYYMMDD.tar.gz"
        exit 1
    fi
    [ ! -f "$BACKUP_FILE" ] && error "Backup file not found: $BACKUP_FILE"
    cd "$REPO_DIR"

    if [[ "$BACKUP_FILE" == *.sql.gz ]]; then
        # ── DB restore ──
        source .env
        warn "This will REPLACE the current database with: $BACKUP_FILE"
        warn "Note: This restores PostgreSQL only. To also restore files, run again with a .tar.gz backup."
        read -rp "Type 'yes' to confirm: " CONFIRM
        [ "$CONFIRM" != "yes" ] && error "Aborted."
        info "Restoring database..."
        gunzip < "$BACKUP_FILE" | $COMPOSE exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --quiet
        info "=== Database restored from $BACKUP_FILE ==="
    elif [[ "$BACKUP_FILE" == *.tar.gz ]]; then
        # ── Data/exports restore ──
        warn "This will OVERWRITE data/ and exports/ with: $BACKUP_FILE"
        warn "Note: This restores files only. To also restore the database, run again with a .sql.gz backup."
        read -rp "Type 'yes' to confirm: " CONFIRM
        [ "$CONFIRM" != "yes" ] && error "Aborted."
        info "Restoring data and exports..."
        tar xzf "$BACKUP_FILE" -C "$REPO_DIR"
        info "=== Data/exports restored from $BACKUP_FILE ==="
    else
        error "Unrecognized backup format. Expected .sql.gz (DB) or .tar.gz (data/exports)."
    fi
    exit 0
fi

if [ "${1:-}" = "update" ]; then
    info "=== Update Deployment ==="
    cd "$REPO_DIR"
    
    info "Pulling latest code..."
    git pull origin main
    
    info "Building frontend..."
    $COMPOSE --profile build run --rm frontend-build
    
    info "Rebuilding and restarting services..."
    $COMPOSE up -d --build
    
    info "Waiting for health check..."
    sleep 15
    $COMPOSE ps
    
    info "=== Update complete ==="
    exit 0
fi

# ─────────────────────────────────────────────────────────────────────────────
# INITIAL SETUP
# ─────────────────────────────────────────────────────────────────────────────

# === Phase 2: System Setup ===
info "=== Phase 2: System Preparation ==="

info "Updating system packages..."
apt-get update && apt-get upgrade -y

info "Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    info "Docker installed successfully."
else
    info "Docker already installed."
fi

info "Installing Docker Compose plugin..."
if ! docker compose version &> /dev/null; then
    apt-get install -y docker-compose-plugin
fi

# Verify Docker is working
docker version >/dev/null 2>&1 || error "Docker is not working"
docker compose version >/dev/null 2>&1 || error "Docker Compose is not working"
info "Docker verified: $(docker --version)"

info "Configuring firewall (UFW)..."
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
info "Firewall configured: SSH + HTTP + HTTPS only."

# SSH hardening
info "Hardening SSH..."
SSHD_CONFIG="/etc/ssh/sshd_config"
if grep -q "^PasswordAuthentication yes" "$SSHD_CONFIG" 2>/dev/null; then
    sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' "$SSHD_CONFIG"
    sed -i 's/^#PasswordAuthentication .*/PasswordAuthentication no/' "$SSHD_CONFIG"
fi
if grep -q "^PermitRootLogin yes" "$SSHD_CONFIG" 2>/dev/null; then
    sed -i 's/^PermitRootLogin yes/PermitRootLogin prohibit-password/' "$SSHD_CONFIG"
fi
systemctl reload sshd 2>/dev/null || true
info "SSH: password auth disabled, root login key-only."

# Install fail2ban
if ! command -v fail2ban-client &> /dev/null; then
    info "Installing fail2ban..."
    apt-get install -y fail2ban
    systemctl enable fail2ban
    systemctl start fail2ban
fi

# Swap (2GB — helpful for 8GB VPS)
if [ ! -f /swapfile ]; then
    info "Creating 2GB swap..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl vm.swappiness=10
    echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# === Clone Repository ===
info "=== Cloning Repository ==="
if [ ! -d "$REPO_DIR" ]; then
    read -rp "Enter your Git repository URL: " GIT_URL
    git clone "$GIT_URL" "$REPO_DIR"
else
    warn "Repository already exists at $REPO_DIR, pulling latest..."
    cd "$REPO_DIR" && git pull origin main
fi
cd "$REPO_DIR"

# === Phase 3: Environment Configuration ===
info "=== Phase 3: Environment Configuration ==="

if [ ! -f .env ]; then
    # Try multiple locations for .env.production
    ENV_SOURCE=""
    if [ -f .env.production ]; then
        ENV_SOURCE=".env.production"
    elif [ -f "$SCRIPT_DIR/.env.production" ]; then
        ENV_SOURCE="$SCRIPT_DIR/.env.production"
    elif [ -f /root/.env.production ]; then
        ENV_SOURCE="/root/.env.production"
    fi

    if [ -n "$ENV_SOURCE" ]; then
        cp "$ENV_SOURCE" .env
        warn "Copied $ENV_SOURCE → .env"
        warn ">>> EDIT .env NOW with your real secrets before continuing! <<<"
        warn ">>> Run: nano .env <<<"
        read -rp "Press Enter after editing .env to continue..."
    else
        warn ".env.production not found in project, $SCRIPT_DIR, or /root/"
        warn "You can provide a path, or press Enter to abort."
        read -rp "Path to .env.production (or Enter to abort): " ENV_PATH
        if [ -n "$ENV_PATH" ] && [ -f "$ENV_PATH" ]; then
            cp "$ENV_PATH" .env
            warn "Copied $ENV_PATH → .env"
            warn ">>> EDIT .env NOW with your real secrets before continuing! <<<"
            read -rp "Press Enter after editing .env to continue..."
        else
            error "No .env file found. Upload .env.production to the server first:\n  scp .env.production root@VPS_IP:/root/.env.production"
        fi
    fi
else
    info ".env already exists."
fi

# Validate critical env vars
source .env
[ -z "${PRODUCTION_DOMAIN:-}" ] && error "PRODUCTION_DOMAIN is not set in .env"
[ -z "${GROQ_API_KEY:-}" ] && error "GROQ_API_KEY is not set in .env"
[ "${POSTGRES_PASSWORD:-}" = "CHANGE_ME_GENERATE_WITH_COMMAND_ABOVE" ] && error "POSTGRES_PASSWORD has not been changed from the template"
[ "${JWT_SECRET_KEY:-}" = "CHANGE_ME_GENERATE_WITH_COMMAND_ABOVE" ] && error "JWT_SECRET_KEY has not been changed from the template"
[ "${REDIS_PASSWORD:-}" = "CHANGE_ME_GENERATE_WITH_COMMAND_ABOVE" ] && error "REDIS_PASSWORD has not been changed from the template"
[ "${ENCRYPTION_KEY:-}" = "CHANGE_ME_GENERATE_WITH_COMMAND_ABOVE" ] && error "ENCRYPTION_KEY has not been changed from the template"
[ -z "${FLOWER_PASSWORD:-}" ] && error "FLOWER_PASSWORD is not set in .env (required for Flower dashboard auth)"
[ "${FLOWER_PASSWORD:-}" = "CHANGE_ME_USE_A_STRONG_PASSWORD" ] && error "FLOWER_PASSWORD has not been changed from the template"
[ -z "${LETSENCRYPT_EMAIL:-}" ] && error "LETSENCRYPT_EMAIL is not set in .env (required for SSL certificate)"
info "Environment variables validated."

# === Phase 4: Build & Deploy ===
info "=== Phase 4: Build & Deploy ==="

info "Creating required directories..."
mkdir -p data/canvas_downloads data/canvas_rag_uploads data/chroma \
         data/guide_images data/quiz data/rag_uploads data/user_workspaces \
         exports logs frontend/dist

info "Building frontend..."
$COMPOSE --profile build run --rm frontend-build

info "Building backend image..."
$COMPOSE build

# === Phase 5: SSL Setup (Two-step) ===
info "=== Phase 5: SSL Certificate ==="

# Step 1: Start with HTTP-only nginx for certbot validation
info "Starting HTTP-only nginx for certificate issuance..."
cp docker/nginx/nginx.dev.conf docker/nginx/nginx.conf.bak
cp docker/nginx/nginx.dev.conf docker/nginx/nginx.conf.tmp

# Temporarily use dev config for initial cert
ORIG_CONF="docker/nginx/nginx.conf"
cp "$ORIG_CONF" "${ORIG_CONF}.https"
cp docker/nginx/nginx.dev.conf "$ORIG_CONF"

info "Starting all services (HTTP mode)..."
$COMPOSE up -d

info "Waiting for services to stabilize..."
sleep 20

info "Requesting SSL certificate from Let's Encrypt..."
$COMPOSE --profile ssl run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d "$PRODUCTION_DOMAIN" \
    --agree-tos \
    -m "${LETSENCRYPT_EMAIL}" \
    --non-interactive

# Step 2: Restore HTTPS config and restart
info "Switching to HTTPS nginx configuration..."
cp "${ORIG_CONF}.https" "$ORIG_CONF"
rm -f "${ORIG_CONF}.https" docker/nginx/nginx.conf.bak docker/nginx/nginx.conf.tmp

$COMPOSE restart nginx

info "Waiting for HTTPS..."
sleep 10

# === Phase 6: Verify ===
info "=== Phase 6: Verification ==="

$COMPOSE ps
echo ""
info "Testing health endpoint..."
if curl -sf "https://${PRODUCTION_DOMAIN}/health" > /dev/null 2>&1; then
    info "✓ HTTPS health check passed!"
elif curl -sf "http://${PRODUCTION_DOMAIN}/health" > /dev/null 2>&1; then
    warn "HTTP works but HTTPS may need a moment. Check: https://${PRODUCTION_DOMAIN}"
else
    warn "Health check did not respond yet. Services may still be starting."
    warn "Check logs: $COMPOSE logs backend"
fi

# === Phase 7: Cron Jobs ===
info "=== Phase 7: Setting Up Maintenance ==="

# Auto-renew SSL (twice daily)
CRON_SSL="0 3,15 * * * cd $REPO_DIR && $COMPOSE --profile ssl run --rm certbot renew --quiet && $COMPOSE restart nginx"
(crontab -l 2>/dev/null | grep -v certbot; echo "$CRON_SSL") | crontab -

# Daily backup — PostgreSQL
CRON_BACKUP="0 2 * * * cd $REPO_DIR && docker compose exec -T postgres pg_dump -U \${POSTGRES_USER} \${POSTGRES_DB} | gzip > /root/backups/grader_\$(date +\\%Y\\%m\\%d).sql.gz"
mkdir -p /root/backups
(crontab -l 2>/dev/null | grep -v pg_dump; echo "$CRON_BACKUP") | crontab -

# Weekly backup — data/ and exports/ (uploaded files, ChromaDB, workspaces)
CRON_DATA="0 3 * * 0 tar czf /root/backups/grader_data_\$(date +\\%Y\\%m\\%d).tar.gz -C $REPO_DIR data/ exports/ 2>/dev/null || true"
(crontab -l 2>/dev/null | grep -v grader_data; echo "$CRON_DATA") | crontab -

info "Cron jobs installed: SSL renewal + daily DB backup + weekly data/exports backup."
warn "Note: DB backup covers PostgreSQL only. data/ (uploads, ChromaDB, workspaces) and exports/ are backed up weekly (Sunday 3AM)."

# ─────────────────────────────────────────────────────────────────────────────
echo ""
info "================================================================"
info "  Deployment complete!"
info "  URL:     https://${PRODUCTION_DOMAIN}"
info "  Flower:  ssh -L 5555:localhost:5555 root@VPS, then http://localhost:5555"
info "================================================================"
info ""
info "  Useful commands:"
info "    Logs:     cd $REPO_DIR && $COMPOSE logs -f backend"
info "    Status:   cd $REPO_DIR && $COMPOSE ps"
info "    Update:   cd $REPO_DIR && bash deploy.sh update"
info "    Restart:  cd $REPO_DIR && $COMPOSE restart"
info "    Backup:   ls /root/backups/"
info "    Restore DB:    cd $REPO_DIR && bash deploy.sh restore /root/backups/<file>.sql.gz"
    info "    Restore data:  cd $REPO_DIR && bash deploy.sh restore /root/backups/<file>.tar.gz"
info "================================================================"
