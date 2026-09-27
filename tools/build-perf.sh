#!/bin/bash
# Optional diagnostic tool; does not change the kernel or assembled image.
set -euo pipefail
cd "$(dirname "$0")/.."
readarray -t locked < <(python3 - <<'PY'
import json
p=json.load(open('build/sources.lock.json'))
for value in (p['linux']['tag'][1:],p['linux']['tarball_sha256'],p['builder']['image'],p['builder']['platform'],p['builder']['cross_compile']):
    print(value)
PY
)
version=${locked[0]}
source="$PWD/.local/sources/linux-$version"
archive="$PWD/.local/downloads/linux-$version.tar.xz"
[[ -f $source/tools/perf/Makefile && -f $archive ]] || {
    echo 'Prepare the locked Linux source with task build:kernel first.' >&2
    exit 1
}
printf '%s  %s\n' "${locked[1]}" "$archive" | sha256sum -c -
mkdir -p .local/build/perf
docker run --rm --user "$(id -u):$(id -g)" --platform "${locked[3]}" \
    --entrypoint bash -v "$PWD:/project" -e NEO_PERF_VERSION="$version" \
    -e NEO_PERF_CROSS="${locked[4]}" "${locked[2]}" -c '
    set -euo pipefail
    make -C "/project/.local/sources/linux-$NEO_PERF_VERSION/tools/perf" \
        O=/project/.local/build/perf/ ARCH=arm CROSS_COMPILE="$NEO_PERF_CROSS" -j1 \
        NO_LIBELF=1 NO_LIBDW=1 NO_LIBUNWIND=1 NO_LIBPYTHON=1 NO_LIBPERL=1 \
        NO_SLANG=1 NO_DEMANGLE=1 NO_LIBNUMA=1 NO_LIBTRACEEVENT=1 NO_LIBBPF=1 \
        NO_LIBBABELTRACE=1 NO_LIBZSTD=1 NO_LIBPFM4=1 NO_LIBDEBUGINFOD=1 \
        NO_CAPSTONE=1 NO_ZLIB=1 NO_LZMA=1 NO_AUXTRACE=1 NO_JVMTI=1 \
        NO_JEVENTS=1 NO_BACKTRACE=1 NO_SDT=1 BUILD_BPF_SKEL=0 perf
    "${NEO_PERF_CROSS}readelf" -h -d /project/.local/build/perf/perf \
        > /project/.local/build/perf/elf-info.txt
    "${NEO_PERF_CROSS}gcc" --version > /project/.local/build/perf/compiler.txt
    '
sha256sum .local/build/perf/perf > .local/build/perf/perf.sha256
echo 'Built optional ARM perf tool at .local/build/perf/perf; not installed on the device.'
