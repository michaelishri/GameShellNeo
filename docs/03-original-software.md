# Original software and launcher architecture

Research date: 27 September 2026. This is a source analysis, not a claim that the owner's microSD card matches a particular repository revision. No image was downloaded or booted, no device was accessed, and no launcher was built or executed.

Follow-up: the owner has now cloned [launcher locally](../../launcher/) at the same `e15f6155cd34e82691291abc273678ef9e7ee880` snapshot initially examined online. See [the dedicated local assessment](05-python-launcher.md) for current-tree findings and changes since the historical baseline. The January 2020 reconstruction below intentionally remains tied to its historical commit.

## Findings that shape the project

The software is a collection of a board-specific Linux stack, a conventional Linux desktop/session, a small-screen launcher, and externally installed games and services. The launcher is not the operating system. Rebuilding it alone would leave the kernel, display, networking, power management, distribution packages, and image assembly unresolved. The local `GameShell` repository supplies kernel patches and hardware artifacts; `LauncherGoDev` supplies an application, not a complete image build system. [S1], [S2], [S3]

The official image listing confirms **Clockwork OS v0.5, 4 January 2020, 32-bit, Linux 5.3.6**, with a 1.8G compressed download. This supports the reported age of the published image. It does **not** mean all source development ended then: the kernel tree contains 5.15.y patches, and the Go launcher has 2023 changes plus later maintenance commits. [S1], [S3], [S4]

Later v0.6 gamma development also means the v0.5 README entry should not be treated as the complete post-2020 release history; see [release history and ecosystem](04-release-history-and-ecosystem.md) for the publication evidence.

There are **two launcher lineages**, both predating 2020: Python/Pygame and Go/SDL2. Local Go history begins on 5 June 2018. The Python code immediately preceding the image release already provides a setting to switch to LauncherGo by editing `~/.bashrc` and rebooting. The current local Go code should therefore be treated as a later revision of an existing alternative, not proof of what shipped in the 2020 image. [S4], [S5], [S6]

## Evidence and historical boundaries

| Source | Revision examined | What it establishes |
|---|---|---|
| Local `GameShell` | `523cf591e2f955d001d257d7c850406f9fd917eb` | Official image listing, kernel patch series and bundled board artifacts. |
| Local `LauncherGoDev` | `b10fa7ab346f43bb89759cb8c558f12ed7590004` | Current checked-out Go source. HEAD is a 26 August 2026 dependency-update merge. |
| Historical Go source, from local Git history | `a48189030409a17ca785921103152f56c21da849` | Latest reachable commit before 5 January 2020; dated 2 July 2019; configuration reports version 0.22. |
| Local `launcher` (initially examined via a temporary external clone) | `e15f6155cd34e82691291abc273678ef9e7ee880` | Current upstream snapshot examined; commit dated 3 January 2023. |
| Historical Python source, from that repository's Git history | `c4a12ce2d29b1694e1f7f13d89ae2451751a543c` | Latest reachable commit before 5 January 2020; dated 2 January 2020; configuration reports `stable 1.25`. |

Historical commits were selected by Git commit time, not by an image manifest. Their inclusion in the image remains unverified. Immutable source links below identify the actual revisions used; paths into the local repositories are also included for practical navigation. [S4], [S5], [S6], [S7]

## Operating system and boot/session structure

### Kernel and boot artifacts

The local board repository is a sequence of support drops rather than one reproducible OS tree:

- The main kernel README documents patching Linux **4.14.2**, building with a Linaro ARM hard-float toolchain, and wrapping the kernel with `mkimage` into a U-Boot `uImage` at address `0x40008000`. [S2]
- `CPI3_linux_4.20` contains a 4.20 patch and prebuilt kernel/device trees; `v0.4` contains `52rc4.patch`, U-Boot binary, and bootloader flashing instructions. These coexist with the v0.5 image listing, whose kernel is 5.3.6. Folder names should not be interpreted as one-to-one image manifests. [S1], [S8]
- `v0.6` documents Linux **5.15.y** at exact base commit `5827ddaf4534c52d31dd464679a186b41810ef76`, followed by seven patch files covering configuration, device tree, display, logo, power, sound and Wi-Fi. The patch folder alone does not establish a published image or its kernel version; the gamma maintainer later reported reverting the image to Linux 5.3.6 after display and stability problems. See the companion report for that first-party discussion. Later v0.6 gamma work is covered in [release history and ecosystem](04-release-history-and-ecosystem.md). [S3]

