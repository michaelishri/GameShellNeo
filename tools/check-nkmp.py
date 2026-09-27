#!/usr/bin/env python3
"""Compare the actual locked NKMP code before/after our patch, natively and on ARM32."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".local/build/nkmp-tests"
PATCH = ROOT / "kernel/patches/0005-sunxi-nkmp-exact-match.patch"
DRIVER = "drivers/clk/sunxi-ng/ccu_nkmp.c"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, **kwargs):
    result = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, **kwargs)
    print(result.stdout, end="", flush=True)
    result.check_returncode()
    return result.stdout


def split_source(source):
    prefix, rest = source.split("static unsigned long ccu_nkmp_calc_rate", 1)
    functions, suffix = rest.split("static void ccu_nkmp_disable", 1)
    return prefix, "static unsigned long ccu_nkmp_calc_rate" + functions, suffix


def instrument(functions, name):
    functions = functions.replace("ccu_nkmp_calc_rate", f"{name}_calc")
    functions = functions.replace("ccu_nkmp_find_best", f"{name}_find")
    marker = "\tu64 rate = parent;\n"
    if functions.count(marker) != 1:
        raise RuntimeError("Review changed calc function before instrumenting it")
    return functions.replace(marker, marker + f"\t{name}_calls++;\n")


def main():
    os.chdir(ROOT)
    lock = json.loads((ROOT / "build/sources.lock.json").read_text())
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "evidence.json").unlink(missing_ok=True)
    version = lock["linux"]["tag"].removeprefix("v")
    archive = ROOT / f".local/downloads/linux-{version}.tar.xz"
    expected = lock["linux"]["tarball_sha256"]
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix(".nkmp-download")
        try:
            with urllib.request.urlopen(lock["linux"]["tarball_url"], timeout=60) as src:
                with temporary.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            if sha256(temporary) != expected:
                raise RuntimeError("Downloaded Linux archive hash mismatch")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if sha256(archive) != expected:
        raise RuntimeError("Locked Linux archive hash mismatch")
    with tarfile.open(archive) as tar:
        def read(member):
            with tar.extractfile(f"linux-{version}/{member}") as stream:
                return stream.read().decode()
        original = read(DRIVER)
        a33 = read("drivers/clk/sunxi-ng/ccu-sun8i-a33.c")
        dts = read("arch/arm/boot/dts/allwinner/sun8i-a33.dtsi")

    # Fail on changed board inputs instead of silently assuming old factor limits.
    pll = a33.split("static struct ccu_nkmp pll_cpux_clk = {", 1)[1].split("\n};", 1)[0]
    for field, macro in {"n": "_SUNXI_CCU_MULT(8, 5)", "k": "_SUNXI_CCU_MULT(4, 2)",
                         "m": "_SUNXI_CCU_DIV(0, 2)", "p": "_SUNXI_CCU_DIV_MAX(16, 2, 4)"}.items():
        if not re.search(r"\." + field + r"\s*=\s*" + re.escape(macro) + ",", pll):
            raise RuntimeError(f"Review changed A33 {field} factor limits")
    cpu_table = dts.split("cpu0_opp_table: opp-table-cpu {", 1)[1].split("\n\tcpus {", 1)[0]
    opps = re.findall(r"opp-hz = /bits/ 64 <(\d+)>;", cpu_table)
    if not opps:
        raise RuntimeError("No locked A33 CPU operating points found")

    target = WORK / DRIVER
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(original)
    patch_log = run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)], cwd=WORK)
    patched = target.read_text()
    prefix, reference, suffix = split_source(original)
    new_prefix, candidate, new_suffix = split_source(patched)
    if prefix != new_prefix or suffix != new_suffix:
        raise RuntimeError("Patch modified code outside the extracted functions")
    structure = prefix[prefix.index("struct _ccu_nkmp {"):]
    generated = ("/* Generated from the hash-verified Linux archive; do not edit. */\n" +
                 structure + instrument(reference, "reference") +
                 instrument(candidate, "candidate") +
                 "static const unsigned long a33_opps[] = {" + ", ".join(opps) + "};\n")
    header = WORK / "nkmp_functions.h"
    header.write_text(generated)
    harness = ROOT / "kernel/tests/nkmp_test.c"
    flags = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror"]
    native_compiler = run(["cc", "--version"])
    run(["cc", *flags, "-I", str(WORK), str(harness), "-o", str(WORK / "native")])
    native = run([str(WORK / "native")])
    builder = lock["builder"]
    arm = run([
        "docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
        "--platform", builder["platform"], "--entrypoint", "bash",
        "-v", f"{ROOT}:/project", "-w", "/project",
        "-e", f"NEO_NKMP_CROSS={builder['cross_compile']}", builder["image"], "-c",
        'set -euo pipefail\n'
        '"${NEO_NKMP_CROSS}gcc" --version\n'
        '"${NEO_NKMP_CROSS}gcc" -std=c11 -O2 -Wall -Wextra -Werror '
        '-I.local/build/nkmp-tests kernel/tests/nkmp_test.c -o .local/build/nkmp-tests/arm32\n'
        'qemu-arm -L /usr/arm-linux-gnueabihf .local/build/nkmp-tests/arm32\n'
    ])
    for name, content in {"patch.txt": patch_log, "native.txt": native_compiler + native,
                          "arm32.txt": arm}.items():
        (WORK / name).write_text(content)
    evidence = {
        "linux_tag": lock["linux"]["tag"], "archive_sha256": expected,
        "builder": builder, "a33_opps_hz": list(map(int, opps)),
        "sha256": {str(p.relative_to(ROOT)): sha256(p)
                   for p in (PATCH, harness, header, Path(__file__).resolve())},
        "result": "native and ARM32 equivalence passed",
        "limits": "Arithmetic/selection tests with a do_div quotient shim, not hardware or timing tests",
    }
    (WORK / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print("NKMP evidence saved in .local/build/nkmp-tests/", flush=True)


if __name__ == "__main__":
    main()
