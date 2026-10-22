# Ext4 security attributes for Debian images (NEO-209)

This prepares diagnostic.27, kernel `6.18.54-gameshellneo26`, to preserve normal
Debian `security.capability` attributes on ext4. Hardware qualification and the
subsequent NEO-208 bundle import/select/confirm remain open. NEO-192's clock and
PM admission is separate and unchanged.

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
Resolved configuration, new image, filesystem and transfer results will be
recorded here after their authoritative stages complete. No offline build result
establishes board capability/import success, clock health, PM safety or energy
behavior.
