#!/bin/sh
set -eu

project_dir=${1:-/home/pi/tennis}
venv_dir="$project_dir/.venv-gateway"

if [ ! -x "$venv_dir/bin/python" ]; then
    echo "Gateway virtual environment not found: $venv_dir" >&2
    exit 1
fi

site_packages=$(
    "$venv_dir/bin/python" -c 'import site; print(site.getsitepackages()[0])'
)
user_site=$(python3 -c 'import site; print(site.getusersitepackages())')

printf '%s\n' \
    "$user_site" \
    '/usr/lib/python3/dist-packages' \
    > "$site_packages/tennis-system-packages.pth"

"$venv_dir/bin/python" -c \
    'import cv2, fastapi, numpy; from picamera2 import Picamera2; print("gateway imports ok")'