Kernel changes and launcher expectations form a compatibility contract. The launcher writes `/proc/driver/backlight` and `/proc/driver/led1` and reads `/sys/class/power_supply/axp20x-battery/uevent`. The 5.15 patch set retains custom display/power driver work, including procfs interfaces. A modern kernel cannot be assumed to expose these exact paths or semantics merely because the SoC boots. [S3], [S9], [S10]

### Reconstructed historical desktop startup

The January 2020 Python repository’s [.cpirc](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.cpirc) and [.xinitrc](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.xinitrc) show this sequence; steps before `.cpirc` are outside the examined evidence:

```text
Login/profile integration (not fully represented here)
  → .cpirc, gated by /tmp/autologin
      → MPD, using ~/.mpd.conf
      → startx loop, selecting LCD versus HDMI from fb0 modes
          → .xinitrc
              → aria2 download daemon
              → feh wallpaper
              → Python appinstaller
              → load.sh → python sys.py/run.py
              → gsnotify notification process
              → modified dwm window manager
```

`.cpirc` selects `.xorg.conf` or `.xorg_lima.conf` according to `~/.lima`. The former requests `fbturbo` on `/dev/fb0`; the latter requests Xorg `modesetting`. The LCD session runs `dwm-mod -w`; HDMI uses `dwm-mod` and a desktop background. AwesomeWM and twm alternatives appear as commented commands, so their presence must not be mistaken for the active path in this snapshot. [S11]

The historical code therefore supplies a fairly complete **user-session recipe**, but not the complete boot chain or root filesystem assembly. Exact distro release, installed package revisions, system services, sudo policy, partition layout, U-Boot environment, and the owner's modifications still require image or device inspection. The README also describes `.mpd_cpi.conf` while `.cpirc` starts `.mpd.conf`, illustrating why documentation alone is insufficient to reconstruct a working installation. [S11], [S12]

## Python launcher

The original launcher uses Pygame, D-Bus/GLib, Wicd, ALSA-related packages and MPD. Its entry point imports Python 2-era modules such as `commands` and `gobject`; the launcher script runs an unqualified `python`. This is a substantive runtime migration issue, not just a shebang change. Its requirements file is unpinned and not a complete operating-system dependency manifest. [S12], [S13]

Its menu architecture reads `../Menu` and `/home/cpi/apps/Menu`. Application launches replace the launcher with a shell command that runs the game and then restarts the Python UI. The graphics session and background services remain outside that launcher process. State such as selected button layout, skin and power mode is stored through files and configuration under the user's home and launcher tree. [S13], [S14]

The historical launcher already includes settings for networking, Bluetooth, sound, brightness, language, power, time, storage, cores, skins, updates, notifications, Lima and switching to Go. The code is valuable as a functional reference and migration inventory, even if GameShellNeo chooses a different implementation. Its repository contains a GPLv3 license file; third-party code and bundled assets still need an individual provenance inventory. [S5], [S15]

## Go launcher: detailed local architecture

### Build and dependencies

The inspected tree has **196 tracked files, including 111 Go files**. `go.mod` declares Go 1.17, `go.sum` records dependency checksums, and `build.sh` runs `go build -ldflags="-s -w" -o launchergo main.go mainscreen.go`. `deploy.sh` simply copies the binary to `/home/cpi/launchergo`. Neither script assembles an OS or deploys all runtime assets. [S16]

The important dependency groups in the [module manifest](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/go.mod) are:

| Group | Evidence in `go.mod` / source | Role |
|---|---|---|
| Graphics | `cuu/gogame`, `veandco/go-sdl2` | Pygame-like rendering wrapper, SDL2 surfaces/events/fonts. |
| Settings/services | `godbus/dbus`, `muka/go-bluetooth`, `cuu/wpa-connect`, `itchyny/volume-go` | D-Bus, Bluetooth, wireless and audio integration. |
| Music | `fhs/gompd/v2` | MPD client. |
| Downloads | `cuu/grab`, `zyxar/argo` | Direct downloads and aria2 RPC. |
| Persistence/configuration | `go-ini/ini`, `mattn/go-sqlite3` | Menu/action configuration and task/network database. |

