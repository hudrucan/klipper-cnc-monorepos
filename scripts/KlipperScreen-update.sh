#!/bin/bash

set -e

SCRIPTPATH=$(dirname -- "$(readlink -f -- "$0")")
KSPATH=$(dirname "$SCRIPTPATH")
KSENV="${KLIPPERSCREEN_VENV:-${HOME}/.klipper-screen-env}"
KLIPPER_PATH="${KLIPPER_PATH:-${HOME}/klipper}"
INSTALL_KLIPPER_EXTRAS="${INSTALL_KLIPPER_EXTRAS:-1}"

if [ -n "$KLIPPERSCREEN_SERVICE" ]; then
    SERVICE="$KLIPPERSCREEN_SERVICE"
else
    SERVICE="klipper-screen.service"
    if command -v systemctl >/dev/null 2>&1 \
        && systemctl list-unit-files klipper-screen-cnc.service \
            | grep -q '^klipper-screen-cnc\.service'; then
        SERVICE="klipper-screen-cnc.service"
    fi
fi

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

install_klipper_extras()
{
    if [ "$INSTALL_KLIPPER_EXTRAS" = "0" ]; then
        echo "Skipping Klipper CNC extras install"
        return
    fi

    local extras_src="${KSPATH}/klipper-extras"
    local extras_dst="${KLIPPER_PATH}/klippy/extras"
    if [ ! -d "$extras_src" ]; then
        echo "Klipper CNC extras source not found at ${extras_src}"
        return
    fi
    if [ ! -d "$extras_dst" ]; then
        echo "Klipper source not found at ${KLIPPER_PATH}; skipping CNC extras"
        echo "Set KLIPPER_PATH=/path/to/klipper to install them automatically"
        return
    fi

    echo "Installing Klipper CNC extras to ${extras_dst}"
    cp "${extras_src}/work_coordinate_systems.py" "${extras_dst}/"
    cp "${extras_src}/touch_probe.py" "${extras_dst}/"
    cp "${extras_src}/tool_setter.py" "${extras_dst}/"

    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl restart klipper || true
    fi
}

install_klipper_extras

if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl daemon-reload
    sudo systemctl restart "$SERVICE"
fi

echo "Klipper Screen CNC update complete"
