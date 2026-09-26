#!/bin/bash
# Explicit, optional host package installation; preserve an existing Docker install.
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    echo 'Host setup supports x86-64 Linux only.' >&2; exit 1;
}
# shellcheck source=/dev/null
source /etc/os-release
[[ $ID == debian || $ID == ubuntu ]] || {
    echo 'Automatic package installation supports Debian/Ubuntu; see README for manual prerequisites.' >&2
    exit 1
}
packages=(ca-certificates build-essential curl git python3 python3-paramiko openssh-client util-linux xz-utils tar shellcheck)
install_docker=no
if ! command -v docker >/dev/null; then
    packages+=(docker.io)
    install_docker=yes
fi
missing=()
for package in "${packages[@]}"; do
    if [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true) != installed ]]; then
        missing+=("$package")
    fi
done
if (( ${#missing[@]} == 0 )); then
    echo 'Host packages are already installed; existing Docker installation preserved.'
    exit 0
fi
admin=()
if (( EUID != 0 )); then admin=(sudo); fi
printf 'Installing missing host packages: %s\n' "${missing[*]}"
"${admin[@]}" apt-get update
"${admin[@]}" apt-get install --yes --no-install-recommends --no-upgrade "${missing[@]}"
if [[ $install_docker == yes && -d /run/systemd/system ]]; then
    "${admin[@]}" systemctl enable --now docker
fi
echo 'Host packages installed. Run task setup next; Docker account access may need a new login (see README).'
