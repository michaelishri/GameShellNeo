# Python launcher: local source assessment

Research date: 27 September 2026. This supplements [the original software report](03-original-software.md) with direct inspection of the newly cloned [launcher repository](../../launcher/). The examined HEAD is `e15f6155cd34e82691291abc273678ef9e7ee880` (3 January 2023). Comparisons use `c4a12ce2d29b1694e1f7f13d89ae2451751a543c` (2 January 2020), the historical snapshot already discussed. Neither revision is a verified manifest of an installed OS image. No launcher, downloaded executable, installer or update script was run.

## What this repository adds

This is more than a graphical application: it preserves a user-session recipe, two Xorg configurations, a modified window-manager binary, a notification binary, a download daemon binary, game/menu adapters and hardware settings. It is consequently an especially useful record of how the original GameShell experience was assembled. It still does **not** supply a reproducible complete OS build. The inspected tracked tree has 325 entries, including 117 Python files and one Git submodule. These counts come from `git ls-files` at the revision above. [Source tree][tree]

The current code remains a **Python 2 application**. `load.sh` calls unqualified `python`; `run.py` imports `commands` and `gobject`, and its descriptor-cleanup routine explicitly requires `sys.platform == 'linux2'`. Other modules contain Python 2 exception and print syntax. Changing the interpreter name alone cannot port it. The version string remains `stable 1.25` in both snapshots, so that label cannot distinguish the 2020 and 2023 source. [Local entry point](../../launcher/sys.py/run.py), [configuration](../../launcher/sys.py/config.py), [skin manager](../../launcher/sys.py/UI/skin_manager.py); [immutable startup][run], [configuration][config], [skin manager][skin].

## Session and supporting binaries

The source describes the following startup sequence, conditional on another component having created `/tmp/autologin` and invoked `.cpirc`:

```text
.cpirc → MPD + repeating startx session
  .xinitrc → aria2 + wallpaper + Python appinstaller
           + load.sh → Python launcher
           + gsnotify + dwm-mod
```

`.cpirc` reads framebuffer modes, chooses LCD or HDMI session, and selects `fbturbo` or `modesetting` using `~/.lima`. It invokes `mpd ~/.mpd.conf`; the README instead gives instructions for `~/.mpd_cpi.conf`. Similarly, the README's directory diagram places the checkout under `~/apps/launcher`, while active startup/update scripts expect `~/launcher`. These are concrete reconstruction ambiguities: a fresh clone plus README is not a complete installation recipe. [Local login script](../../launcher/.cpirc), [session](../../launcher/.xinitrc), [README](../../launcher/README.md); [immutable login][cpirc], [session][session], [README][readme].

Both sessions start the installer and launcher in the background. LCD runs `dwm-mod -w`, whereas HDMI runs `dwm-mod` and passes `daemon` to gsnotify. AwesomeWM configuration is included, but its session command is commented out. Bluetooth firmware initialization is another separate shell script: it chooses `bcm43438a0.hcd` or `bcm43438a1.hcd` from `/proc/driver/brcmf_fw`, then invokes external `brcm_patchram_plus` on `/dev/ttyS1`, with a literal Bluetooth address. The script's presence does not establish where an image invokes it. [Local session](../../launcher/.xinitrc), [firmware script](../../launcher/bluetooth_firmware.sh); [session][session], [firmware][bluetooth].

Read-only `file` inspection identifies `aria2c`, `dwm-mod` and `sys.py/gsnotify/gsnotify-arm` as 32-bit ARM ELF binaries using `/lib/ld-linux-armhf.so.3`; gsnotify also carries a Go build ID. Their source/build recipes are not present alongside these executables. This checkout therefore cannot by itself reproduce all components it starts. Notably, the 2023 session invokes **`aria2c` from PATH**, while the historical session explicitly invoked `~/launcher/aria2c`. Replacing the bundled binary will not necessarily replace the binary the current session runs. [Local binary directory](../../launcher/), [notification directory](../../launcher/sys.py/gsnotify/); [current tree][tree], [current session][session], [historical session][oldsession].

