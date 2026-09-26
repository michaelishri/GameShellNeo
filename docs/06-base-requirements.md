# Initial base image: agreed requirements

Status: requirements discussion, recorded 2026-09-27. This document records the owner's decisions following the research reports. It is not a claim of implemented or tested functionality. Building and device changes have not started.

## Objective and platform

Create a reliable, power-efficient Linux foundation before working on a launcher. Prioritize driver compatibility, hardware integration, power management and maintainability.

- Support only the owner's **CPI v3.1** board. The owner has now confirmed that revision is printed on the mainboard; the earlier micro-HDMI-based inference is superseded by that physical identification. Other revisions are outside the initial support scope because they cannot be tested.
- Start with a minimal Armbian/Debian base. Keep hardware support portable enough to consider a bespoke distribution later.
- A supported LTS kernel is acceptable initially. Newer stable Linux remains a direction, not a requirement to use the latest release for the first milestone. No exact kernel version has been selected.
- A small, documented downstream patch set is acceptable. Record each patch's purpose and the conditions for removing it.

## Engineering guidelines and long-term experience

Existing ClockworkPi and community code is reference material for hardware behavior, known problems and prior solutions. It is not a prescribed implementation. The owner welcomes redesigned or newly written drivers where that provides better efficiency, functionality or reliability. Evaluate reuse, upstream extension and new implementation on their merits; justify changes with hardware evidence and tests. Maintainability and standard Linux interfaces remain design goals. New driver work does not bring deferred peripherals into the initial milestone automatically.

The owner identifies the Nintendo Switch experience as an inspiration: quick startup, over-the-air updates and dependable sleep/resume. This is a product-experience target, not a verified statement about Nintendo hardware timings or an assumption that GameShell can reproduce its implementation.

| Long-term target | Interpretation and validation needed |
| --- | --- |
| Startup under five seconds | Aspirational cold-boot target. Define the start event and usable-ready endpoint before benchmarking; distinguish first visible output, interactive readiness and network availability. Launcher readiness can only be evaluated once a launcher exists. |
| Reliable sleep/resume | Preserve running state and recover peripherals consistently across repeated cycles, battery levels and USB-power transitions. Retain the sub-second resume aspiration and week-long standby aspiration already discussed. |
| Over-the-air updates | A required long-term capability. Investigate authenticated updates, interrupted-update recovery, rollback and preservation of user data/settings before committing to a production storage layout. No OTA framework or partition scheme is selected. |

Early development may still use manual microSD reflashing. OTA implementation is later work, but its storage and bootloader implications should inform the base architecture. Startup optimization is an explicit goal alongside correctness and efficiency; numerical targets remain subject to feasibility and measurement.

## Initial functional scope

| Area | Required behavior |
| --- | --- |
| Boot | Reliable startup on the owner's hardware, with diagnostic access |
| Built-in display | Working display output and backlight control; accelerated rendering is deferred |
| Input | Working keypad and power-button handling |
| Wi-Fi | Connectivity and SSH access; initial setup through USB/SSH |
| USB networking | SSH access through a macOS-compatible USB network connection |
| Battery | Charge percentage, charging/discharging status and external-power detection through standard Linux interfaces and command-line tools |
| Charging and shutdown | Validate charging behavior and orderly shutdown; automatically shut down at critically low battery |
| Sleep and resume | Preserve running state through low-power sleep and recover the in-scope hardware on wake |

Battery percentage accuracy and the critical shutdown threshold require validation. No battery UI is required during this phase. Critical-battery handling during sleep remains a feasibility question; an awake userspace monitor alone does not establish protection while suspended.

## Power policy

| Condition | Agreed policy |
| --- | --- |
| Short power-button press while awake | Request low-power sleep |
| Wake trigger | Power button is sufficient; game-button wake is not required |
| On battery, inactive | Automatically sleep after two minutes by default |
| Inactivity configuration | User can change the timeout or disable automatic sleep |
| Active SSH connection | Inhibit automatic sleep, including on battery |
| Connected to USB power | Inhibit automatic sleep; deliberate power-button sleep remains available for testing |
| Wi-Fi during sleep | May disconnect; restore the previous enabled state and attempt reconnection on wake |
| Bluetooth when added later | Same sleep/reconnection policy as Wi-Fi |

The SSH and USB-power rules apply to automatic sleep. They do not remove deliberate power-button sleep. Exact activity detection, session tracking and configuration mechanisms are not yet selected. Future game activity and launcher integration will need separate treatment.

Resume in under one second and standby endurance of a week or more are **aspirational targets**, subject to hardware and battery measurements. The owner wants eventual user choice over the power/resume tradeoff where feasible. Neither multiple working sleep modes nor deep suspend support has been established yet. Device resume and network reconnection latency should be measured separately.

## Development and measurement setup

- Use the current Intel x86 machine as the primary development host.
- Connect GameShell by USB to an M2 MacBook Air, kept powered on and awake during development. The Intel host and Mac are on the same local network.
- The Mac runs macOS Tahoe 26.5.1 (25F80), as reported by the owner.
- Access is Intel host → SSH jump host on Mac → USB Ethernet → GameShell. This path was subsequently verified by an authenticated SSH session; see [the installed baseline](21-installed-hardware-baseline.md). No network settings were changed during the test. Repeated reconnection remains to be qualified.
- A USB-to-serial adapter is available; [report 22](22-serial-cable-and-console-preparation.md) records its recovered product documentation and pending GameShell connection. Serial setup is deferred and does not block initial base work. Provide wiring and console guidance when it resumes, after verifying the physical connection.
- A spare microSD card is available. Reflashing it when needed is acceptable; preserve the existing working installation.
- The battery was replaced about 18 months ago. Its rated capacity and current usable capacity require confirmation.
- No external power-measurement equipment is available. Use software readings and timed battery tests, recording uncertainty. Battery endurance tests need to account for USB charging and diagnostic activity.

## Deferred scope

Launcher work, on-device Wi-Fi configuration, HDMI output, Bluetooth, GPU acceleration, and speaker/headphone playback are deferred. Their deferred functionality does not establish that the associated hardware draws no power; its idle power state still matters to the efficiency investigation.

Detailed follow-up tasks are maintained in [FOLLOW-UP.md](../FOLLOW-UP.md).

## Next analysis, before building

The remaining questions primarily require technical evidence rather than more preference gathering:

1. Map required board support against a candidate supported kernel, identifying essential patches, obsolete compatibility code and unresolved gaps.
2. Establish the R16/A33 sleep/wake path, including any bootloader or firmware dependencies, PMIC wake behavior and peripheral recovery requirements.
3. Determine battery telemetry capabilities and how critical-battery protection can operate both awake and asleep.
4. Define repeatable acceptance tests for the agreed functionality and power policies, separating minimum functional success from aspirational endurance/latency targets.
5. Identify cold-boot bottlenecks and OTA implications for bootloader and storage design. Evaluate driver approaches independently of historical implementations.

Exact kernel selection, implementation details and numerical performance guarantees remain open. These analysis items do not authorize an image build or device modification.

Research status, 2026-09-27: the source-based investigation of these five items is complete in reports 07–12. See [the feasibility summary](11-feasibility-summary-and-validation-plan.md) for recommendations and remaining implementation/hardware questions. The requirements above remain unchanged.

Subsequent research assessed the supplied Allwinner documents in reports 13–16 and traced vendor firmware, PMIC history and modern suspend integration in reports 17–19. [The implementation plan](20-base-implementation-plan.md) records the latest recommendations without changing these agreed requirements.
