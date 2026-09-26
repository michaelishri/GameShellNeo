#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
checker=$(command -v shellcheck || true)
if [[ -z $checker ]]; then
    checker=.local/sources/armbian/cache/tools/shellcheck/shellcheck-v0.11.0.linux.x86_64
fi
[[ -x $checker ]] || { echo 'Install ShellCheck or prepare the Armbian tool cache.' >&2; exit 1; }
scripts=(tools/*.sh runtime/usr/local/sbin/gameshellneo-usb runtime/usr/local/sbin/gameshellneo-collect)
for script in "${scripts[@]}"; do bash -n "$script"; done
"$checker" "${scripts[@]}"
echo 'Bash syntax and ShellCheck passed.'
