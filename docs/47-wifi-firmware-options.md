# Wi-Fi firmware alternatives for CPI v3.1

Research date: **29 September 2026 NZDT**. Target: the owner's CPI v3.1,
BCM43430 **chip revision 0 / A0**, using Linux `6.18.54-gameshellneo5`.
This report records offline source and binary inspection. No firmware was
installed and no hardware was accessed for this research.

Subsequent hardware trials are recorded separately in
[report 48](48-a0-firmware-trials.md), including the candidate's runtime FWID,
which differs from the binary footer reported below.

## Answer

**Yes: a replacement binary can be used without firmware source, and upstream
linux-firmware contains a concrete newer A0 candidate.** Its embedded build date
is **29 May 2017**, compared with the installed binary's **8 October 2016**.
It uses the exact `brcmfmac43430a0-sdio.bin` filename selected for this chip
revision. It merits a controlled comparison; neither its date nor its published
change description establishes that it fixes the observed scheduled-scan crash.
[Installed baseline](21-installed-hardware-baseline.md);
[candidate binary][upstream-bin]; [Broadcom submission][introduction].

Raspberry Pi is a valid **distribution source**, but its newer Pi-specific
43430/43436 binaries are not interchangeable with this A0 device. The inspected
Pi 3B/Zero W replacement identifies itself as A1; the 43436s binary is also A1,
and the 43436 binary is B0. Raspberry Pi's package instead inherits the ordinary
upstream A0 file separately. Taking the pinned A0 binary directly from upstream
makes its identity and provenance easier to audit. [Pi packaging][pi-config];
[Pi overlay semantics][pi-readme]; [Pi binary files][pi-overlay].

## Exact silicon and board-data gate

The installed baseline reports `BCM43430/0`, filename
`brcm/brcmfmac43430a0-sdio.bin`, and runtime identification:

```text
BCM43430/0 wl0: Oct 8 2016 15:27:51 version 7.46.57.4.ap.r4 (A0 Station/P2P) FWID 01-e2c3069b es6.c5.n4.a3
```