These are not all pure-Go deployment assumptions: SDL and SQLite bindings, runtime command-line tools, fonts, images and services are part of the environment. The current tree is not a self-contained static executable. Native build prerequisites were not installed or tested in this research. The README's `go get -u` recipe also differs materially from a dependency-pinned build based on the checked-in module files. [S16], [S17]

No tracked tests, CI workflow, root license file or `load.sh` were found in the examined Go tree. These are bounded repository observations, not claims about upstream private infrastructure. The missing `load.sh` matters because `update.sh` explicitly invokes it. [S16], [S24]

### Rendering and controls

The UI fixes its logical dimensions at **320 × 240**, with 80 × 80 icons. `main.go` initializes display and fonts, creates the main screen/title/footer, loads menu directories, registers custom events, and processes keyboard events with an SDL delay of 20 ms. Background goroutines handle LED blinking, idle power behavior and status refresh. This event delay is not a measured frame rate. [S10], [S18]

GameShell buttons are keyboard events: arrows navigate, Escape is Menu, U/I/J/K map to X/Y/A/B, Return is Start, and H/L represent the outer Lightkey positions. The alternative PC layout maps face buttons to their letters. This preserves an important cross-application boundary: keypad firmware, SDL naming, launcher bindings and RetroArch bindings must agree. [S19]

PNG assets, TTF fonts and language INI files are filesystem resources. The included languages are English, Japanese, Simplified Chinese, Traditional Chinese and Spanish. Several UI layouts use explicit pixel coordinates and named fonts, so replacing fonts or scaling the display is not automatically layout-safe. The default skin and translations are reusable references, subject to asset licensing review. [S20]

### Menu, plugins and process lifecycle

`mainscreen.go` recursively discovers the built-in `Menu` tree and `/home/cpi/apps/Menu`, sorts numeric filename prefixes, and merges multiple `20_Retro Games` collections. It recognizes scripts, emulator `action.config` entries and `plugin.json` packages. Built-in settings, Warehouse, PICO-8, music, TinyCloud and power pages are imported into the executable. An external Go plugin can also be loaded using `plugin.Open` and an `APIOBJ` symbol implementing the UI interface. External plugins are executable code, not declarative or isolated extensions. [S21]

Launching a game posts a custom event, shuts down the launcher graphics, constructs `/bin/sh -c` commands, starts a child process, and exits the launcher. The command chains a launcher restart after the game. This reduces simultaneous launcher/game UI activity but tightly couples shell quoting, executable paths, working directories and restart behavior. Preserving return-to-menu behavior is a specific migration requirement. [S10], [S21]

### Emulator and game integration

The launcher is a front end, not an emulator implementation. The local action files define these integrations: [S22]

| Menu | Runner | Recognized content / provisioning |
|---|---|---|
| MAME | RetroArch + `mame2003_plus_libretro.so` | ZIP ROMs; excludes `neogeo.zip` from the game list. |
| MGBA | RetroArch + `mgba_libretro.so` | `gb`, `gbc`, `gba`, `gbx`. |
| NESTOPIA | RetroArch + `nestopia_libretro.so` | ZIP and NES files. |
| Pcsx | Standalone `pcsx` binary | Disc/image formats including BIN/CUE/PBP/M3U. |
| CaveStory | RetroArch + `nxengine_libretro.so` | External game data under `/home/cpi/games/nxengine`. |
| freeDM | `chocolate-doom` | External `freedoom1.wad`. |
| PICO-8 | External commercial-package executable | Path under `/home/cpi/games/PICO-8`; presence of a menu does not grant redistribution rights. |

`action.config` supplies ROM location, runner/core, extensions, title, exclusions and optional download URL. Local RetroArch configuration can override per-emulator settings. Favorites use Unix group `cpifav`, GID 31415, by changing ROM group ownership; this is an unusual persistence mechanism that backup and migration tooling must account for. Neither menu presence nor a linked binary establishes performance, accuracy, BIOS availability or license compliance. [S22], [S23]

