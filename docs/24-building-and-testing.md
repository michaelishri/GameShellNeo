# Building the diagnostic image

This is the CPI v3.1 development workflow. Hardware acceptance remains NEO-5;
successful compilation and filesystem checks cannot establish boot, charging,
display or sleep behavior. Preserve the original card.

The [README task workflow](../README.md#shared-task-commands) is the shared
entry point for routine work. The commands below use that Taskfile; `tools/`
contains the underlying implementation.

## Build stages

Use the Intel Linux host with Go Task v3, Docker, Bash, Python 3.11+, Git, curl, tar and a C
compiler. The wrappers obtain the builder by the digest in
[`sources.lock.json`](../build/sources.lock.json). Compilation uses one job and
disk-backed storage. The kernel and Armbian image stages are separate: kernel
changes require compilation, while runtime/image changes reuse verified kernel
artifacts. Armbian's project family does not inherit the broad sunxi patch queue
or runtime tuning. `KERNELSOURCE=none` is intentional in the image stage.

All commands below run from the GameShellNeo directory. Keep `.local/` private.
The original sibling repositories are reference inputs and are never modified.

Run `task setup` first to pull and smoke-test the Docker image pinned in the
lock file. On a new Debian/Ubuntu host, `task setup:host` installs missing host
packages; configure Docker account access before running setup. Neither command
replaces existing `.env` contents. The [README](../README.md#prerequisites)
covers prerequisites, logs and repeat runs.

1. Supply the exact bootloader and owner's radio files from the recorded
   baseline. Paths are arguments, not hard-coded machine dependencies:

   ```sh
   task prepare
   ```

2. Prepare private access using `GAMESHELL_WIFI_SSID` and
   `GAMESHELL_WIFI_PSK` in the ignored `.env`. The helper writes no credentials
   to stdout. Never pass passwords in command lines. Direct Wicd import remains
   available in `tools/provision.py` for legacy migration.

   ```sh
   task provision
   ```

   The device directory contains a new SSH host key, its fingerprint record,
   Wi-Fi configuration and stable machine ID. Reusing it is appropriate for
   repeated images of this one board. Use a distinct directory/identity for
   another device. These identities differ from the original installation.

3. Build and record the kernel stage:

   ```sh
   task build:kernel
   task check:dt
   ```

   The helper verifies the Linux archive and applies only the project's patch
   queue. If patches change, run `task kernel:reset` to archive the previous
   scratch source/output before rebuilding; the builder rejects
   an already patched tree with a different patch manifest. The resolved config
   is asserted before compiling. The completed-stage manifest binds patch and
   configuration inputs to the installed modules, kernel and DTB.

4. Build the image:

   ```sh
   task build:image
   ```

   The container uses privileges for ARM emulation and loop devices backed by
   image files. It never selects a physical disk. A temporary ARM binfmt entry
   is removed on normal exit if the wrapper created it. An interrupted/killed
   container may require checking that entry before retrying. Debian snapshot
   metadata must match locked hashes and verify against the pinned builder's
   Debian keyring. Expiry exceptions apply to dated snapshots only. Rootfs
   caches are reused only when their recorded local content hash and project
   inputs match. Published remote cache images are disabled. A missing or stale
   ledger forces a fresh rootfs build.

   `task build:rootfs` exercises the userspace bootstrap separately.
   Assembly first writes `.local/sources/armbian/output/images/`. The wrapper
   then runs offline filesystem/content verification and collects a private
   image, checksums, manifests, logs and package inventory in `.local/artifacts/`. The image
   contains private credentials and firmware; it is not a public release.

## Checks

```sh
task check
task check:kernel
task check:dt
task image:verify
```

`task check:dt` uses the pinned builder's bundled dtschema 2026.9
against the patched kernel bindings and records the validator package versions.
It validates the modified bindings, processes the full schema set and checks
the project DTB. Emitted diagnostics fail the check even if the validator exits
zero. The build report records actual checks and any remaining caveats.

## First hardware session

Before writing a card, identify the spare and reader, and make an offline,
verified backup of the original. Do not infer a disk path. Flash only the spare,
then attempt first boot on the owner's CPI v3.1. Compare the new SSH fingerprint
with `.local/provisioning/device/identity.json` before accepting it.

[Report 26](26-first-card-and-boot-validation.md) records the identified Samsung
spare, the owner's explicit write authorization while the original-card backup
remains outstanding, and the macOS flash helper. It tracks physical results
separately from the build checks above; the recovery-backup gate remains open.

The USB address is `192.168.10.1`; the Mac gets a maintenance-link lease without
a router or DNS offer. The existing Wi-Fi configuration provides fallback.
Use user `cpi` with the corresponding development private key. Direct SSH from
the Intel host can use the Mac as an SSH jump host when accessing the USB link.

Check `/run/gameshellneo/ready.json` and `/run/gameshellneo/battery.json`, then
run `sudo gameshellneo-collect`. The readiness marker describes userspace and
enumerated device nodes; validate visible output, buttons and actual readings
separately. A short power press requests shutdown. Sleep is intentionally
unavailable. Follow the acceptance sequence in [report 23](23-first-build-spec.md).
