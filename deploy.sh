#!/usr/bin/env bash
# =============================================================================
# Grader - VPS Deployment Script (Hetzner / GCP Compute Engine / Ubuntu 24.04)
# =============================================================================
# Usage:
#   First deploy:   bash deploy.sh
#   Update deploy:  bash deploy.sh update
#   Restore backup: bash deploy.sh restore <backup-file>
# =============================================================================

set -euo pipefail

REPO_DIR="/root/grader"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.prod.yml)
APP_UID=10001
APP_GID=10001

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

compose() {
    docker compose "${COMPOSE_FILES[@]}" "$@"
}

PROVIDER="${DEPLOY_PROVIDER:-auto}"
if [ "$PROVIDER" = "auto" ]; then
    if curl -sf -m 2 -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/ > /dev/null 2>&1; then
        PROVIDER="gcp"
    else
        PROVIDER="hetzner"
    fi
fi
info "Provider detected: $PROVIDER"

require_real_value() {
    local var_name="$1"
    local value="${!var_name:-}"
    if [ -z "$value" ]; then
        error "$var_name is not set in .env"
    fi

    case "$value" in
        CHANGE_ME_GENERATE_WITH_COMMAND_ABOVE|CHANGE_ME_USE_A_STRONG_PASSWORD|gsk_XXXXXXXXXXXXXXXXXXXXXXXXX|your-email@example.com|grader.yourdomain.com)
            error "$var_name still contains a template placeholder"
            ;;
    esac
}

validate_domain() {
    case "${PRODUCTION_DOMAIN:-}" in
        ""|grader.yourdomain.com|yourdomain.com|example.com|*.example.com|localhost)
            error "PRODUCTION_DOMAIN must be set to the real production domain"
            ;;
    esac
}

validate_cors_origins() {
    local expected_origin="https://${PRODUCTION_DOMAIN}"
    if [[ "${CORS_ORIGINS:-}" != *"${expected_origin}"* ]]; then
        error "CORS_ORIGINS must include ${expected_origin}"
    fi
}

validate_environment() {
    source .env

    validate_domain
    require_real_value LETSENCRYPT_EMAIL
    require_real_value GROQ_API_KEY
    require_real_value POSTGRES_PASSWORD
    require_real_value REDIS_PASSWORD
    require_real_value JWT_SECRET_KEY
    require_real_value JWT_REFRESH_SECRET_KEY
    require_real_value ENCRYPTION_KEY
    require_real_value SIGNUP_INVITE_CODE
    require_real_value INVITE_SECRET
    require_real_value FLOWER_PASSWORD
    validate_cors_origins

    info "Environment variables validated."
}

ensure_runtime_directories() {
    mkdir -p \
        data/canvas_downloads \
        data/canvas_rag_uploads \
        data/chroma \
        data/guide_images \
        data/quiz \
        data/rag_uploads \
        data/user_workspaces \
        exports \
        logs \
        frontend/dist
}

ensure_runtime_permissions() {
    ensure_runtime_directories
    chown -R "${APP_UID}:${APP_GID}" data exports logs frontend/dist
}

assert_internal_ports_are_not_published() {
    local rendered
    rendered="$(compose config)"
    if grep -Eq 'published: "?(5432|6379|5555)"?' <<<"$rendered"; then
        error "Merged production compose still publishes an internal port. Check docker-compose files."
    fi
    info "Production compose exposes only the intended public ports."
}

wait_for_container_health() {
    local container_name="$1"
    local timeout_seconds="${2:-180}"
    local start_ts
    start_ts="$(date +%s)"

    info "Waiting for ${container_name} to become healthy..."
    while true; do
        local status
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)"
        if [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
            return 0
        fi
        if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
            compose logs --tail=200
            error "Container ${container_name} stopped before becoming healthy"
        fi
        if [ $(( "$(date +%s)" - start_ts )) -ge "$timeout_seconds" ]; then
            compose logs --tail=200
            error "Timed out waiting for ${container_name}"
        fi
        sleep 5
    done
}

build_frontend() {
    info "Building frontend..."
    compose --profile build run --rm frontend-build
}

