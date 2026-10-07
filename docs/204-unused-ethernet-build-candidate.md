# Unused Ethernet controller build candidate

8 October 2026, New Zealand; NEO-142. This is an offline candidate for the
owner's CPI v3.1. The compiled compressed kernel is **103,648 bytes smaller
(101.22 KiB, 1.575%)**, with the same ten modules and board DTB. The linked
kernel's address span is unchanged; reclaimed RAM, boot time and energy have
not been demonstrated. It does not change the installed diagnostic.23, its kernel
stage, image identity or qualified hardware evidence. The owner is asleep;
new display, sleep, reboot, button and cable tests are deferred.

## Source finding

The locked Linux 6.18.54 `sunxi_defconfig` enables both `SUN4I_EMAC` and
`STMMAC_ETH`. The first is the older Allwinner EMAC controller driver; the
second includes the Synopsys MAC core and enabled platform wrappers. These
are platform Ethernet MACs, separate from the networking used by this board:

| Function | Required implementation |
| --- | --- |
| Onboard Wi-Fi | `BRCMFMAC`/`BRCMFMAC_SDIO`, Sunxi MMC and the `brcm,bcm4329-fmac` SDIO node |
| USB connection to the Mac | Sunxi MUSB in peripheral mode, configfs ECM, `USB_U_ETHER` and `USB_F_ECM` |
| USB transceiver | `PHY_SUN4I_USB`, distinct from Ethernet PHY support |

The source audit covers `drivers/net/ethernet/allwinner/sun4i-emac.c` and the
enabled STMMAC wrappers `dwmac-generic.c`, `dwmac-sunxi.c`, `dwmac-sun8i.c` and
`dwmac-sun55i.c`. Their match tables describe other Allwinner MACs and generic
Synopsys bindings. The CPI DT includes the A33 platform, SDIO radio and MUSB
controller, with no corresponding platform Ethernet binding. The compiled-DTB
check extracts the actual match strings from those locked source files and
rejects a matching node even if it is disabled.

`arch/arm/mach-sunxi/sunxi.c` uses the A33's DT machine description and timer
initialization; it does not register a legacy EMAC/STMMAC platform device.
The generic STMMAC wrapper can also accept platform data on other systems, so
the DT check alone is not a claim about every supported platform. This
candidate is scoped to the CPI v3.1 build, without an Ethernet overlay or
external platform-device registration.

Both controller drivers register through `module_platform_driver`. Removing
their build support avoids linking that code and its registration. Their
absence from the board's device tree does **not** imply that they currently
poll hardware or consume measurable idle power. No such energy claim is made.

## Candidate and reproducible comparison

The separate `kernel/candidates/cpi31-no-ethernet.config` contains only:

```text
CONFIG_SUN4I_EMAC=n
CONFIG_STMMAC_ETH=n
```

It is not merged into `kernel/gameshellneo.config` or any image task.
The resolved comparison changes exactly nine options from built-in to disabled:
the two requested controllers, `STMMAC_PLATFORM`, its four enabled
`DWMAC_GENERIC`/`DWMAC_SUNXI`/`DWMAC_SUN8I`/`DWMAC_SUN55I` wrappers, and the
hidden `MII` and `MDIO_BUS_MUX` helpers. `MII` loses the controller selections;
`MDIO_BUS_MUX` loses the `DWMAC_SUN8I` selection. No other normalized option
changes. Existing prompted Ethernet PHY/PCS options remain enabled; this
candidate does not remove every unused network-related option.

Run the host-only comparison with:

```sh
task check:ethernet-config
```

The task builds baseline and candidate ARM kernels, modules and board DTBs
sequentially under the pinned compiler container. Both use the locked archive,
verified patch queue, unchanged project configuration and fixed kernel build
user, host, version and timestamp. They have separate output directories and
a verified shared source mounted read-only. The candidate adds just the two
overrides. No files are installed or copied into the completed kernel stage.

The comparison checks the required Wi-Fi/USB configuration, compiled board
bindings, unchanged board DTB and removal of the linked `emac_probe` and
`stmmac_dvr_probe` symbols. It rejects configuration changes outside the nine
audited removals, differing source/compiler identities, different module
inventories or module bytes. Module outputs must agree with Kbuild's
`modules.order`. It records configuration differences, compiler and source
provenance, artifact/module hashes, ELF section totals and compressed kernel
sizes, and retains copies of the modules as well as both kernels. Per-run evidence is retained under
`.local/build/ethernet-config-tests/run-*/`; the repeatable task log is
`.local/build/ethernet-config.log`.

The normal kernel preflight checks download/build storage. A separate read-only
check requires 12 GiB on the actual comparison filesystem before creating its
output: two 6 GiB planning allowances, even though source is shared. These
remain snapshots, not reserved space or peak guarantees. The suite and normal
build workflow locks prevent conflicting invocations through the saved task.
Verified configuration-specific outputs can be reused on a later invocation;
source inventories and all comparison gates are checked again.

## Measured result