The preserved binary SHA256 is
`bb2bd00ede1fe04c74d3684e76ef58d9f2acd54d6759894b934bbefb159668e9`.
The companion board NVRAM SHA256 is
`5f977a2a3916ef795ceb184cf928231d587249606d1750dacecb5f16ed941ae6`.
Preserve that NVRAM unchanged in a firmware comparison. Its presence and hash
were verified in the original capture; that capture did not explicitly name
the NVRAM file actually selected by the driver.
[Installed baseline](21-installed-hardware-baseline.md#radio-and-startup-observations).

The inspected Linux 6.18.54 `sdio.c` defines three separate mappings: revision
0 to `43430A0`, revision 1 to `43430A1`, and revisions 2+ to `43430B0`.
The A1 filename intentionally lacks an `a1` suffix for historical compatibility.
Therefore a file named simply `brcmfmac43430-sdio.bin` is not a generic candidate
for all 43430 revisions, and renaming it cannot establish compatibility.
[Local source](../.local/sources/linux-6.18.54/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c),
lines 615–618 and 648–650; [upstream driver][driver].

## Preferred candidate and provenance

| Property | Verified value |
| --- | --- |
| File | `brcm/brcmfmac43430a0-sdio.bin` |
| Source | Official `kernel-firmware/linux-firmware` GitLab repository |
| Inspected repository commit | `58a9869598b606fc2e5531298932b8757292f9a0` |
| Binary introduction commit | `cd86989eb7e809b12c29f9cbba0a6482efef1547`, committed 25 November 2017 |
| Size | 382,455 bytes |
| SHA256 | `ad85074b7919517d7e1a7e463e0176d46e7b312216bd7aa372e4aee2bfe8e07a` |
| Embedded chip/build | `43430a0-roml`, `7.13.53.9 (r664949)` |
| Embedded date | `Mon 2017-05-29 00:05:32 PDT` |
| Embedded Ucode / FWID | `997.0` / `01-93c3a6da` |
| Local candidate | `.local/research/firmware-options/linux-firmware/brcm/brcmfmac43430a0-sdio.bin` |

The complete binary was downloaded at the pinned current commit and independently
checked against the introduction commit and upstream tag `20260519`; all three
yielded the same SHA256. The file-specific upstream history contains only the
2017 introduction. This is a **2017 firmware build still distributed today**,
not a firmware built in 2026. The report uses the embedded date rather than
upload dates or cross-branch numerical version ordering.
[Pinned binary][upstream-bin]; [introduction][introduction];
[Pi base release][upstream-pi-base].

Broadcom's submission explicitly identifies the revision-0 requirement and
records fixes for CVE-2016-0801 and CVE-2017-0561. It does not mention the
GameShell's current scan failure. Those documented fixes do not establish which
fixes are absent from the separately versioned installed vendor build.
[Submission message][introduction].

`WHENCE` lists this binary under the Broadcom firmware license. The accompanying
`LICENSES/LICENCE.broadcom_bcm43xx` covers the binary, including complete,
unmodified redistribution for the intended Broadcom hardware and retention of
the agreement and notices. Preserve the exact license if the binary is included
in an image. This provides a documented redistribution path for this candidate;
the installed vendor binary's licensing provenance remains a separate open
question from the original capture.
[WHENCE][whence]; [license text][license];
[installed provenance limit](21-installed-hardware-baseline.md).

## Other inspected choices

All dates below are extracted **embedded build dates**, not repository dates.
The inspected revisions are pinned in the source list below.

| Source / path | Embedded target and release | Assessment for this A0 GameShell |
| --- | --- | --- |
| Upstream `brcm/brcmfmac43430a0-sdio.bin` | A0, `7.13.53.9`, 29 May 2017 | Newer matching-revision candidate; not hardware-qualified |
| Armbian `brcm/brcmfmac43430a0-sdio.bin` | A0, `7.10.1.244`, 1 July 2016 | Correct revision but older than installed; possible comparative fallback, not an upgrade |
| Armbian `ap6212/fw_bcm43438a0.bin` | A0, `7.10.226.49`, 6 June 2014 | Older vendor-format artifact |
| Armbian `rkwifi/fw_bcm43438a0.bin` | A0, `7.10.68.5`, 30 April 2015 | Older vendor-format artifact |
| Banana Pi vendor `ap6212/fw_bcm43438a0.bin` | A0, `7.10.226.1`, 18 July 2014 | Older vendor-format artifact |
| Upstream `cypress/cyfmac43430-sdio.bin`; identical Armbian `brcm/brcmfmac43430-sdio.bin` | A1, `7.45.98.118`, 30 March 2021 | Later build, wrong revision |
| Raspberry Pi `cypress/cyfmac43430-sdio.bin` under its packaging overlay | A1, `7.45.98 (TOB)`, 19 July 2021 | Pi 3B/Zero W replacement, wrong revision |
| Raspberry Pi `brcm/brcmfmac43436s-sdio.bin` under its packaging overlay | A1, `7.45.96.s1`, 14 June 2023 | Pi Zero 2 W variant, wrong revision |
| Raspberry Pi `brcm/brcmfmac43436-sdio.bin` under its packaging overlay | B0, `9.88.4.77`, 31 March 2022 | Pi Zero 2 W variant, wrong revision |

Sources: [upstream binaries][upstream-tree], [Armbian binaries][armbian-tree],
[Banana Pi vendor files][bpi-tree], [Raspberry Pi overlay][pi-overlay].
The local `manifest.json` records each downloaded file's full SHA256, size and
embedded metadata. Git symlinks downloaded through raw URLs are marked
`symlink-text`; their few-byte contents are link targets, not firmware.

Key alternative SHA256 values:

| Artifact | SHA256 |
| --- | --- |
| Armbian A0 `brcm/` binary | `86ed71ab0fc23dd6ccdf2262b1cf448c12238d46525aafc294cd9e6f3e3f761d` |
| Armbian A0 `ap6212/` station binary | `9495a5584db1aa3b31ca8f94e454be92a73d2e75fee030987cbb07c3226e4e0e` |
| Armbian A0 `rkwifi/` station binary | `0c7c8aaf153455130cec58c9a2df01783517d207675bca3c13f64b17eaa2d214` |
| Banana Pi A0 station binary | `6f96677d24289fcb31287c693a2f1084e6f0794250445c53314979349b24271d` |
| Upstream/Armbian A1 binary | `93f3c40c94340c29a40714cb04e3e89974870fcae42a844b8a4544750159f40d` |
| Pi 43430 A1 binary | `0717f8e798f3962230e76e9d840385ba127a38d31d6a55acd5c97cf53e4acc9d` |
| Pi 43436s A1 binary | `68b9bcc9855d91733cd44c21de4cb507c91b0d32d838c0696def5eb96c99e2de` |
| Pi 43436 B0 binary | `510a7dd1e056199b309425548ee0bd846993a1837ac7fa1e4d3e641f05a1327a` |

The Armbian A0 mainline file history shows its introduction in October 2017,
despite the binary's July 2016 build date. Its legacy `ap6212` and `rkwifi`
collections include AP/STA and manufacturing variants as well; filenames alone
do not prove they implement the modern driver's complete interface. No matching
firmware-specific license file was located in the inspected Armbian or Banana
Pi trees. They are less clearly documented candidates for redistribution than
the upstream artifact. [Armbian introduction][armbian-introduction];
[Armbian tree][armbian-tree]; [Banana Pi tree][bpi-tree].

For the rejected later-revision alternatives, upstream `WHENCE` assigns the
43430 A1 Cypress file to `LICENCE.cypress`. Raspberry Pi's copyright metadata
assigns its added 43430 files to its Cypress license entry and its added 43436
files, including 43436s, to its Synaptics entry. Those provenance entries do not
make the binaries suitable for A0. [WHENCE][whence]; [Pi copyright][pi-copyright].

## Raspberry Pi packaging and original-vendor limits

The inspected `RPi-Distro/firmware-nonfree` default branch is `trixie`, commit
`3bab0f823f5b53150b76aab77093adef6655b920`. Its package version is
`1:20260519-1~bpo13+1+rpt1`. Its source instructions describe taking the upstream
linux-firmware release and overlaying `debian/added-firmware`. The package
includes `brcm/brcmfmac*` and does not exclude A0; the inspected complete tree
has no A0 replacement in the overlay. The A0 file at upstream `20260519` has
the preferred candidate's hash. Thus **the packaging recipe includes the same
A0 candidate**. A built Raspberry Pi `.deb` was not downloaded or independently
unpacked in this investigation. [Changelog][pi-changelog];
[source instructions][pi-readme]; [package selection][pi-config].

The Pi 3B and Zero W board-specific `.bin` links resolve to
`../cypress/cyfmac43430-sdio.bin`. The Zero 2 W links point to 43436s or 43436
depending on the driver-selected revision. Keep the GameShell's own NVRAM;
the Pi's `.txt` files are board-specific data, not firmware upgrades.
[Pi overlay][pi-overlay]; [driver revision selection][driver].

The inspected official ClockworkPi GameShell tree at
`523cf591e2f955d001d257d7c850406f9fd917eb` contains no replacement radio binary
in its recursive file inventory. This is a bounded repository finding, not a
claim about every historical GameShell OS image. The public Infineon
`ifx-linux-firmware` tree at `d24c95cce5e77b04736972ba05ccd06da6cc377f`
contains newer firmware families but no 43430/43438 A0 artifact. Infineon's
support response for the older 43438 family directs release-change enquiries
to the module vendor. No vendor or other person was contacted.
[ClockworkPi tree][clockwork-tree]; [Infineon tree][infineon-tree];
[Infineon support response][infineon-support].

## What a later comparison must establish

Finish the separate original / scan-offload-disabled / original runtime
comparison before changing the binary. Its temporary runtime flag and its
results are separate evidence; this report makes no claim about their outcome.
A firmware test should have a verified USB recovery route, preserve the original
binary and exact GameShell NVRAM, and change only the selected A0 `.bin`.
Confirm the new runtime version after reload or reboot; a file copied to disk
does not prove the radio loaded it.

Compare the same disconnected scheduled-scan workload, count firmware crashes
and SDIO removals, then check connection, reconnection and the intended network
switch. Keep the driver and scan settings fixed within the firmware comparison.
If the new build fails to start or regresses networking, restore the original
hash. Only passing those checks would justify considering it for the image.
These are proposed controls derived from the chip mapping and ongoing failure
context, not a report of completed hardware tests. USB battery qualification
should resume only after the intended network is stable.

## Reproducibility

Downloads and metadata are retained under the ignored directory
`.local/research/firmware-options/`: repository commit and tree JSON, file
history, original binary bytes, `WHENCE`, upstream licenses, packaging metadata,
and `manifest.json`. GitHub trees were checked as complete (`truncated: false`).
The preferred binary was fetched through the official GitLab repository API at
the pinned commit. The manifest distinguishes downloaded symlink text from
actual binaries. These files are offline research artifacts and were not
copied to the GameShell or added to an image.

[upstream-bin]: https://gitlab.com/kernel-firmware/linux-firmware/-/blob/58a9869598b606fc2e5531298932b8757292f9a0/brcm/brcmfmac43430a0-sdio.bin
[upstream-tree]: https://gitlab.com/kernel-firmware/linux-firmware/-/tree/58a9869598b606fc2e5531298932b8757292f9a0
[upstream-pi-base]: https://gitlab.com/kernel-firmware/linux-firmware/-/blob/20260519/brcm/brcmfmac43430a0-sdio.bin
[introduction]: https://gitlab.com/kernel-firmware/linux-firmware/-/commit/cd86989eb7e809b12c29f9cbba0a6482efef1547
[whence]: https://gitlab.com/kernel-firmware/linux-firmware/-/blob/58a9869598b606fc2e5531298932b8757292f9a0/WHENCE
[license]: https://gitlab.com/kernel-firmware/linux-firmware/-/blob/58a9869598b606fc2e5531298932b8757292f9a0/LICENSES/LICENCE.broadcom_bcm43xx
[driver]: https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/tree/drivers/net/wireless/broadcom/brcm80211/brcmfmac/sdio.c?h=v6.18.54
[pi-config]: https://github.com/RPi-Distro/firmware-nonfree/blob/3bab0f823f5b53150b76aab77093adef6655b920/debian/config/defines.toml
[pi-readme]: https://github.com/RPi-Distro/firmware-nonfree/blob/3bab0f823f5b53150b76aab77093adef6655b920/debian/README.source
[pi-changelog]: https://github.com/RPi-Distro/firmware-nonfree/blob/3bab0f823f5b53150b76aab77093adef6655b920/debian/changelog
[pi-copyright]: https://github.com/RPi-Distro/firmware-nonfree/blob/3bab0f823f5b53150b76aab77093adef6655b920/debian/copyright
[pi-overlay]: https://github.com/RPi-Distro/firmware-nonfree/tree/3bab0f823f5b53150b76aab77093adef6655b920/debian/added-firmware
[armbian-tree]: https://github.com/armbian/firmware/tree/2a9e1c19460401443267926181191d57e3ff175d
[armbian-introduction]: https://github.com/armbian/firmware/commit/3aa265d38307115a8be673aeaf16ec36439b6d06
[bpi-tree]: https://github.com/BPI-SINOVOIP/BPI_WiFi_Firmware/tree/bfef5c84b7079a714f6bb96a60f468f05a4518c0/ap6212
[clockwork-tree]: https://github.com/clockworkpi/GameShell/tree/523cf591e2f955d001d257d7c850406f9fd917eb
[infineon-tree]: https://github.com/Infineon/ifx-linux-firmware/tree/d24c95cce5e77b04736972ba05ccd06da6cc377f
[infineon-support]: https://community.infineon.com/t5/AIROC-Wi-Fi-and-Wi-Fi-Bluetooth/Android-12-wifi-Driver-security-performance-improvement-files/td-p/831846
