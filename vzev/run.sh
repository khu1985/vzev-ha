#!/usr/bin/with-contenv bashio
# Startet die vZEV-App. Daten liegen im App-Konfigurationsordner (/config),
# damit sie im Home-Assistant-Backup enthalten sind.
export VZEV_DIR=/config
export EVCC_PASSWORD="$(bashio::config 'evcc_passwort')"
bashio::log.info "vZEV Abrechnung startet (Daten in ${VZEV_DIR})"
cd /app
exec python3 -u server.py
