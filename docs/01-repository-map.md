# GameShellNeo: repository map and research scope

Research date: 2026-09-27. This is a source and documentation investigation, not a boot test or a reconstruction of a shipped SD card.

## What is in the workspace

The workspace now contains three Git repositories and the `GameShellNeo/docs` destination. `launcher/` was added after the initial research and assessed in a follow-up on the same date. All three source repositories were clean when inspected. No project-level `AGENTS.md` was found inside this workspace or in the inspected ancestor directories. Counts below are tracked entries, including any submodule gitlink, not all files on disk.

| Directory | Origin | Inspected commit | Tracked entries | Role |
| --- | --- | --- | ---: | --- |
| `GameShell/` | [clockworkpi/GameShell](https://github.com/clockworkpi/GameShell) | `523cf591e2f955d001d257d7c850406f9fd917eb` | 108 | Hardware documents, kernel patches/binaries, keypad firmware, OS download index |
| `LauncherGoDev/` | [clockworkpi/LauncherGoDev](https://github.com/clockworkpi/LauncherGoDev) | `b10fa7ab346f43bb89759cb8c558f12ed7590004` | 196 | Later Go/SDL launcher implementation and its integration scripts/assets |
| `launcher/` | [clockworkpi/launcher](https://github.com/clockworkpi/launcher) | `e15f6155cd34e82691291abc273678ef9e7ee880` | 325 | Python/Pygame launcher, X11 session setup, helpers and assets |
| `GameShellNeo/docs/` | No Git repository at this directory at research start | Not applicable | Initially empty | Reports produced for this investigation |

Evidence: local `git remote -v`, `git rev-parse HEAD`, `git ls-files`, `git status --short`, and directory inspection. Online equivalents are the [GameShell snapshot](https://github.com/clockworkpi/GameShell/tree/523cf591e2f955d001d257d7c850406f9fd917eb) and [LauncherGoDev snapshot](https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004). These pinned trees are preferable to a moving branch when reproducing this research.

## GameShell: the hardware and historical support bundle

This repository is an index and collection of components. It is not a complete checked-in operating-system build. Its current README advertises the 32-bit `clockworkos_v0.5.img.bz2`, dated January 4, 2020, with Linux 5.3.6 and a 1.8G download. It separately links the community D.E.O.T. image and both Python and Go launchers. The repository itself contains a v0.1 torrent, rather than the advertised v0.5 root filesystem. [Source: README](../../GameShell/README.md).

| Area | Important files | Why it matters |
| --- | --- | --- |
| Electrical design | [Mainboard schematic](../../GameShell/clockwork_Mainboard_Schematic.pdf), [keypad schematic](../../GameShell/clockwork_Keypad_Schematic.pdf) | Component identities, connections, supply rails and revision evidence |
| Mechanical assembly | [Assembly guide](../../GameShell/clockwork_GameShell_Assembly_Guide.pdf), [3D models](../../GameShell/Code/3Dmodel/) | Module layout, repair/modification references, case and button assets |
| Keypad | [Sketch](../../GameShell/Code/Keypad/clockworkpi_keypad.ino), [README](../../GameShell/Code/Keypad/README.md), bundled `UsbKeyboard/` and HEX image | Independent microcontroller firmware and USB keyboard behavior |
| Early kernels | [Kernel README](../../GameShell/Code/Kernel/README.md), `cpi3-linux_4_14_2.patch`, `v0.2/`, `CPI3_linux_4.20/` | Historical build instructions, board support and prebuilt kernel/device-tree/bootloader artifacts |
| Intermediate boot/kernel work | [v0.4](../../GameShell/Code/Kernel/v0.4/) | Linux 5.2-rc4 patch and bootloader flashing notes |
| Later kernel work | [v0.6](../../GameShell/Code/Kernel/v0.6/) | Seven Linux 5.15 patches and a pinned upstream base, despite the README still advertising image v0.5 |
| Bluetooth | [Bluetooth README](../../GameShell/Code/bluetooth/README.md), firmware and patchram executable | Historical userspace firmware loading requirements |
| USB networking | [USB-Ethernet README](../../GameShell/Code/USB-Ethernet/README.md), patches and Windows driver archive | Device-mode network integration and historical host setup |
| Emulator settings | [retroarch.cfg](../../GameShell/retroarch.cfg) | Original application assumptions and mappings; not a complete emulator distribution |
| Documentation automation | [publish-wiki.yml](../../GameShell/.github/workflows/publish-wiki.yml), [wiki home](../../GameShell/wiki/Home.md) | Wiki synchronization, not an image build or hardware test pipeline |

The v0.6 instructions target Linux `5.15.y` at `5827ddaf4534c52d31dd464679a186b41810ef76`, use `arm-linux-gnueabihf-`, and package a `zImage` into a U-Boot `uImage`. This is concrete evidence of a later board-support effort; the folder name alone does not establish a released v0.6 operating-system image. [Source: v0.6 README](../../GameShell/Code/Kernel/v0.6/README.md).

The local Git history begins in August 2023, when earlier material was gathered into this repository. Its latest commit is a February 2026 README change; the v0.6 README change is from April 2024. This history therefore cannot be used as the original publication chronology of all enclosed artifacts. [Sources: initial commit](https://github.com/clockworkpi/GameShell/commit/964d6b6), [gathering commit](https://github.com/clockworkpi/GameShell/commit/e5480d5), [v0.6 documentation](https://github.com/clockworkpi/GameShell/commit/994a646), [latest inspected commit](https://github.com/clockworkpi/GameShell/commit/523cf591e2f955d001d257d7c850406f9fd917eb).

## LauncherGoDev: an application, with OS integration assumptions

The README describes a Go launcher designed around a 320×240 screen and D-pad, with a `cpi` account, a `cpifav` group, application/game directories and Music Player Daemon configuration. Those requirements show that it expects a prepared Linux environment. They do not describe how to construct that entire environment. [Source: launcher README](../../LauncherGoDev/README.md).

| Area | Location | Research significance |
| --- | --- | --- |
| Application entry and screen | [main.go](../../LauncherGoDev/main.go), [mainscreen.go](../../LauncherGoDev/mainscreen.go) | Runtime startup, UI and event flow |
| Shared implementation | [sysgo](../../LauncherGoDev/sysgo/) | Reusable UI/system helpers and GameShell integration |
| User-facing programs/settings | [Menu](../../LauncherGoDev/Menu/) | Launcher plugins, game launch scripts, system settings and application acquisition |
| Application installation | [appinstaller](../../LauncherGoDev/appinstaller/) | Separate helper source used by local development build |
| Assets | [skin](../../LauncherGoDev/skin/), `screenshot/` | Existing visual language and bundled resources |
| Go dependency graph | [go.mod](../../LauncherGoDev/go.mod), [go.sum](../../LauncherGoDev/go.sum) | Declares Go 1.17 and dependencies including SDL2 bindings, SQLite, D-Bus, Bluetooth, MPD and Wi-Fi helpers |
| Build/deployment | [build.sh](../../LauncherGoDev/build.sh), [local-build.sh](../../LauncherGoDev/local-build.sh), [deploy.sh](../../LauncherGoDev/deploy.sh), [update.sh](../../LauncherGoDev/update.sh) | Small developer scripts with expected paths, rather than an OS release pipeline |

`build.sh` builds the launcher from two Go entry files. `local-build.sh` also builds the application installer and copies outputs to a developer-specific directory; `deploy.sh` copies the launcher into `/home/cpi/launchergo`. No tracked test files or GitHub Actions directory were found in this snapshot. This describes the checked-in tooling, not a claim that upstream has never tested the program. [Sources: build scripts above; pinned repository tree](https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004).

The Go project itself dates to June 2018; “later Go launcher” here describes the inspected generation, not a claim that Go was introduced after v0.5. [Source: first commit](https://github.com/clockworkpi/LauncherGoDev/commit/26f18da0d8a615b24baf01e76c3b57eb85138078).

Recent history needs interpretation: the 2025 and 2026 merges update dependencies, while the preceding 2024 commit fixes a typo and the preceding feature work is from January 2023. Recent timestamps establish some source maintenance, but do not demonstrate a shipped, tested GameShell image. [Sources: inspected latest commit](https://github.com/clockworkpi/LauncherGoDev/commit/b10fa7ab346f43bb89759cb8c558f12ed7590004), [2024 change](https://github.com/clockworkpi/LauncherGoDev/commit/d99b6a6), [2023 change](https://github.com/clockworkpi/LauncherGoDev/commit/2743d6b).

## launcher: the original Python interface and session bundle

The newly added local checkout matches the current Python snapshot examined online in the initial research, but provides its full tracked tree and history directly in the workspace. Its HEAD is dated January 3, 2023. Relative to the historical January 2, 2020 baseline `c4a12ce2d29b1694e1f7f13d89ae2451751a543c`, Git reports changes to 25 files, with 259 insertions and 68 deletions plus binary replacements. This is a comparison of repository revisions, not a manifest of differences between shipped images. [Current snapshot](https://github.com/clockworkpi/launcher/tree/e15f6155cd34e82691291abc273678ef9e7ee880); [historical comparison](https://github.com/clockworkpi/launcher/compare/c4a12ce2d29b1694e1f7f13d89ae2451751a543c...e15f6155cd34e82691291abc273678ef9e7ee880).

| Area | Local source | Significance |
| --- | --- | --- |
| Session startup | [.cpirc](../../launcher/.cpirc), [.xinitrc](../../launcher/.xinitrc), [load.sh](../../launcher/load.sh) | Launches and connects Xorg, the UI, downloads, installer, notifications and window manager |
| Python runtime | [sys.py](../../launcher/sys.py/), [requirements.txt](../../launcher/requirements.txt) | Original UI implementation and legacy dependency assumptions |
| Menus and assets | [Menu](../../launcher/Menu/), [skin](../../launcher/skin/) | Built-in settings, games, application descriptors, graphics and themes |
| Update/install flow | [update.sh](../../launcher/update.sh), [appinstaller.py](../../launcher/sys.py/appinstaller.py), [aria2.conf](../../launcher/aria2.conf) | Application delivery and integration with an external menu checkout |
| Submodule | [.gitmodules](../../launcher/.gitmodules), `sys.py/pyaria2_rpc` | Pins an external Python aria2 RPC library, not initialized in the supplied checkout |
| Bundled executables | `aria2c`, `dwm-mod`, `sys.py/gsnotify/gsnotify-arm` | Architecture-specific runtime artifacts; no complete toolchain follows from their inclusion |

`git submodule status` reports `-b554bce52720629420238c3813f72a4c6554917a sys.py/pyaria2_rpc`; the leading minus denotes an uninitialized submodule. The launcher imports it from configuration, so this clone alone is not a complete runtime. It was left unchanged for source assessment. The README also places the launcher under `/home/cpi/apps/launcher`, whereas the session scripts use `/home/cpi/launcher`; deployment needs to reconcile that disagreement. [Submodule declaration](../../launcher/.gitmodules); [import](../../launcher/sys.py/config.py); [README](../../launcher/README.md); [session script](../../launcher/.xinitrc).

The follow-up [Python launcher assessment](05-python-launcher.md) examines this checkout, its evolution since the pre-v0.5 baseline, integration gaps and reuse potential. The historical software report remains useful for the January 2020 session reconstruction.

## What the local repositories still do not establish

These boundaries define the limits of what can be concluded from the supplied repositories:

- The Python launcher is now available locally and assessed. Its external aria2 RPC submodule is uninitialized, and its scripts expect additional services and application directories that the clone does not provide. [Local assessment](05-python-launcher.md).
- There is no extracted shipped root filesystem or installed-package manifest here. Repository documentation cannot establish every package, service, credential setting or firmware file actually present on the user's SD card.
- There is no complete Linux source checkout or complete U-Boot source checkout here. Patches and binaries are evidence of board support, not a self-contained toolchain and source supply chain.
- There is no complete image construction pipeline in these three tracked trees. Building the Go executable does not produce a flashable OS.
- There is no connected-device inventory, boot log or hardware measurement. The user's board revision, installed OS changes, battery condition and peripheral behavior remain unknown.

The first four findings are based on the tracked trees and linked documentation; the last is a boundary of this investigation. Later community and upstream projects may fill some of these gaps; see the ecosystem report.

## How to interpret the reports

Use schematics and source for precise implementation claims; use release announcements for what a maintainer says was shipped; use product pages for advertised specifications. A current source tree, a historical disk image, and the user's installed system are three different objects. Evidence about one is not automatically evidence about the others.

Local file links resolve relative to `GameShellNeo/docs` in the current workspace. Pinned GitHub links preserve the source version when reports are shared separately. Dates on Git commits are repository metadata; forum edit dates, download timestamps and image release dates can differ. Claims about real-device performance, runtime reliability and full hardware support require later testing.

This investigation changes only the documentation destination. No original repository was updated, no image was flashed, and no launcher or firmware was installed. The detailed reports identify potential reuse and open questions; they do not select an architecture for GameShellNeo before the next round of guidance.
