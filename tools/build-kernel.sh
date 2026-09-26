#!/bin/bash
# Run on the Intel Docker host. All build products remain under ignored .local.
set -euo pipefail
cd "$(dirname "$0")/.."
readarray -t locked < <(python3 - <<'PY'
import json
p=json.load(open('build/sources.lock.json'))
for value in (p['linux']['tag'][1:],p['linux']['tarball_url'],p['linux']['tarball_sha256'],p['builder']['image']):
    print(value)
PY
)
version=${locked[0]}
archive="$PWD/.local/downloads/linux-$version.tar.xz"
source="$PWD/.local/sources/linux-$version"
mkdir -p .local/downloads .local/sources .local/build/kernel .local/kernel-install
if [[ ! -f $archive ]]; then
    curl -fL --retry 3 "${locked[1]}" -o "$archive.part"
    mv "$archive.part" "$archive"
fi
printf '%s  %s\n' "${locked[2]}" "$archive" | sha256sum -c -
if [[ ! -d $source ]]; then tar -xJf "$archive" -C .local/sources; fi
python3 tools/kernel-inputs.py --apply "$source"
docker run --rm --user "$(id -u):$(id -g)" --entrypoint bash -v "$PWD:/project" \
    -e KBUILD_BUILD_USER=gameshellneo -e KBUILD_BUILD_HOST=builder \
    "${locked[3]}" -c '
    set -euo pipefail
    cd /project/.local/sources/linux-'"$version"'
    export ARCH=arm CROSS_COMPILE=arm-linux-gnueabihf- LOCALVERSION=-gameshellneo1
    output=/project/.local/build/kernel
    make O="$output" sunxi_defconfig
    scripts/kconfig/merge_config.sh -m -O "$output" "$output/.config" /project/kernel/gameshellneo.config
    make O="$output" olddefconfig
    python3 /project/tools/check-kernel-config.py "$output/.config"
    make O="$output" -j1 zImage modules allwinner/sun8i-r16-clockworkpi-cpi3.dtb
    make O="$output" INSTALL_MOD_PATH=/project/.local/kernel-install modules_install
    arm-linux-gnueabihf-gcc --version > /project/.local/build/compiler.txt
    dpkg-query -W > /project/.local/build/builder-packages.txt
    make -s O="$output" kernelrelease > /project/.local/build/kernelrelease
    python3 /project/tools/kernel-artifacts.py record
    '