| Measurement | Baseline bytes | Candidate bytes | Candidate minus baseline |
| --- | ---: | ---: | ---: |
| Compressed ARM `zImage` | 6,580,536 | 6,476,888 | −103,648 |
| GNU `size` text | 10,623,395 | 10,455,014 | −168,381 |
| GNU `size` data | 3,976,306 | 3,920,414 | −55,892 |
| GNU `size` BSS | 272,192 | 274,752 | +2,560 |
| GNU `size` total | 14,871,893 | 14,650,180 | −221,713 |
| `_stext` through `_end` address span | 16,286,144 | 16,286,144 | 0 |

The smaller file is a real storage reduction. The ELF totals must not be
reported as reclaimed device RAM. Both kernels have `_stext=0xc0100000`,
`_end=0xc10881c0`, `__init_begin=0xc0e00000` and `__init_end=0xc0f00000`.
The ARM `arch/arm/include/asm/memory.h` and `arch/arm/mm/init.c` use `_stext`
through `_end` for the non-XIP kernel's initial memblock reservation; those
bounds do not shrink. This does not measure any dynamic allocations avoided
by omitting driver registration.

The BSS increase is a layout effect. Its ELF section begins earlier
(`0xc1045a80` → `0xc1045080`) but still ends at `0xc10881c0`. The first sized
BSS symbol remains at `0xc1046000`; `BSS()` in
`include/asm-generic/vmlinux.lds.h` aligns the contents to a page. The larger
initial gap accounts for the 2,560-byte section increase. Comparing the
multiset of symbol names/sizes, including repeated static names, finds no
new or enlarged BSS symbol: only the three four-byte `chain_mode`,
`parent_count` and `stmmac_fs_dir` variables disappear. The saved task now
captures `nm` and `readelf` output and structured layout boundaries so this
distinction can be checked again.

All ten built modules are byte-identical between configurations, including
the SDIO radio, cfg80211, USB ECM and composite gadget modules. Both DTBs are
24,086 bytes with SHA-256
`8b27e81f542f4afefb4be398e52b283e9f12a01fb9a5f3b47068a8b6a9b9c040`.
The baseline resolved configuration is also byte-identical to the completed
diagnostic.23 configuration. The paired builds deliberately fix the build
timestamp; their complete binaries are not asserted to be the installed
kernel's binary identity.

## Host validation

Ten focused tests cover loss or changed build mode of each required recovery
dependency, absent baseline support, incomplete controller removal, unrelated
configuration changes, changed source/compiler/DT/module identities and the
comparison filesystem's space threshold, duplicate static symbol names and
missing layout evidence. The actual compiled DTB has 185 nodes
and none of the 22 extracted Ethernet match strings. Twenty-four negative
controls inject each of those strings into a disabled node, then independently
remove each required Wi-Fi/USB binding. Every mutation is rejected, and the
original blob stays byte-identical. These controls run for both build outputs.

The full `task check` passes 13 runtime and 679 tooling tests with one existing
opt-in skip, compiled host checks, Bash syntax and ShellCheck. The paired build
also retains the project's 169 resolved Kconfig assertions for both variants.
The compiler is the pinned Debian ARM GCC 14.2.0-19 toolchain.
Reusing the baseline's verified object cache reproduces its `.config`,
`vmlinux`, `System.map`, `zImage` and DTB byte-for-byte. The completed production
kernel stage still passes all 169 configuration assertions and its 15-file
artifact manifest; it was never used as either comparison output directory.

Final private comparison:
`.local/build/ethernet-config-tests/run-20261007T121811.059457Z/comparison.json`,
SHA-256 `d1a098000aeac4dba5647774263744497344053922ce7859a19a7998dbf0868a`.
Both `vmlinux` and `zImage` remain byte-identical to the earlier completed pair
after adding the layout capture. The final host-test log is
`.local/neo142-check-final.log`, SHA-256
`5289a5e2e477e1cca41b97c015e6901684a8346a69618329cc9bf6531456690c`.

| Paired artifact | Baseline SHA-256 | Candidate SHA-256 |
| --- | --- | --- |
| `zImage` | `9aa63ed3a9f865bff52173b882f0ddd58d823aa587d481c1d667d0857fa5c696` | `f794fc07b480768c12d82c0619d6552eecca3f9c026c4962ef4630a0348ab8f9` |
| Resolved `.config` | `b801d2edf212c267be4d29b205bce928c02bb05654d046708ae2dfcaada801b5` | `8cbf9d6f42a6830f36670a3d7c7553d7f9c0c7d510eb982dd437b56aab90c75e` |

The verified common source tree digest is
`2dcc5f5734951b324164f75f79544cfa0231a9cfdfa3f7bd7ce838481ffe07d9`;
the JSON binds it to the locked archive, 29 exported patches, compiler image,
configuration and comparison-tool inputs. The active project fragment,
source lock and production kernel stage retain their existing identities.

## Remaining qualification

Compressed-byte savings do not establish a boot-time saving. ELF `text`, `data`
and `bss` totals also do not directly measure persistent runtime RAM: they
include sections whose lifetime differs, and kernel layout/alignment changes.

Integration requires a new image identity, preserved diagnostic.23 recovery,
ordinary full kernel/device-tree/image checks and attended boot/network/PM
qualification. The next observation of intermittent post-return SSH setup can
still use installed diagnostic.23 and the host instrumentation in
[report 202](202-post-return-ssh-investigation.md); this optimization is not a
proposed fix for that unresolved issue.
