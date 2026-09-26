# Base-image feasibility: conclusions and validation plan

Research date: 2026-09-27. This is the decision-oriented companion to reports [07](07-sleep-and-wake-feasibility.md), [08](08-driver-and-board-support.md), [09](09-battery-and-power-policy.md) and [10](10-boot-and-update-architecture.md). The owner's [requirements](06-base-requirements.md) remain authoritative. This investigation performed source/document inspection only: no image build, hardware access, benchmark, flash or network configuration was performed.

## Conclusion

The available sources support pursuing a modern minimal GameShellNeo base. They do **not** establish that week-long standby or reliable deep suspend can be achieved by updating the kernel and carrying a small set of existing drivers forward. The most significant uncertainty is a complete A33/R16 system-suspend implementation with DRAM retention and verified wake. Battery protection during sleep is another separate gap.

The later [local-document investigation](13-allwinner-document-findings.md) strengthens the hardware case: R16 vendor configuration explicitly describes super standby, ARISC and DRAM self-refresh. It supplies useful mechanisms and research leads, but no complete standby firmware/source payload or measured CPI endurance. The proposed milestones below therefore remain appropriate.

The subsequent focused source investigation is complete in reports [17](17-vendor-firmware-and-dram-trace.md), [18](18-pmic-history-and-suspend-contract.md) and [19](19-modern-suspend-integration.md). It found explicit A33 DRAM operations, historical firmware interfaces and an existing ARMv7 PSCI/SCPI patch stack to assess. It also found a separate USB current-limit setter defect. **Use [report 20](20-base-implementation-plan.md) for the latest concrete implementation sequence.** These findings narrow the work without establishing working deep sleep.

The practical recommendation is to separate two engineering milestones without weakening the final requirements:

1. **A diagnosable modern base:** repeatable boot, correct board configuration, display/backlight, keypad, Wi-Fi, USB networking, battery telemetry and orderly shutdown. Measure awake idle and prove a basic suspend-to-idle/wake path where supported.
2. **Qualified low-power operation:** reliable state-preserving suspend with the required power savings, peripheral recovery and critical-battery protection. Investigate deeper firmware support as an explicit workstream rather than assuming the first milestone provides it.

A suspend-to-idle prototype would be an intermediate result, not completion of the owner's week-long standby ambition. There is no measured standby or boot-time result yet. The evidence behind these distinctions is in the [sleep report](07-sleep-and-wake-feasibility.md) and [battery report](09-battery-and-power-policy.md).

## Proposed baseline

| Component | Recommendation | Why / limitation |
| --- | --- | --- |
| Userspace | Minimal Debian 13 armhf through a pinned Armbian framework | Current ARMv7 support and practical package/tool availability; actual GameShell board support is project work |
| Kernel | Evaluate the maintained 6.18.y LTS line first; keep 6.12.y as a comparison fallback | Current inspected Armbian sunxi configuration uses 6.18; relevant A33 source comparisons do not establish a decisive 6.12 advantage |
| Bootloader | Qualified board configuration on a pinned U-Boot version; v2026.07 is the inspected framework baseline | Preserve diagnostics and ordinary U-Boot flow initially; no working new GameShell build is claimed |
| Driver strategy | Standard upstream interfaces, targeted board description and focused driver work | Existing code documents behavior but does not dictate the implementation |
| Sleep strategy | First prove and measure suspend-to-idle; bound the deeper suspend/firmware investigation separately | Deep sleep is not established by enabling `CONFIG_SUSPEND` or adding a generic Crust configuration |
| OTA direction | Evaluate signed A/B images and RAUC later; reserve a coherent boot/storage design now | Recovery, persistent state and bootloader layout remain integration work |