## Dependencies and completeness

The README describes Pygame, Wicd, D-Bus/GLib, ALSA, Xlib, MPD, requests and additional Python packages. Its apt/pip recipe and `requirements.txt` disagree: requirements omit `requests` and `numpy`, specify `python-mpd` rather than the README's `python-mpd2`, comment out GObject and Wicd, and comment out beeprint as problematic. There are no version pins in this requirements file. Native libraries, Xorg, command-line utilities, firmware, services and privileges remain outside it. Treat it as dependency hints rather than a lockfile. [Local requirements](../../launcher/requirements.txt), [README](../../launcher/README.md); [requirements][requirements], [README][readme].

The sole submodule is `sys.py/pyaria2_rpc`, pinned to `b554bce52720629420238c3813f72a4c6554917a` from `cuu/pyaria2_rpc`. In this local clone, `git submodule status` begins with `-`, meaning it is uninitialized. `config.py` imports `Xmlrpc` from it at startup; `appinstaller.py` imports `Wsrpc`. Thus this specific checkout is incomplete for execution even before resolving the legacy runtime. The submodule was not initialized during research. [Local submodule declaration](../../launcher/.gitmodules), [installer](../../launcher/sys.py/appinstaller.py); [declaration][submodule], [pinned upstream submodule](https://github.com/cuu/pyaria2_rpc/tree/b554bce52720629420238c3813f72a4c6554917a), [configuration][config], [installer][installer].

The tree includes a GPLv3 license file, fonts, skin artwork and vendored Python libraries. A repository-level license is useful evidence but does not replace separate provenance checks for binaries, fonts, firmware or commercially licensed game engines. No tracked automated test suite or CI workflow was identified in this snapshot. [Local license](../../launcher/LICENSE), [tree][tree].

## Application architecture and extension contract

`run.py` owns Pygame initialization, a GLib main loop, keyboard processing, screen power state and process transitions. GLib timers poll Pygame events, blink the LED and refresh the title bar; background threads handle aria2 notifications and a Unix socket at `/tmp/gameshell`. This is not a standalone SDL event loop: Wicd/GLib/D-Bus are fundamental dependencies of the application's structure. `config.py` also does preparation during import, including reading settings and requesting wireless power-save changes. Importing modules is therefore not a safe substitute for static inspection. [Local application](../../launcher/sys.py/run.py), [configuration](../../launcher/sys.py/config.py); [application][run], [configuration][config].

The UI retains a logical 320 × 240 canvas and 80 × 80 icons. Current code recognizes framebuffer modes containing 640 × 480 or 480 × 640 and scales its canvas by two; it does not implement arbitrary responsive layout. The portrait-mode check also sets a 640 × 480 output surface, not a rotation transform. Actual behavior on such displays needs testing. Skin font paths and colors are configurable, while ten language INI files are present, including Russian added after the historical snapshot. [Local constants](../../launcher/sys.py/UI/constants.py), [render helper](../../launcher/sys.py/UI/util_funcs.py), [languages](../../launcher/sys.py/langs/); [constants][constants], [configuration][config], [render helper][util], [skin manager][skin], [tree][tree].

Menu discovery reads `../Menu` and `/home/cpi/apps/Menu`. Filenames provide ordering and display labels; `20_Retro Games` collections receive special merging behavior. A directory is classified in this order: Python package, emulator action configuration, commercial-package descriptor, matching shell-script package, otherwise nested menu. Standalone `.sh` files also become launchable entries. Python modules are imported dynamically and initialized using `Init(main_screen)`; selection invokes `API(main_screen)`. These are unrestricted in-process extensions, with access to launcher internals, rather than sandboxed plugins. [Local menu loader](../../launcher/sys.py/UI/main_screen.py), [page dispatch](../../launcher/sys.py/UI/page.py); [loader][menu], [dispatch][page].

Emulator `action.config` fields include `ROM`, `ROM_SO`, `EXT`, `EXCLUDE`, `FILETYPE`, `LAUNCHER`, `TITLE` and `SO_URL`, with an optional `retroarch-local.cfg`. The parser splits text on `=` rather than implementing a general configuration format, so extensions should preserve its actual limitations. Commercial packages use `compkginfo.json` and a `.done` marker. These menu contracts are useful compatibility targets even if GameShellNeo replaces the Python UI. [Local loader](../../launcher/sys.py/UI/main_screen.py), [commercial handler](../../launcher/sys.py/UI/CommercialSoftwarePackage/__init__.py); [loader][menu], [commercial handler][commercial].

Normal game launch closes Pygame and the GLib loop, releases selected file descriptors, and replaces the process using `/bin/sh -c`. The constructed command runs the selected application and then `exec python run.py` to return to the launcher. This makes working directories, quoting, inherited environment and restart behavior part of the compatibility contract. It also means launcher-owned idle timers do not continue operating while that process is replaced by a game; independently running session services are separate. [Local process handling](../../launcher/sys.py/run.py); [process handling][run].

## Input, state and hardware contracts

Buttons produce keyboard events: arrows navigate; Escape is Menu; Space is Select; Return is Start; U/I/J/K provide face buttons; H/L are outer Lightkey positions. Xbox/SNES layout changes remap face-button meanings. Keypad plus/minus control the volume overlay. The mapping is shared behavior to preserve across launcher, games and input firmware. [Local key definitions](../../launcher/sys.py/UI/keys_def.py); [key definitions][keys], [application][run].

State is scattered: `.buttonslayout`, `.powerlevel` and `.lang` live relative to `sys.py`; the skin path is in `~/.gameshell_skin`; installer SQLite files are `aria2tasks.db` and `warehouse.db` in its working directory. Favorites use ROM filesystem group ownership, with GID 31415 (`cpifav`), rather than a portable favorites database. Removal resets the group to the owner's numeric UID, assuming that UID and normal GID match. A future migration must preserve ownership metadata or explicitly convert favorites before copying ROMs. [Local config](../../launcher/sys.py/config.py), [language manager](../../launcher/sys.py/UI/lang_manager.py), [emulator](../../launcher/sys.py/UI/Emulator/__init__.py), [favorite list](../../launcher/sys.py/UI/Emulator/fav_list_page.py); [config][config], [language manager][lang], [emulator][emulator], [favorite list][favorites], [installer][installer].

Power handling writes `/proc/driver/backlight` and `/proc/driver/led1`, and battery reporting expects the axp20x power-supply path. Idle stages dim, blank and eventually initiate shutdown countdown; each transition resets its time base, so configured values are stage delays rather than three absolute deadlines since the last key. This code establishes display blanking, not suspend-to-RAM. The separate low-power notification job queries UPower, demonstrating that even battery information comes through more than one interface. [Local application](../../launcher/sys.py/run.py), [notification job](../../launcher/sys.py/gsnotify/Jobs/00_lowpower.sh); [application][run], [configuration][config], [notification job][lowpower].

Settings remain strongly tied to the original installation. Lima selection moves an Xorg driver file, edits the ARM library loader configuration, runs `ldconfig` and reboots. Switching launcher edits occurrences of `launcher` in `~/.bashrc` to `launchergo` and reboots. These are useful records of the old system's assumptions, but poor candidates for unchanged reuse on a redesigned OS. [Local Lima setting](../../launcher/Menu/GameShell/10_Settings/Lima/__init__.py), [launcher switch](../../launcher/Menu/GameShell/10_Settings/LauncherGo/__init__.py); [Lima][lima], [switch][switch].

## Delivery and correctness concerns

The updater still fetches metadata with `verify=False`, then interpolates the remote `gitversion` into a shell command. `update.sh` pulls and hard-resets the installed repository, initializes/updates its submodule and pulls `~/apps/Menu`. It provides no atomic deployment/rollback boundary. The newer guard on the external menu pull also means a missing or failing menu checkout can exit before `load.sh` restarts the UI. A separate legacy archive-update branch does call `add_hash_verification('md5', ...)` when its metadata supplies a 32-character digest; this should not be confused with the Git branch or Warehouse installer. Because that metadata request disables certificate verification, the digest does not authenticate its publisher. Quoting improvements since 2020 do not solve these structural problems. [Local update UI](../../launcher/Menu/GameShell/10_Settings/Update/__init__.py), [update script](../../launcher/update.sh); [update UI][updateui], [update script][update].

`aria2.conf` enables RPC on all interfaces, permits all origins and provides no RPC secret. If deployed as written without another control, download control is exposed beyond localhost. The installer consumes completion notifications, maps GitHub raw URLs to local paths and shells out to extraction/copy commands. It shows no signature or expected-digest verification in that installation path; malformed URLs are caught by a broad exception rather than validated before splitting. These are observed code/configuration properties, not a test of the owner's running device. [Local daemon configuration](../../launcher/aria2.conf), [installer](../../launcher/sys.py/appinstaller.py); [daemon configuration][aria], [installer][installer].

## Changes since the January 2020 snapshot and reuse judgment

The endpoint diff touches **25 files**, with 259 inserted and 68 deleted text lines plus binary replacements. Its substantive changes are canvas scaling, configurable skin fonts, Russian translation, MAC-address display, music-selection index fixes, PICO-8 package metadata, shell quoting/exit guards, aria2 binary replacement, PATH-based aria2 startup and gsnotify binary replacement. Wicd, Python 2, the menu model, updater architecture and `stable 1.25` version remain. These observations support continued maintenance after the original image date, but not a broad modernization or proof of any image's contents. [Immutable endpoint comparison][comparison]

For GameShellNeo, the strongest reuse candidates are the interaction model, menu/action format, artwork/localization subject to provenance review, and the detailed list of hardware/service behaviors. Direct code reuse would require a Python/runtime port, service and privilege redesign, dependency reconstruction, replacement or reproducible builds of bundled binaries, and safer delivery. The newly cloned repository materially improves the reference set, but does not close the outstanding image-build, installed-package or real-hardware validation gaps.

## Immutable sources

All current-source links below refer to the inspected HEAD. Local links above point to the actual clone; future edits can make them differ from this report.

[run]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/run.py
[config]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/config.py
[skin]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/skin_manager.py
[cpirc]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/.cpirc
[session]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/.xinitrc
[readme]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/README.md
[bluetooth]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/bluetooth_firmware.sh
[requirements]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/requirements.txt
[submodule]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/.gitmodules
[installer]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/appinstaller.py
[constants]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/constants.py
[util]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/util_funcs.py
[menu]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/main_screen.py
[page]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/page.py
[commercial]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/CommercialSoftwarePackage/__init__.py
[keys]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/keys_def.py
[lang]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/lang_manager.py
[emulator]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/Emulator/__init__.py
[favorites]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/UI/Emulator/fav_list_page.py
[lowpower]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/sys.py/gsnotify/Jobs/00_lowpower.sh
[lima]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/Menu/GameShell/10_Settings/Lima/__init__.py
[switch]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/Menu/GameShell/10_Settings/LauncherGo/__init__.py
[updateui]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/Menu/GameShell/10_Settings/Update/__init__.py
[update]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/update.sh
[aria]: https://github.com/clockworkpi/launcher/blob/e15f6155cd34e82691291abc273678ef9e7ee880/aria2.conf
[tree]: https://github.com/clockworkpi/launcher/tree/e15f6155cd34e82691291abc273678ef9e7ee880
[oldsession]: https://github.com/clockworkpi/launcher/blob/c4a12ce2d29b1694e1f7f13d89ae2451751a543c/.xinitrc
[comparison]: https://github.com/clockworkpi/launcher/compare/c4a12ce2d29b1694e1f7f13d89ae2451751a543c...e15f6155cd34e82691291abc273678ef9e7ee880