### Downloads and updates

There are two separate distribution paths:

1. The UI updater fetches `launchergo_ver_2023.json` from `clockworkpi/CPI`, compares its `gitversion` with the installed checkout, and launches `update.sh`. [That script](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/update.sh) performs `git pull`, `git reset --hard` to the supplied version, changes the background, and invokes the absent `load.sh`. It does not build the Go source. The field is passed through a shell command, and no signed release manifest verification is visible in this path. This is an in-place checkout updater, not an atomic OS update or rollback system. [S9], [S24]
2. Emulator downloads fetch archives and extract using `unzip`/`tar`. Warehouse uses an index at `clockworkpi/warehouse`, aria2 RPC, and a separate `appinstaller` executable with SQLite task, warehouse and Wi-Fi tables. Installer notifications unpack launcher archives or copy PICO-8/TIC-80 content to predetermined directories. No archive signature or expected digest check is visible in these inspected download/install paths. Module checksums in `go.sum` do not cover those runtime downloads. [S25], [S26]

The Python updater is similar but also updates a submodule and the external application-menu checkout. Its metadata request explicitly disables TLS certificate verification (`verify=False`), which is a concrete defect in the historical path. These updater details are reasons to redesign software delivery before offering GameShellNeo updates, not reasons to run the old scripts during research. [S27]

## Services, privileges and portability

| Area | Code's assumptions | Consequence for a revival |
|---|---|---|
| Network | Current Go Wi-Fi page uses wpa-connect plus `nmcli`; legacy Wicd code remains in the tree. Interface defaults to `wlan0`. | Choose one supported network-control contract; directory names alone do not identify the active backend. [S9], [S28] |
| Audio | MPD Unix socket `/tmp/mpd.socket`; ALSA utilities and volume control. | Include service configuration and mixer behavior in acceptance testing. [S9], [S12], [S29] |
| Power | Direct custom procfs writes; idle dim/off/countdown; `sudo halt -p`, `iw` and `rfkill`. | Distinguish blanking from suspend; observed code does not establish working suspend-to-RAM. [S10], [S29] |
| GPU selection | Moves Xorg driver `.so` files, edits an ARM library configuration and runs `ldconfig`, then reboots. | This is coupled to a historical installation layout, not a portable modern Mesa selector. [S30] |
| User/storage | `/home/cpi`, `cpifav`, mutable state within launcher directories, home-relative database. | Paths, permissions and state ownership need explicit migration treatment. [S9], [S17], [S23] |
| Sharing | TinyCloud displays SSH/SCP, Samba shares, AirPlay and USB Ethernet address `192.168.10.1`. | This page documents expected services; it does not itself configure or start them. [S31] |

The code contains tangible security and correctness concerns that should be carried into requirements:

- The documented account/password is `cpi`/`cpi`; TinyCloud repeats it. Actual device credentials and network exposure were not checked. [S17], [S31]
- Go Wi-Fi code prints the password, logs the full connection command, stores passwords in a SQLite `pass` column, and interpolates SSIDs/passwords into a shell command. Spaces and shell metacharacters can affect behavior; this requires structured process arguments and deliberate credential handling. No exploit was executed. [S28]
- Historical `aria2.conf` enables RPC, listens on all interfaces, allows all origins and supplies no RPC secret. If deployed as written without another access control, it exposes download control beyond localhost. The running device's firewall and effective configuration are unknown. [S32]
- Installers treat downloaded archives and shell-launchable menus as trusted executable content. An installer guard checks `len(parts) < 1` after splitting a URL, but then indexes `parts[1]`; an unexpected URL lacking the expected hostname can panic. These are source-level findings, not penetration-test results. [S25], [S26]

## Reuse assessment and open questions

**Strong reference material:** menu/action conventions, button mappings, small-screen interaction, hardware control interfaces, emulator paths, localization assets, and service expectations. These capture the original experience in implementable detail. **Conditional reuse:** application and kernel code require build verification, dependency and license review, and decisions about replacing legacy interfaces. **Not established:** an auditable full-image build, actual installed image inventory, modern kernel functionality, emulator performance or a safe update mechanism. [S1], [S10], [S16], [S22], [S24]

