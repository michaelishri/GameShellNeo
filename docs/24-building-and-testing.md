# Building the diagnostic image

This is the CPI v3.1 development workflow. Hardware acceptance remains NEO-5;
successful compilation and filesystem checks cannot establish boot, charging,
display or sleep behavior. Preserve the original card.

## Build stages

Use the Intel Linux host with Docker, Bash, Python 3, Git, curl, tar and a C
compiler. The wrappers obtain the builder by the digest in
[`sources.lock.json`](../build/sources.lock.json). Compilation uses one job and
disk-backed storage. The kernel and Armbian image stages are separate: kernel
changes require compilation, while runtime/image changes reuse verified kernel
artifacts. Armbian's project family does not inherit the broad sunxi patch queue
or runtime tuning. `KERNELSOURCE=none` is intentional in the image stage.

All commands below run from the GameShellNeo directory. Keep `.local/` private.
The original sibling repositories are reference inputs and are never modified.

1. Supply the exact bootloader and owner's radio files from the recorded
   baseline. Paths are arguments, not hard-coded machine dependencies:

   ```sh
   python3 tools/prepare-build.py \
     --bootloader ../GameShell/Code/Kernel/v0.2/u-boot-sunxi-with-spl.bin \
     --radio-directory .local/hardware-baseline/2026-09-27/radio-reference
   ```

2. Prepare private access. `current-ssid` contains only the chosen existing
   network name; `wireless-settings.conf` is the private Wicd reference. The
   helper accepts matching WPA-PSK profiles, rejects conflicting credentials,
   and writes no credentials to stdout. Never pass passwords in command lines.

   ```sh
   python3 tools/provision.py \
     --wicd .local/provisioning/wireless-settings.conf \
     --ssid-file .local/provisioning/current-ssid \
     --authorized-key .local/ssh/id_ed25519.pub \
     --output .local/provisioning/device
   ```

   The device directory contains a new SSH host key, its fingerprint record,
   Wi-Fi configuration and stable machine ID. Reusing it is appropriate for
   repeated images of this one board. Use a distinct directory/identity for
   another device. These identities differ from the original installation.

3. Build and record the kernel stage:

   ```sh
   tools/build-kernel.sh > .local/build/kernel.log 2>&1
   ```

   The helper verifies the Linux archive and applies only the project's patch
   queue. If patches change, use a fresh scratch source extraction; it rejects
   an already patched tree with a different patch manifest. The resolved config
   is asserted before compiling. The completed-stage manifest binds patch and
   configuration inputs to the installed modules, kernel and DTB.

4. Build the image:

   ```sh
   tools/build-image.sh > .local/build/image.log 2>&1
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

   `tools/build-image.sh rootfs` exercises the userspace bootstrap separately.
   Assembly first writes `.local/sources/armbian/output/images/`. The wrapper
   then runs offline filesystem/content verification and collects a private
   image, checksums, manifests, logs and package inventory in `.local/artifacts/`. The image
   contains private credentials and firmware; it is not a public release.

## Checks

```sh
python3 -m unittest discover -s runtime/tests -v
cc -std=c11 -Wall -Wextra -Werror \
  -Ikernel/overlay/drivers/power/supply kernel/tests/current_limit_test.c \
  -o .local/build/current_limit_test
.local/build/current_limit_test
python3 tools/check-kernel-config.py .local/build/kernel/.config
python3 tools/kernel-artifacts.py check
python3 tools/image.py verify PATH_TO_PRIVATE_IMAGE
```

`tools/check-devicetree.sh` uses the pinned builder's bundled dtschema 2026.9
against the patched kernel bindings and records the validator package versions.
It validates the modified bindings, processes the full schema set and checks
the project DTB. Emitted diagnostics fail the check even if the validator exits
zero. The build report records actual checks and any remaining caveats.

## First hardware session

Before writing a card, identify the spare and reader, and make an offline,
verified backup of the original. Do not infer a disk path. Flash only the spare,
then attempt first boot on the owner's CPI v3.1. Compare the new SSH fingerprint
with `.local/provisioning/device/identity.json` before accepting it.

The USB address is `192.168.10.1`; the Mac gets a maintenance-link lease without
a router or DNS offer. The existing Wi-Fi configuration provides fallback.
Use user `cpi` with the corresponding development private key. Direct SSH from
the Intel host can use the Mac as an SSH jump host when accessing the USB link.

Check `/run/gameshellneo/ready.json` and `/run/gameshellneo/battery.json`, then
run `sudo gameshellneo-collect`. The readiness marker describes userspace and
enumerated device nodes; validate visible output, buttons and actual readings
separately. A short power press requests shutdown. Sleep is intentionally
unavailable. Follow the acceptance sequence in [report 23](23-first-build-spec.md).
