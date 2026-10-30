#!/bin/bash
set -euo pipefail

# Render the realm template, then start Keycloak.
# Pure bash substitution, not envsubst (absent from this image) and not sed
# (mangles a `&` in a password).
: "${APP_PUBLIC_BASE_URL:?APP_PUBLIC_BASE_URL must be set (e.g. https://wba.example.com)}"
: "${KEYCLOAK_CLIENT_SECRET:?KEYCLOAK_CLIENT_SECRET must be set}"
: "${KEYCLOAK_SERVICE_CLIENT_SECRET:?KEYCLOAK_SERVICE_CLIENT_SECRET must be set}"
: "${DEV_ADMIN_PASSWORD:?DEV_ADMIN_PASSWORD must be set}"
: "${DEV_USER_PASSWORD:?DEV_USER_PASSWORD must be set}"

mkdir -p /opt/keycloak/data/import
rm -f /opt/keycloak/data/import/*.json

rendered=$(<"/opt/keycloak/realm-wba.json.template")
for name in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET \
            KEYCLOAK_SERVICE_CLIENT_SECRET DEV_ADMIN_PASSWORD DEV_USER_PASSWORD; do
  rendered=${rendered//"\${$name}"/"${!name}"}
done

# A surviving placeholder means a name above is misspelled; importing it would
# set a client secret to the literal string.
case "$rendered" in
  *'${'*) echo "FATAL: unsubstituted placeholder remains in realm template" >&2; exit 1 ;;
esac
printf '%s\n' "$rendered" > /opt/keycloak/data/import/realm-wba.json

exec /opt/keycloak/bin/kc.sh start-dev --import-realm --http-relative-path=/auth