Before choosing an implementation, the most useful additional evidence would be:

1. A read-only inventory or backup of the owner's card: image/version identifiers, partition map, boot files, package list, active services, kernel command line, device tree, user changes and launcher revision.
2. An official v0.5 image manifest or an offline inspection of the image to resolve distro release, exact package/core versions, initialization units and binaries missing from the source trees.
3. On-device validation of display, HDMI, input, audio, wireless, battery reporting, charging, idle behavior and shutdown against any proposed replacement kernel/userspace.
4. Provenance and redistribution terms for Go code, fonts/artwork, firmware, emulator binaries and game assets. The Python GPL file does not automatically license the separately published Go repository.

These are outstanding research/validation boundaries, not an implementation plan or a request to modify the device.

## Sources

Local source roots: [GameShell](../../GameShell/) and [LauncherGoDev](../../LauncherGoDev/). Immutable links identify the exact revisions examined. Directory links support claims about tree contents; individual source files support behavioral claims.

[S1]: https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/README.md
[S2]: https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/Code/Kernel/README.md
[S3]: https://github.com/clockworkpi/GameShell/tree/523cf591e2f955d001d257d7c850406f9fd917eb/Code/Kernel/v0.6
[S4]: https://github.com/clockworkpi/LauncherGoDev/commits/b10fa7ab346f43bb89759cb8c558f12ed7590004/
[S5]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/Menu/GameShell/10_Settings/LauncherGo/__init__.py
[S6]: https://github.com/clockworkpi/LauncherGoDev/blob/a48189030409a17ca785921103152f56c21da849/sysgo/config.go
[S7]: https://github.com/clockworkpi/launcher/commits/e15f6155cd34e82691291abc273678ef9e7ee880/
[S8]: https://github.com/clockworkpi/GameShell/tree/523cf591e2f955d001d257d7c850406f9fd917eb/Code/Kernel
[S9]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/config.go
[S10]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/main.go
[S11]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.xinitrc
[S12]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/README.md
[S13]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/sys.py/run.py
[S14]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/sys.py/config.py
[S15]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/LICENSE
[S16]: https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004
[S17]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/README.md
[S18]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/UI/constants.go
[S19]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/UI/keys_def.go
[S20]: https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004/skin/default
[S21]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/mainscreen.go
[S22]: https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell
[S23]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/UI/Emulator/rom_list_page.go
[S24]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell/10_Settings/Update/update_page.go
[S25]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/UI/download_process_page.go
[S26]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/appinstaller/app_notifier.go
[S27]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/Menu/GameShell/10_Settings/Update/__init__.py
[S28]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell/10_Settings/Wifi/wifi.go
[S29]: https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell/10_Settings
[S30]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell/10_Settings/Lima/gpu_driver_page.go
[S31]: https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell/98_TinyCloud/tiny_cloud_page.go
[S32]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/aria2.conf

Additional exact files for combined claims:

- [Login/session startup](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.cpirc)
- [Framebuffer Xorg configuration](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.xorg.conf)
- [Lima Xorg configuration](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.xorg_lima.conf)
- [Python launcher startup](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/load.sh)
- [Python requirements](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/requirements.txt)
- [Python update script](https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/update.sh)
- [Go dependency versions](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/go.mod)
- [Go module checksums](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/go.sum)
- [Go deployment script](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/deploy.sh)
- [Go update script and missing load.sh call](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/update.sh)
- [Installer database initialization](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/appinstaller/appinstaller.go)
- [Warehouse index and RPC integration](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/Menu/GameShell/21_Warehouse/ware_house_page.go)
- [Go plugin loading](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/UI/plugin.go)
- [Font initialization](https://github.com/clockworkpi/LauncherGoDev/blob/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/UI/fonts.go)
- [Translation files](https://github.com/clockworkpi/LauncherGoDev/tree/b10fa7ab346f43bb89759cb8c558f12ed7590004/sysgo/langs)
- [Custom kernel power interfaces](https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/Code/Kernel/v0.6/515_power.patch)
- [Custom kernel display interfaces](https://github.com/clockworkpi/GameShell/blob/523cf591e2f955d001d257d7c850406f9fd917eb/Code/Kernel/v0.6/515_display.patch)