build_images() {
    info "Building backend and worker images..."
    compose build
}

start_infra() {
    info "Starting infrastructure services..."
    compose up -d postgres redis
    wait_for_container_health grader_postgres 180
    wait_for_container_health grader_redis 120
}

run_migrations() {
    info "Running database migrations..."
    compose run --rm backend alembic upgrade head
}

start_application_stack() {
    info "Starting backend and workers..."
    compose up -d backend worker-doc worker-canvas
    wait_for_container_health grader_backend 180
}

start_nginx() {
    info "Starting nginx..."
    compose up -d nginx
    wait_for_container_health grader_nginx 120
}

backup_nginx_template() {
    cp docker/nginx/nginx.conf docker/nginx/nginx.conf.deploy-backup
}

restore_nginx_template() {
    if [ -f docker/nginx/nginx.conf.deploy-backup ]; then
        mv docker/nginx/nginx.conf.deploy-backup docker/nginx/nginx.conf
    fi
}

switch_nginx_to_http_template() {
    backup_nginx_template
    cp docker/nginx/nginx.dev.conf docker/nginx/nginx.conf
}

request_ssl_certificate() {
    info "Requesting SSL certificate from Let's Encrypt..."
    compose --profile ssl run --rm certbot certonly \
        --webroot -w /var/www/certbot \
        -d "$PRODUCTION_DOMAIN" \
        --agree-tos \
        -m "${LETSENCRYPT_EMAIL}" \
        --non-interactive
}

install_maintenance_cron() {
    info "=== Phase 7: Setting Up Maintenance ==="

    mkdir -p /root/backups

    local cron_ssl
    local cron_backup
    local cron_data

    cron_ssl="0 3,15 * * * cd $REPO_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile ssl run --rm certbot renew --quiet && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx"
    cron_backup="0 2 * * * cd $REPO_DIR && bash ./docker/backup_postgres.sh"
    cron_data="0 3 * * 0 tar czf /root/backups/grader_data_\$(date +\\%Y\\%m\\%d).tar.gz -C $REPO_DIR data/ exports/ 2>/dev/null || true"

    (crontab -l 2>/dev/null | grep -v certbot; echo "$cron_ssl") | crontab -
    (crontab -l 2>/dev/null | grep -v backup_postgres.sh; echo "$cron_backup") | crontab -
    (crontab -l 2>/dev/null | grep -v grader_data; echo "$cron_data") | crontab -

    info "Cron jobs installed: SSL renewal + daily DB backup + weekly data/exports backup."
    warn "DB backup covers PostgreSQL only. data/ and exports/ are backed up weekly."
    warn "DB backup logs are written to /root/backups/grader_db_backup.log"
}

verify_deployment() {
    info "=== Phase 6: Verification ==="
    compose ps
    echo ""
    info "Testing health endpoint..."
    if curl -sf "https://${PRODUCTION_DOMAIN}/health" > /dev/null 2>&1; then
        info "HTTPS health check passed."
    elif curl -sf "http://${PRODUCTION_DOMAIN}/health" > /dev/null 2>&1; then
        warn "HTTP works but HTTPS may need a moment. Check https://${PRODUCTION_DOMAIN}"
    else
        warn "Health check did not respond yet. Services may still be starting."
        warn "Check logs with: cd $REPO_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs backend"
    fi
}

run_deploy_sequence() {
    assert_internal_ports_are_not_published
    ensure_runtime_directories
    build_frontend
    ensure_runtime_permissions
    build_images
    start_infra
    run_migrations
    start_application_stack
}

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
        source .env
        warn "This will REPLACE the current database with: $BACKUP_FILE"
        warn "Note: This restores PostgreSQL only. To also restore files, run again with a .tar.gz backup."
        read -rp "Type 'yes' to confirm: " CONFIRM
        [ "$CONFIRM" != "yes" ] && error "Aborted."
        info "Restoring database..."
        gunzip < "$BACKUP_FILE" | compose exec -T postgres psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --quiet
        info "Database restored from $BACKUP_FILE"
    elif [[ "$BACKUP_FILE" == *.tar.gz ]]; then
        warn "This will OVERWRITE data/ and exports/ with: $BACKUP_FILE"
        warn "Note: This restores files only. To also restore the database, run again with a .sql.gz backup."
        read -rp "Type 'yes' to confirm: " CONFIRM
        [ "$CONFIRM" != "yes" ] && error "Aborted."
        info "Restoring data and exports..."
        tar xzf "$BACKUP_FILE" -C "$REPO_DIR"
        ensure_runtime_permissions
        info "Data/exports restored from $BACKUP_FILE"
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

    validate_environment
    run_deploy_sequence
    start_nginx
    compose restart nginx
    wait_for_container_health grader_nginx 120
    compose ps

    info "=== Update complete ==="
    exit 0
