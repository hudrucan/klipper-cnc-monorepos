#!/bin/bash

set -e

SCRIPTPATH=$(dirname -- "$(readlink -f -- "$0")")
KSPATH=$(dirname "$SCRIPTPATH")
KSENV="${KLIPPERSCREEN_VENV:-${HOME}/.klipper-screen-env}"
SERVICE="${KLIPPERSCREEN_SERVICE:-klipper-screen.service}"

echo "Updating Klipper Screen CNC dependencies"

if [ ! -d "$KSENV" ]; then
    echo "Virtual environment not found at ${KSENV}; creating it"
    python3 -m venv "$KSENV"
fi

. "${KSENV}/bin/activate"

if [[ "$(uname -m)" =~ armv[67]l ]]; then
    pip --disable-pip-version-check install \
        --extra-index-url https://www.piwheels.org/simple \
        -r "${KSPATH}/scripts/KlipperScreen-requirements.txt" \
        --prefer-binary
else
    pip --disable-pip-version-check install \
        -r "${KSPATH}/scripts/KlipperScreen-requirements.txt" \
        --prefer-binary
fi

deactivate

if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl daemon-reload
    sudo systemctl restart "$SERVICE"
fi

echo "Klipper Screen CNC update complete"