These are recommendations from this research, not additional user decisions. Exact commits and package versions must be frozen for the first experiment. Kernel.org lists 6.18 and 6.12 as longterm branches with projected December 2028 end-of-life; that projection is subject to change. The inspected release index lists 6.18.54 and 6.12.111. Audit findings apply to the source versions explicitly identified in each detailed report, not an unperformed review of every later stable patch. [Kernel release policy](https://www.kernel.org/category/releases.html), [release index](https://www.kernel.org/), [driver audit](08-driver-and-board-support.md), [build-framework analysis](10-boot-and-update-architecture.md).

## Most important findings

| Finding | Implication | Evidence |
| --- | --- | --- |
| Stock inspected ARMv7 U-Boot lacks the required system-suspend integration; an existing downstream PSCI/SCPI patch stack is now located; Crust's A33 DRAM suspend support is still absent | Assess/rebase known monitor work and develop retention support; the complete effort exceeds ordinary board-driver changes | [Original audit](07-sleep-and-wake-feasibility.md); [integration follow-up](19-modern-suspend-integration.md) |
| Legacy configuration disables CPU idle and defaults to the performance governor; board CPU-voltage integration needs correction | There is concrete active/idle efficiency work before speculative undervolting or overclocking | [Driver and configuration audit](08-driver-and-board-support.md) |
| LCD initialization and OCP8178 backlight control are board-specific gaps | Develop proper lifecycle-aware panel/backlight integration; assess the recent upstream submission before choosing to write another implementation | [Display audit](08-driver-and-board-support.md) |
| Battery percentage is exposed, but that does not establish calibration for the replacement pack | Validate percentage and timed endurance; do not infer exact remaining runtime from a raw percentage | [Battery telemetry](09-battery-and-power-policy.md) |
| Low-battery IRQ definitions do not amount to an implemented battery wake-to-shutdown path | Critical-battery protection in suspend needs separate design and tests | [Protection gaps](09-battery-and-power-policy.md) |
| The AXP223 USB-power driver contains frequent polling while external power is absent | Investigate wakeups and upstream history before changing event detection; no measured energy saving can yet be assigned | [Power-efficiency investigation](09-battery-and-power-policy.md) |
| The USB current-limit setter can select its unlimited entry for a finite request | Correct selection semantics and test them before relying on configured limits; preserve the intentionally distinct AXP223 capability table | [PMIC history and defect trace](18-pmic-history-and-suspend-contract.md) |
| Historical bootloader placement starts at 8 KiB and conflicts with a normal GPT layout | Design the card map explicitly before OTA partitioning; do not import a generic layout | [Boot/storage analysis](10-boot-and-update-architecture.md) |

Deferred functionality still has an idle-power cost to investigate. Disabling audio playback or HDMI acceptance tests does not prove the codec, amplifiers or bridge are powered down. The board supply topology decides which rails can safely be controlled independently. [Hardware analysis](02-hardware.md), [driver audit](08-driver-and-board-support.md).

## Validation plan

Every result should identify the board marking, image checksum, kernel/device-tree/firmware revisions, battery/USB-power condition and test procedure. Record failures as well as successes. The counts below are proposed engineering gates, not a certification standard or a guarantee of long-term reliability.

| Area | Proposed first test and pass condition |
| --- | --- |
| Recovery | Preserve the current card; demonstrate a spare-card restore and capture serial output before firmware/suspend experiments |
| Boot | Ten normal cold boots reach the defined local-ready endpoint without unexplained hangs; record timings for every run, separately from first-boot provisioning |
| Display/backlight | Verify useful brightness range, visually dark off state, repeated off/on and restoration after sleep; visually dark alone does not prove electrical off |
| Keypad/power key | Check every physical key, press/release and representative chords; one short power press requests one suspend; wake does not immediately trigger another sleep |
| CPU scaling | Observe allowed frequency transitions under idle/load, check regulator linkage/configuration, and detect instability under repeated transitions |
| USB management | Intel → Mac → GameShell SSH works; repeated cable reconnects and reboots recover without manual network reconstruction |
| Wi-Fi | Configure through USB/SSH, connect/disconnect, sleep with radio previously on/off, then restore that state and attempt reconnection; record reconnect time separately |
| Telemetry | Confirm battery presence, percentage validity, charging/discharging and USB-power transitions; compare a timed run with the reported trend |
| Idle policy | On battery, configured inactivity triggers sleep; timeout changes/disable work; an active SSH connection or USB power inhibits automatic sleep |
| Manual sleep | Power-button sleep remains available with USB or SSH connected; session loss is expected when networking stops; wake restores local operation |
| Initial suspend gate | Twenty consecutive cycles recover local state and in-scope peripherals; proceed to a proposed 100-cycle soak only after basic faults are resolved |
| Sleep conditions | Repeat with USB plugged/unplugged, Wi-Fi on/off and different noncritical battery levels; document actual available sleep state and wake reason |
| Low-battery policy | First test logic with controlled telemetry input; later validate on-device behavior with a conservative cutoff and supervision; do not deliberately run an uncertain pack to hardware cutoff |
| Endurance | Timed unplugged tests at fixed brightness/radio/activity settings; report duration, usable percentage interval and uncertainty, not fabricated precision in watts |
| OTA later | Verify untrusted/wrong-board rejection, inactive-slot installation, bounded boot attempts, interrupted updates, rollback and persistent-data compatibility |

A battery-powered SSH session intentionally prevents automatic sleep under the owner's policy. Endurance measurements must therefore avoid leaving such a session connected. Store sparse logs locally and retrieve them afterward; frequent sampling and open management links can change the behavior being measured. USB-powered diagnostics and unplugged endurance runs answer different questions. [Agreed policies](06-base-requirements.md), [measurement limitations](09-battery-and-power-policy.md).

Twenty or 100 successful short cycles do not establish a week of standby. Similarly, a time difference in rounded gauge percentages is not a precise current measurement. Report those limits and extend tests only when the hardware is stable enough to justify them.

## Read-only baseline to collect when the owner is ready

This work is deferred until the device and verified connection are available; it does not block source research:

- Mainboard and keypad markings; battery label and spare-card size.
- Running OS/kernel identification, boot files, device-tree identity and CPU/memory information.
- Available sleep states and wakeup controls, without requesting a suspend yet.
- CPU frequency/idle configuration, regulator/debug information where exposed, and relevant boot warnings.
- Battery/USB power-supply property names and a few readings during ordinary power transitions.
- USB enumeration and network-interface identity as observed by the Mac.
- Existing boot-time and endurance baseline, once a repeatable observation method is agreed.

Do not collect Wi-Fi passwords, private SSH keys or full home-directory contents as diagnostics. A backup remains separate from a public/shareable evidence bundle. The serial adapter's model, voltage compatibility and board pinout must be checked before any wiring guidance is applied. [Follow-up list](../FOLLOW-UP.md).

## Source access and uncertainty

Local sources were inspected at the snapshots recorded in report 01. External investigations used upstream Linux, U-Boot, Crust, distribution documentation, update-framework documentation and author patch discussions. Detailed reports name their fixed tags/commits. Some hosting endpoints were unavailable or rate limited; alternative primary-source mirrors or explicit access limitations are recorded where relevant. No absence claim based on a filename search should be read as proof that no related work exists anywhere.

The owner's [R16 datasheet](https://linux-sunxi.org/images/b/b3/R16_Datasheet_V1.4_%281%29.pdf) is useful electrical and pin-level evidence. The associated [R16 user manual v1.2](https://linux-sunxi.org/images/c/ca/Allwinner_R16_User_Manual_V1.2.pdf) was also located. Locating a manual does not establish that it documents all low-power DRAM operations; see the sleep report's source analysis. PDF text was accessible, but the research browser's requested datasheet screenshots failed, so no new interpretation of its power-sequence graphics is claimed here.

The additional GameShell standby discussion is assessed in report 07. [Report 12](12-r16-a33-source-guide.md) explains the upstream R16/A33 relationship, evaluates the supplied audio tutorial and records access limits for the development archives. These additions do not change the separation between a basic sleep milestone and deeper firmware qualification.

## Next step after the focused investigation

The owner authorized the deeper source investigation, now documented in reports 17–19. [Report 20](20-base-implementation-plan.md) turns it into a bounded plan: collect the hardware baseline, prepare a pinned diagnostic image, qualify ordinary device/policy behavior, then implement and test monitor/Crust retention incrementally. The research supports that experiment; it still does not support promising the final standby target within a small driver-only effort.
