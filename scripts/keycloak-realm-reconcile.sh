#!/usr/bin/env bash
# =============================================================================
# keycloak-realm-reconcile.sh — deliver realm changes to a RUNNING Keycloak
#
# `--import-realm` is create-only: it imports a realm that does not exist and
# skips one that already does. Editing `deploy/keycloak/realm-wba.json.template`
# therefore has no effect on a stack that is already running. This script is the
# delivery arm for those edits — it applies them to the live realm with
# `kcadm.sh`, without dropping the database, restarting Keycloak, or touching
# users, sessions, roles or any client other than the one being changed.
#
# `deploy/keycloak/realm-wba.json.template` is the source of truth. Every mapper
# applied here must match the template byte-for-byte in shape; if the two drift,
# the realm stops matching the code that defines it.
#
# Usage:
#   ./scripts/keycloak-realm-reconcile.sh
#
# Every reconcile block checks the running realm first and skips its write when
# the change is already present, so the script is safe to re-run.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

CONTAINER="wba-ai-keycloak"
KCADM="/opt/keycloak/bin/kcadm.sh"
KC_SERVER="http://localhost:8080/auth"
REALM="wba"
WEB_CLIENT_ID="wba-web"
WEB_MAPPER_NAME="wba-web-audience"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info()  { printf "${GREEN}✓${NC}  %s\n" "$*"; }
error() { printf "${RED}✗${NC}  %s\n" "$*" >&2; }

require_container_running() {
    local state
    state="$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true)"
    if [[ "$state" != "running" ]]; then
        error "Keycloak container ${CONTAINER} is not running (state: ${state:-absent})."
        error "Start it first: docker compose up -d keycloak"
        exit 1
    fi
}

require_admin_password() {
    if [[ ! -f "$ENV_FILE" ]]; then
        error "No .env file at ${ENV_FILE}."
        exit 1
    fi
    # Read straight into KC_CLI_PASSWORD — the exact variable kcadm.sh consumes
    # (see authenticate()). Reading it into an intermediate name and re-exporting
    # would work too, but it copies the secret into a second process variable for
    # no gain. The `.env` name is referenced only to find the line.
    KC_CLI_PASSWORD="$(sed -n 's|^DEV_KEYCLOAK_ADMIN_PASSWORD=||p' "$ENV_FILE" | head -n 1)"
    if [[ -z "$KC_CLI_PASSWORD" ]]; then
        error "DEV_KEYCLOAK_ADMIN_PASSWORD is not set in ${ENV_FILE}."
        exit 1
    fi
    # Exported so `docker exec -e KC_CLI_PASSWORD` (bare, no `=value`) can
    # forward it from this shell's environment into the container.
    export KC_CLI_PASSWORD
}

authenticate() {
    # kcadm.sh has no `--password:env` flag (verified against Keycloak 26.8:
    # it rejects one with "Unknown options: '--password:env'"). What it does
    # support is the KC_CLI_PASSWORD environment variable, read when --password
    # is omitted — documented in `kcadm.sh config credentials --help`.
    #
    # `docker exec -e KC_CLI_PASSWORD` (bare, no `=value`) forwards the variable
    # from THIS shell's environment into the container, so the secret never
    # appears in argv and cannot leak through `ps` or the Docker event log.
    docker exec -e KC_CLI_PASSWORD "$CONTAINER" \
        "$KCADM" config credentials --server "$KC_SERVER" --realm master \
        --user admin >/dev/null
}

kcadm() {
    docker exec "$CONTAINER" "$KCADM" "$@"
}

reconcile_web_audience() {
    local client_id
    client_id="$(kcadm get clients -r "$REALM" -q clientId="$WEB_CLIENT_ID" --fields id --format csv --noquotes)"
    if [[ -z "$client_id" ]]; then
        error "Client ${WEB_CLIENT_ID} not found in realm ${REALM}."
        exit 1
    fi

    local mappers
    mappers="$(kcadm get "clients/${client_id}/protocol-mappers/models" -r "$REALM" --fields name --format csv --noquotes)"
    if grep -qx "$WEB_MAPPER_NAME" <<<"$mappers"; then
        info "wba-web audience mapper already present — nothing to do"
        return 0
    fi

    kcadm update "clients/${client_id}" -r "$REALM" \
        -s 'protocolMappers=[{"name":"wba-web-audience","protocol":"openid-connect","protocolMapper":"oidc-audience-mapper","consentRequired":false,"config":{"included.client.audience":"wba-web","id.token.claim":"false","access.token.claim":"true"}}]' >/dev/null

    info "Added ${WEB_MAPPER_NAME} to client ${WEB_CLIENT_ID}"
}

require_container_running
require_admin_password
authenticate

reconcile_web_audience
