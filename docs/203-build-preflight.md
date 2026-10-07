# Build inputs and disk headroom before compilation

8 October 2026, New Zealand; NEO-141. This unattended change addresses the late
build failures recorded in [report 188](188-historical-driver-source-compaction.md)
and [report 193](193-diagnostic22-adc-integration.md). A missing bootloader path
or insufficient image space should be discovered before spending time on a
kernel build. The installed diagnostic.23 and all device settings are unchanged.

## Workflow

`task build` now runs the full preflight and source/input preparation before
kernel regressions and compilation. Preparation still runs again before image
assembly, preserving its existing lock/hash checks. `task build:image` and
`task build:rootfs` preflight their inputs/space before preparation. The kernel
and image shell wrappers recheck storage at their own entry points, including
direct wrapper use. The full build explicitly selects full scope even if an
unrelated `SCOPE` variable was supplied.

The shared, read-only `tools/build_preflight.py` is exposed as:

```sh
task build:preflight \
  BOOTLOADER=/path/to/u-boot-sunxi-with-spl.bin \
  RADIO_DIR=/path/to/radio-reference
task build:preflight SCOPE=kernel
```

`SCOPE=image` checks image inputs/storage. `SCOPE=inputs` checks only inputs.
Kernel-only work does not require an unrelated bootloader or private radio
baseline. Full/image work requires the explicit selected input paths; it does
not substitute `.local/inputs` copies when those selections are missing.

The bootloader must be a regular file with the locked size and SHA-256. Local
radio inputs require the locked digest; public radio blobs use the same
digest-named cache and HTTPS rule as preparation. Existing cached data is
verified rather than trusted or replaced after a checksum failure. Uncached
public assets are reported as `download-required`; the preflight performs no
network access. Full-build preparation then downloads and verifies them before
compilation. It also checks the locked Armbian checkout and Debian metadata at
that earlier stage. A passing offline preflight alone is not proof that a
future download will succeed.

`prepare-build.py` performs the shared input validation before creating staging
directories, cloning or patching Armbian. Paths containing spaces remain data,
passed through environment/structured arguments. NVRAM contents, credentials
and firmware payloads are not printed; the JSON report contains paths, digests,
sizes, input status and filesystem capacity.

## Resource policy and limits

The pinned Armbian `lib/functions/host/prepare-host.sh` checks its output and
cache directories against 10 GiB. The new preflight retains that image
allowance and adds a **6 GiB kernel planning allowance** for source expansion,
downloads, output and module staging. The 6 GiB value is conservative planning,
not a measured maximum for every configuration or toolchain.

Paths resolve through existing symlinks to their actual storage. If a build
directory does not yet exist, its nearest existing ancestor supplies filesystem
identity and available space; the check creates nothing. On each filesystem,
kernel and image roles are counted once each, yielding 16 GiB for the usual
shared layout, 6 GiB for kernel-only storage or 10 GiB for image-only storage.
If one role spans multiple filesystems, each receives its full allowance rather
than assuming how future writes will be distributed. The least available-space
reading is retained when multiple paths report the same filesystem identity.

This is a snapshot, not a reservation. It cannot guarantee sufficient space
under concurrent writes, quotas, a changed configuration or larger outputs.
Docker's separate storage remains outside this check; `task setup`/`doctor`
still own builder preparation. Stage rechecks, Armbian's own check, kernel
artifact validation, signed snapshot checks and final image verification remain
in place. No retention cleanup, image deletion or weakened provenance check is
part of this change.

## Validation

Twelve focused tests cover absent explicit inputs despite staged copies,
checksum/size/nonregular-file rejection, corrupt public caches without fallback,
missing public downloads, no filesystem mutation, shared/split filesystem
headroom, boundary values, symlinked storage, preparation before any clone and
shell-wrapper early exits. A real Go Task dry run verifies full preflight and
preparation precede compilation even with `SCOPE=kernel` supplied to `build`.

The full host check passes 13 runtime and 668 tooling tests with one existing
opt-in skip, compiled checks and shell lint; the additional preparation-order
test then passes in the twelve-test focused run. No compilation, public download
or hardware action was needed for this validation.

The actual explicit-path preflight uses the original repository bootloader and
the private 27 September radio baseline. All four locked assets verify:
bootloader, cached firmware, private NVRAM and cached license. It observes
283.764 GiB available on the shared filesystem against the 16 GiB full-build
allowance. Private result: `.local/neo141-preflight.json`, SHA-256
`63cf2effd96d976191454473073c0a998235c5fb7be0d4cc342c92f0ab13ea25`.
No input, compiled artifact, recovery image or live-device setting was changed.
