#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .local/provisioning/device/identity.json ]] || { echo 'Prepare private provisioning first.' >&2; exit 1; }
action=${1:-build}
[[ $action == build || $action == rootfs ]] || { echo 'Usage: build-image.sh [build|rootfs]' >&2; exit 2; }
if [[ $action == build ]]; then
    [[ -f .local/build/kernel/arch/arm/boot/zImage ]] || { echo 'Build the kernel first.' >&2; exit 1; }
    python3 tools/kernel-artifacts.py check
fi
readarray -t locked < <(python3 - <<'PY'
import json
p=json.load(open('build/sources.lock.json'))
for value in (p['builder']['image'],p['debian']['snapshot'],p['debian']['security_snapshot']): print(value)
PY
)
cache_name=
cache_sha=
ignore_cache=yes
if [[ $action == build ]] && cache_info=$(python3 tools/rootfs-cache.py check); then
    readarray -t cached <<< "$cache_info"
    cache_name=${cached[0]}
    cache_sha=${cached[1]}
    ignore_cache=no
fi
# Only the container gets privileges to create/mount loop devices for image files.
# The wrapper never selects or writes a physical card.
docker run --rm --privileged --entrypoint bash \
    -v "$PWD:/project" -v "$PWD/.local/sources/armbian:/armbian" \
    -e NEO_DEBIAN_SNAPSHOT="${locked[1]}" -e NEO_SECURITY_SNAPSHOT="${locked[2]}" \
    -e ZSTD_NBTHREADS=1 -e NEO_BUILD_ACTION="$action" -e NEO_IGNORE_CACHE="$ignore_cache" \
    -e NEO_ROOTFS_CACHE_NAME="$cache_name" -e NEO_ROOTFS_CACHE_SHA="$cache_sha" "${locked[0]}" -c '
    set -euo pipefail
    # Debian 13 ships systemd binfmt entries, not update-binfmts database files.
    if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
        mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc
    fi
    if [[ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]]; then
        cat /usr/lib/binfmt.d/qemu-arm.conf > /proc/sys/fs/binfmt_misc/register
        trap '\''printf -- "-1" > /proc/sys/fs/binfmt_misc/qemu-arm'\'' EXIT
    fi
    arch-test armhf
    for archive in debian debian-security; do
        gpg --batch --no-default-keyring --keyring /usr/share/keyrings/debian-archive-keyring.gpg \
            --verify "/project/.local/inputs/$archive.InRelease"
    done
    # Host helper dependencies come from the same signed snapshots as the target.
    python3 /project/tools/image.py apt-sources /
    git config --global --add safe.directory /armbian
    cd /armbian
    ./compile.sh "$NEO_BUILD_ACTION" BOARD=gameshellneo-cpi31 BRANCH=current RELEASE=trixie \
        BUILD_MINIMAL=yes BUILD_DESKTOP=no KERNEL_CONFIGURE=no ENABLE_EXTENSIONS=gameshellneo \
        NETWORKING_STACK=none BOOTCONFIG=none KERNELSOURCE=none EXTRAWIFI=no \
        CONSOLE_AUTOLOGIN=no \
        KEEP_ORIGINAL_OS_RELEASE=yes \
        INSTALL_ARMBIAN_FIRMWARE=no SKIP_ARMBIAN_REPO=yes ARTIFACT_IGNORE_CACHE="$NEO_IGNORE_CACHE" \
        NEO_LOCAL_CACHE_ONLY=yes NEO_ROOTFS_CACHE_NAME="$NEO_ROOTFS_CACHE_NAME" NEO_ROOTFS_CACHE_SHA="$NEO_ROOTFS_CACHE_SHA" \
        USE_TMPFS=no CPUTHREADS=1 KERNEL_BTF=no MANAGE_ACNG=no COMPRESS_OUTPUTIMAGE=sha \
        IMAGE_PARTITION_TABLE=msdos OFFSET=16 BOOTSIZE=128 BOOTFS_TYPE=fat ROOTFS_TYPE=ext4 \
        FIXED_IMAGE_SIZE=4096 ROOTFS_COMPRESSION_RATIO=1 VENDOR=GameShellNeo \
        REVISION=0.1.0 NEO_DEBIAN_SNAPSHOT="$NEO_DEBIAN_SNAPSHOT" \
        NEO_SECURITY_SNAPSHOT="$NEO_SECURITY_SNAPSHOT"
    '
python3 tools/rootfs-cache.py record
if [[ $action == build ]]; then
    python3 tools/bundle-image.py --latest
fi
