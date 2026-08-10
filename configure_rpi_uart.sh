#!/bin/bash
set -euo pipefail

cmdline_file=/boot/firmware/cmdline.txt
config_file=/boot/firmware/config.txt

if [[ ! -f "$cmdline_file" || ! -f "$config_file" ]]; then
    echo "Expected Raspberry Pi boot configuration files were not found" >&2
    exit 1
fi

if [[ ! -f "${cmdline_file}.codex-before-uart" ]]; then
    cp -a "$cmdline_file" "${cmdline_file}.codex-before-uart"
fi
if [[ ! -f "${config_file}.codex-before-uart" ]]; then
    cp -a "$config_file" "${config_file}.codex-before-uart"
fi

/usr/bin/raspi-config nonint do_serial_hw 0

sed -i -E \
    -e 's/(^| )console=(serial0|ttyAMA0|ttyS0),[0-9]+( |$)/ /g' \
    -e 's/  +/ /g' \
    -e 's/^ //' \
    -e 's/ $//' \
    "$cmdline_file"

systemctl disable --now serial-getty@serial0.service 2>/dev/null || true
systemctl disable --now serial-getty@ttyS0.service 2>/dev/null || true

echo "UART hardware enabled and serial console disabled."
grep -o 'console=[^ ]*' "$cmdline_file" || true
grep -h '^enable_uart=' "$config_file" || true
