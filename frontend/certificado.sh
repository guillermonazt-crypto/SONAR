#!/bin/sh
# Si no se montaron certificados reales en deploy/certs, genera uno
# autofirmado para que HTTPS funcione desde el primer arranque.
set -e
CERTS=/etc/nginx/certs
if [ ! -f "$CERTS/sonar.crt" ] || [ ! -f "$CERTS/sonar.key" ]; then
    mkdir -p "$CERTS"
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
        -subj "/CN=${SONAR_HOSTNAME:-sonar.local}" \
        -keyout "$CERTS/sonar.key" -out "$CERTS/sonar.crt"
    echo "SONAR: certificado autofirmado generado para ${SONAR_HOSTNAME:-sonar.local}"
fi
