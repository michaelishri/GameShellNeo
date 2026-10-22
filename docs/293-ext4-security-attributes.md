# Ext4 security attributes for Debian images (NEO-209)

Diagnostic.27, kernel `6.18.54-gameshellneo26`, is built and offline verified with
normal Debian `security.capability` attributes on ext4. Hardware qualification
and the subsequent NEO-208 bundle import/select/confirm remain open. NEO-192's
clock and PM admission is separate and unchanged. NEO-210 prepares an inactive
store package for guarded bootstrap from the existing fixed recovery; the
original diagnostic.25 recovery remains unchanged.

The original recovery/diagnostic.25 and diagnostic.26 images remain immutable.
Their running kernels disable `CONFIG_EXT4_FS_SECURITY`. The retained real
bundle import failed verification of `usr/bin/fping`'s capability; a private
scratch roundtrip returned errno 95 for `security.capability` while `user.*`
worked. Retaining all metadata requires a capable running kernel before import;
an imported root alone cannot repair the initial running kernel.

The image fragment now requests `CONFIG_EXT4_FS_SECURITY=y`, and the resolved
configuration checker requires it independently of experiment selections or a
fragment entry. Linux 6.18.54's `fs/ext4/Kconfig` depends only on `EXT4_FS` for
this option. No LSM or `CONFIG_SECURITY` selection is added. The source lock
changes only the new image and kernel version fields. All 33 production patch
names/hashes, overlay files and experiment selections remain unchanged.

Normal image assembly and its offline verifier can reuse an existing identity
without preparing a second identity:

```sh
export NEO_IMAGE_PROVISIONING_DIRECTORY=/absolute/existing/checkout/.local/provisioning/device
task build:image BOOTLOADER=/absolute/locked/u-boot-sunxi-with-spl.bin RADIO_DIR=/absolute/radio-reference
```

The selector validates existing regular provisioning files and passes their
directory as data to a read-only Docker child mount at the established
`/project/.local/provisioning/device` path. Unset selection retains the normal
local directory. Neither helper invokes provisioning or writes the selected
inputs. The existing image/runtime identity installation and verification stay
in place. Explicit provisioning selection must also be supplied when later
invoking `verify-image.sh` separately from the image build.

The isolated build worktree owns its outputs. The original completed kernel
receipt (`4ad6db59201996fd45dcc8e3a79d44d38268b7f5610da145e3ec0186602f94a2`)
passed its 16-file check. The new incremental kernel copy matched all 8,742
files, modes, modification times and symlink targets. The locked kernel archive
is independently hash-checked and freshly extracted by the saved kernel task;
the source stamp and completed original receipt both match the unchanged 33
patches. No original `.local/kernel-install` directory is copied. Fresh modules
must be installed under the new release. The Armbian copy excludes old output
images, active scratch, transient locks/bytecode and the old base-rootfs cache;
the changed image wrapper deliberately invalidates that old cache receipt.

Private build logs, original-input preservation hashes, cache-copy proof and
managed stage receipts are retained under this worktree's `.local/build/`.
The source check passes 24 runtime tests and 1,166 tooling tests (four explicit
skips), both native C checks and Bash/ShellCheck. The final source log is
`.local/build/neo209/host-check-final-source.log`, SHA-256
`d4e656c0173723b7602af9c8d0a953e44ff21b158752fbf7432a30fd7d14efda`.
The new checker rejects the retained diagnostic.26 configuration specifically
because `CONFIG_EXT4_FS_SECURITY` resolves to `n`. Its regression also rejects
a missing or disabled resolved option when the fragment omits the entry.