fi

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

docker version >/dev/null 2>&1 || error "Docker is not working"
docker compose version >/dev/null 2>&1 || error "Docker Compose is not working"
info "Docker verified: $(docker --version)"

if [ "$PROVIDER" = "hetzner" ]; then
    info "Configuring firewall (UFW)..."
    ufw allow OpenSSH
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
    info "Firewall configured: SSH + HTTP + HTTPS only."
else
    info "GCP: Firewall managed via VPC firewall rules (skipping UFW)."
    info "Ensure GCP firewall allows TCP 22, 80, 443 for this VM."
fi

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

if ! command -v fail2ban-client &> /dev/null; then
    info "Installing fail2ban..."
    apt-get install -y fail2ban
    systemctl enable fail2ban
    systemctl start fail2ban
fi

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

info "=== Cloning Repository ==="
if [ ! -d "$REPO_DIR" ]; then
    read -rp "Enter your Git repository URL: " GIT_URL
    git clone "$GIT_URL" "$REPO_DIR"
else
    warn "Repository already exists at $REPO_DIR, pulling latest..."
    cd "$REPO_DIR" && git pull origin main
fi
cd "$REPO_DIR"

info "=== Phase 3: Environment Configuration ==="
if [ ! -f .env ]; then
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
        warn "Copied $ENV_SOURCE -> .env"
        warn "Edit .env now with freshly rotated production secrets before continuing."
        warn "Run: nano .env"
        read -rp "Press Enter after editing .env to continue... " _
    else
        warn ".env.production not found in project, $SCRIPT_DIR, or /root/"
        read -rp "Path to .env.production (or Enter to abort): " ENV_PATH
        if [ -n "$ENV_PATH" ] && [ -f "$ENV_PATH" ]; then
            cp "$ENV_PATH" .env
            warn "Copied $ENV_PATH -> .env"
            warn "Edit .env now with freshly rotated production secrets before continuing."
            read -rp "Press Enter after editing .env to continue... " _
        else
            error "No .env file found. Upload a production env file to the server first."
        fi
    fi
else
    info ".env already exists."
fi

validate_environment

info "=== Phase 4: Build & Deploy ==="
run_deploy_sequence

info "=== Phase 5: SSL Certificate ==="
switch_nginx_to_http_template
trap restore_nginx_template EXIT

start_nginx
request_ssl_certificate
restore_nginx_template
trap - EXIT

info "Restarting nginx with HTTPS configuration..."
compose restart nginx
wait_for_container_health grader_nginx 120

verify_deployment
install_maintenance_cron

echo ""
info "================================================================"
info "  Deployment complete!"
info "  Provider: $PROVIDER"
info "  URL:      https://${PRODUCTION_DOMAIN}"
info "  Flower:   ssh -L 5555:localhost:5555 root@SERVER, then http://localhost:5555"
info "================================================================"
info ""
info "  Useful commands:"
info "    Logs:     cd $REPO_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend"
info "    Status:   cd $REPO_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"
info "    Update:   cd $REPO_DIR && bash deploy.sh update"
info "    Restart:  cd $REPO_DIR && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart"
info "    Backup:   ls /root/backups/"
info "    Restore DB:    cd $REPO_DIR && bash deploy.sh restore /root/backups/<file>.sql.gz"
info "    Restore data:  cd $REPO_DIR && bash deploy.sh restore /root/backups/<file>.tar.gz"
info "================================================================"