The maintained source is commit `910d5b8`. The resolved kernel passes all 183
configuration assertions, enables `CONFIG_EXT4_FS_SECURITY=y`, and retains
`CONFIG_SECURITY=n`. Its `System.map` contains `ext4_xattr_security_handler`,
`cap_inode_setxattr` and `cap_convert_nscap`. The new completed-kernel receipt
checks all 16 artifacts; only `6.18.54-gameshellneo26` modules are installed.
An independent full-tree comparison confirms that the freshly extracted patched
source matches all 97,300 original source entries (91,167 regular files and 85
symlinks, with directories included). Its tree SHA-256 is
`9a23a32a41c2bb16db51dabafb603598da6ae5fe0275486ef9c5ab2db6fe6f9b`.

Evidence is retained in
`/home/mishri/workspace/clockworkpi/GameShellNeo/.local/worktrees/ext4-security-attributes`.
The saved `build:kernel` and `build:image` Tasks completed with these managed
stages, each with authoritative exit 0, no OOM and no stop request:

| Stage | Managed run |
| --- | --- |
| Kernel | `45d007d4ba05498da555258fdc16d9ea` |
| Normal image assembly | `3db17d055ae24c779e1c215501d26040` |
| Normal image filesystem/content verification | `3239829aca5943799eeb1bd649779754` |
| Additional read-only image inspection | `a0015afe125f4f019b8cf24e2a01cb5f` |

The additional inspection mounts the artifact read-only and verifies its exact
source-lock/project-input manifest, new kernel/module release, reused identity
bytes and `usr/bin/fping` capability. The latter is
`0100000200200000000000000000000000000000`, the effective permitted
`CAP_NET_RAW` attribute. The normal verifier passes MBR boundaries, original
bootloader readback, FAT16/ext4 read-only filesystem checks, U-Boot CRC/address
checks, installed kernel/DTB/modules/radio hashes, private identity permissions
and service policy. Every entry in the completed artifact bundle's
`SHA256SUMS` verifies.

| Retained artifact | SHA-256 |
| --- | --- |
| `.local/artifacts/GameShellNeo-0.1.0-diagnostic.27-cpi31-f51b91fe7cfc.img` (4,294,967,296 bytes) | `f51b91fe7cfcfb24747e137a0c2bac46e9a0d12e0dc995500fad5dd9200f8617` |
| `.local/artifacts/verification.json` | `9961937326db2865bb93c550c67ccc34a9f295759ee62afefefb4c4370190154` |
| `.local/artifacts/image-manifest.json` | `c14bb9f43d9de58ee5268482389754338110ec84aea6f364e298ca4dd6b9d4f1` |
| `.local/build/kernel-completed.json` | `06469342853c28af584e2068a98a2e669728c10780354e7241781a9a871af7a2` |
| `.local/build/neo209/kernel-validation.json` | `77f7e5f0a730142fd77b5e7f876a067dc1b3c4390e45117f8218aae31ba85eed` |
| `.local/build/neo209/image-extra-audit.json` | `40e0c92fef3eeb3f16aa477c7126347ea394d7ecbf37218ad037cf562169785c` |
| `.local/build/neo209/qualification.json` | `6001dcbf656a9e7ccc87cbdeb5bcaabc8f1f648c25b501fdd48b855e16cd3e7a` |

The final qualification index pins all four stage receipts/logs, scripts and
artifact manifests. All 819 tracked inputs stayed unchanged through the builds
and inspection. All nine preserved original receipt/provisioning entries match;
private input files retain their original bytes and modification times. The
live image mount proof confirms the existing provisioning bind is read-only and
all writable project/Armbian paths belong to the isolated worktree. The first
image invocation omitted the explicit provisioning selector and stopped before
Docker; its original task log remains separately retained. The corrected saved
invocation is the successful stage above. The managed ledger is idle.

Standards review of `910d5b8` reports zero documented violations and zero
actionable code smells. Spec review of the same fixed source reports zero
missing, incorrect or out-of-scope findings. These reviews cover source;
the independently retained stage and inspection receipts establish the offline
artifact results. No offline build result establishes board capability/import
success, clock health, PM safety or energy behavior. No board, Mac, physical
card, selection or reboot action was performed by these preparation stages.
