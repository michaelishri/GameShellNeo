# GameShellNeo

This is the working handoff for agents on this project. Operational snapshot:
**22 October 2026, Pacific/Auckland**. Recheck Git, Kaneo and live evidence;
the snapshot below is a starting point, not admission for a hardware test.

## Project and owner decisions

- Revive the ClockworkPi GameShell as **GameShellNeo**, initially for the owner's
  **CPI v3.1** mainboard only. The Intel x86 Linux machine builds the image; the
  owner's M2 MacBook Air provides remote USB access, camera observations and
  SD-card flashing.
- Finish the low-level Linux/driver/power foundation before starting the UI.
  The current diagnostic stack uses locked Linux 6.18.54 and minimal Debian 13
  Trixie; read `build/sources.lock.json` in the selected branch for exact inputs.
  An LTS kernel and a small, documented patch set are acceptable. Vendor and
  ClockworkPi code are references rather than prescribed implementations.
- Product targets include reliable sleep/resume, configurable automatic sleep
  after two minutes of inactivity by default, ideally sub-second resume, a week
  or more asleep, cold boot under five seconds and eventual OTA updates. These
  are targets; existing debug/RTC tests do not establish all of them. Wi-Fi and
  Bluetooth may disconnect during sleep. Connecting USB while asleep should
  leave the device asleep and charging.
- Desired power-button behavior: a quick press sleeps/wakes; about two seconds
  requests power options; about eight seconds forces power off. Driver events
  may be changed to implement this. Do not confuse this desired policy with the
  currently installed diagnostic handlers or a retained test-owned key guard.
- The active goal is to work through Kaneo's in-progress tickets, complete as
  much software/preparation as possible before parking hardware dependencies,
  and leave a clear list of remaining physical actions. Closing one ticket does
  not complete that overall goal.

## Ethos

- Small cumulative optimizations are worthwhile there is no minimum percentage saving required
- When you discover issues unrelated to your current focus, note them down in `FOLLOW-UP.md` so they can be investigated at some other time

## Driver engineering

- Driver changes are authorized throughout GameShellNeo's agreed scope, including fixes, refactoring, extensions and replacements. Do not seek separate approval merely because a change belongs in a driver.
- Prioritize a stable, fast, power-efficient driver stack. Fix the underlying driver issue at the appropriate layer where practical rather than accumulating userspace workarounds, retries or delays that mask it.
- Treat existing upstream, vendor and ClockworkPi implementations as reference material, not prescribed code. Prefer maintainable upstream-compatible fixes when suitable, but do not preserve a defective design solely to avoid driver changes.
- If a hardware constraint or unresolved cause requires a temporary workaround, document the evidence, tradeoff and removal criteria, and track the underlying work in `FOLLOW-UP.md`.
- Validate changes with reproducible tests and relevant hardware qualification. Keep claims of stability, latency and energy savings tied to evidence; source-level improvements alone do not establish hardware results.

## Workspace and source of truth

- Workspace: `/home/mishri/workspace/clockworkpi`. Canonical project checkout:
  `/home/mishri/workspace/clockworkpi/GameShellNeo`. Read this canonical handoff
  as well as the selected worktree's instructions. Sibling ClockworkPi/vendor
  repositories and `allwinner/` contain reference code and supplied documents.
- Start with `git status --short`, `git branch --show-current`,
  `git log -5 --oneline` and `git worktree list`. Main includes the reviewed
  cumulative development through NEO-207. The thirteen source branch histories
  retained in report 288 are reconciled in reports 289–291; merged refs are
  cleaned only after publication while their source/evidence worktrees remain.
  A command, report or image present in one worktree may be absent or different
  in another. Select the intended source and image before rebuilding.
- Consult the ticket's current description/comments, `FOLLOW-UP.md`, the
  selected worktree's `README.md`, `Taskfile.yml`, and matching numbered reports
  under `docs/`. Reports record historical observations, not current health.
- Preserve unrelated owner edits and other worktrees. Stage explicit files;
  do not use destructive cleanup/reset or bulk staging to simplify your work.
  Do not edit the immutable `.sources/.../source` trees used by driver tests.
  Add fixes as maintained patches/candidates and regenerate through saved Tasks.

Current worktrees are under the canonical checkout's `.local/worktrees/`:

| Directory | Preserved revision / purpose |
| --- | --- |
| `musb-restart-integration` | `fa2a95d` (detached after branch cleanup): established remote/camera tools, diagnostic.26 image and NEO-192 clock investigation; use this checkout for current hardware access |
| `brcmfmac-tx-recovery` | `57a6c22` (detached): NEO-202 completed; Wi-Fi candidates through 0054 are offline-qualified and outside the image queue |
| `build-stage-ownership` | `0f53a71` (detached): completed NEO-194 implementation, independent reviews and original qualification evidence |
| `merge-ready-branches` | detached reviewed main integration with the repeated host checks and Docker ownership evidence recorded in report 288 |
| `remaining-branch-integration` | `057b50e`: frozen NEO-205 native/ARM and real-kernel retirement evidence; see report 289 |
| `remaining-extra-validation` | `057b50e` (detached): full ARM power-supply candidate and final Sunxi ownership fixture evidence |
| `remaining-smp-validation` | `057b50e` (detached): thirteen Docker ownership groups, two-CPU QMP smoke and eighteen-case four-CPU ARM SMP evidence; see report 290 |
| `remaining-legacy-integration` | code through `58eeadd` plus final report commits: independent wake/startup profile, six ARM configurations and mapped older histories; see report 291 |
| `remaining-legacy-validation` | `58eeadd` (detached): production sleep/callback regression and explicitly historical teardown reproduction |
| `remaining-final-integration` | final merge documentation and host checks; source/candidate receipts stay in the frozen validation worktrees above |
| `multiboot-boot-selection` | NEO-208 development SD systems; real directory boot/one-shot/recovery rollback pass; complete-metadata import needs NEO-209's capable maintenance bootstrap |
| `ext4-security-attributes` | NEO-209: enable ext4 security attributes and prepare diagnostic.27 / kernel26 through managed stages; original hardware worktree remains frozen |

Merged branch references are removed; their worktrees, ignored evidence and
private configuration remain at their original revisions. Create a branch
before making new commits in a detached worktree. Do not copy a feature's
validation claims onto another branch or image.

## Private configuration and identities

- Keep credentials and access endpoints in the canonical `GameShellNeo/.env`.
  Never print its contents, source it as shell code, paste secrets into chat,
  or commit filled values. `tools/private_config.py:load_env()` reads it as data.
  Existing environment variables with the supported prefixes can override file
  values; investigate overrides if configuration appears stale.
- The hardware integration worktree's `.env` is already a symlink to that
  canonical file. Its device key links to the canonical private key. Worktrees
  do not automatically share `.env`, known-host files, provisioning or images.
  Prefer the established hardware worktree rather than inventing another
  credential/key setup. Never overwrite an existing `.env` with a template.
- Relevant configuration keys, with values kept private:

  | Keys | Purpose |
  | --- | --- |
  | `M2_MACBOOK_AIR_IP`, `M2_MACBOOK_AIR_TAILNET` | Mac SSH identity address and preferred tailnet transport endpoint |
  | `M2_MACBOOK_AIR_USERNAME`, `M2_MACBOOK_AIR_PASSWORD`, `M2_MACBOOK_AIR_KEY` | Mac account/authentication; use the configured mechanism |
  | `M2_MACBOOK_AIR_SUDO_PASSWORD` | Optional separate Mac sudo password; helper otherwise uses the configured SSH password |
  | `GAMESHELL_IP`, `GAMESHELL_USB_IP`, `GAMESHELL_USERNAME`, `GAMESHELL_WIFI_VIA_MAC` | Board addresses/account and whether Wi-Fi SSH also tunnels through the Mac |
  | `GAMESHELL_WIFI_SSID`, `GAMESHELL_WIFI_PSK`, `GAMESHELL_WIFI_COUNTRY` | Current radio configuration |
  | `NEO_SSH_KEY`, `NEO_HOST_PUBLIC_KEY` | Device SSH client key and provisioned device host public key paths |
  | `NEO_CAMERA_NAME` | Exact camera selection; currently `Razer Kiyo` |

- Mac host keys are checked against existing known-host records. Device host
  identity is pinned to the provisioned Ed25519 public key. Preserve those
  checks; investigate changes instead of deleting keys or disabling validation.

## MacBook and GameShell remote access

- Access chain: **Intel host → Mac SSH over LAN/tailnet → GameShell over USB
  Ethernet or the Mac's local Wi-Fi**. The Intel machine need not reach the
  board's Wi-Fi network directly. The Mac must be open, awake, logged into its
  desktop and reachable; keep it powered for unattended work.
- `tools/remote.py:connect_mac()` prefers `M2_MACBOOK_AIR_TAILNET` for transport
  when configured, while retaining the configured Mac identity for host-key
  checks. Its `device()` helper uses a Mac SSH TCP forward for USB, and for
  Wi-Fi when `GAMESHELL_WIFI_VIA_MAC=1`. Ordinary SSH access remains authorized.
- Run these **from `musb-restart-integration`**, where the matching private
  identity and camera tooling are already available:

  ```sh
  task mac:status
  task device:status ROUTE=usb
  task device:status ROUTE=wifi
  task device:exec ROUTE=usb -- uname -r
  task mac:usb-inspect
  ```

  Status/inspection are read-only. `device:exec` can run arbitrary commands;
  assess the command's actual effects rather than treating the Task as harmless.
- For additional Mac operations, reuse `connect_mac()`, `run()` and `load_env()`
  from the existing helpers. Add recurring operations to `Taskfile.yml` instead
  of rebuilding one-off access/build scripts or embedding credentials.
- Mac Remote Login must be enabled. Raw-card access over SSH has previously
  needed “Allow full disk access for remote users” in Remote Login settings.
  Camera access belongs to the installed GameShellNeo Camera app. If access
  fails, report the actual failing layer/permission rather than asking the
  owner to repeat all setup steps.
- A working charge connection does not prove a USB data connection. The owner
  uses a USB-A-to-C adapter; a suitable data cable has been verified. Mac sleep,
  cable reattachment and board reboot affect evidence and must be recorded.
- For a network change, the owner updates `.env` and connects the Mac to the
  same network. With USB still available, `task device:wifi-config` provisions
  those credentials, applies them over USB, verifies Wi-Fi SSH and updates the
  board address. This changes configuration; do not run it just to inspect.
- The radio needs an available compatible 2.4 GHz network. The PXL10 hotspot
  has been used when home/office Wi-Fi was unsuitable; keep the hotspot enabled
  and both devices nearby. Confirm the actual configured country; do not infer
  it from timezone or location. The owner previously accepted an AP's AU country
  announcement after moving from Australia to New Zealand.
- Before a large image transfer, confirm regular Wi-Fi rather than assuming a
  mobile hotspot is unmetered. Do not reuse an old answer after a location or
  network change. The helper's current address/configuration is authoritative.

## Camera observations

- The owner prefers the external **Razer Kiyo** (sometimes called “Razor” in chat).
  Use the exact `NEO_CAMERA_NAME='Razer Kiyo'` preference in `.env`. The helper
  discovers built-in/external devices and requires one exact match; do not
  silently substitute the FaceTime camera. Current hardware tooling is in
  `musb-restart-integration`; main now contains the same reviewed camera helper.
- Use camera observations for tests needing only visual confirmation of screen
  state/return, without another human-ready/confirmation exchange. Existing
  test authorization and health admission still apply. The camera cannot
  override a failed preflight. Report 268 in the integration worktree documents
  Kiyo setup; report 166 documents the original built-in setup.
- Keep the Mac open, awake and logged into its desktop, with the GameShell screen clearly in view. If positioning changes, inspect a fresh baseline image before relying on the camera. Tests that sleep the Mac need another observer.
- From the repo, run `task mac:camera-status` to read permission without opening the camera, `task mac:camera-capture` for a still, or `task mac:camera-capture SECONDS=30 FPS=2` for a sequence. Sequences accept 1–300 seconds and 1–5 exported frames per second. Reuse the installed app; run `task mac:camera-setup` if setup is missing or helper source changes. Rebuilding may require macOS permission again.
- For an authorized hardware test, start a sequence first and wait for the readiness message, which follows the first saved image and exposure settling. Then perform the test while capture continues. Camera commands alone do not initiate GameShell sleep, reboot or other device changes.
- Inspect the actual JPEGs and session results under ignored `.local/diagnostics/<capture>/`. Record the observed screen state and confirm successful capture and camera shutdown. The helper captures video only, runs on demand and stops after the bounded capture; no microphone, login item or persistent camera service is used. Successful downloaded captures are removed from the Mac; failed or interrupted captures remain there for diagnosis. Keep raw images private and out of Git.
- An obscured, unreadable or missing image is inconclusive. A lit screen alone does not establish application responsiveness, input or network recovery; verify those separately. Camera frame timestamps do not qualify sub-second resume targets or power consumption. USB unplugging, SD-card swaps and other physical actions still require the owner.

Quick check after reconnection:

```sh
task mac:camera-status
task mac:camera-capture SECONDS=5 FPS=2
```

Inspect the actual first/last JPEGs with the image-viewing tool, not just the
JSON success flag. A five-second, 2 FPS sequence should yield ten frames. Check
`result.json` for the requested camera, success and `camera_stopped: true`.
Use the filenames from its frame list; the current helper starts at
`frame-000001.jpg`. Save a concise private `visual-observation.json` when needed.
Images, logs and receipts stay under the ignored capture directory.

Reuse the installed app at `~/.local/share/GameShellNeo/camera/GameShellNeo Camera.app`.
Rebuilding unnecessarily can change its permission identity.
`task mac:camera-setup` is for a missing setup or changed helper source, not a
routine reconnect. No microphone, background camera service or persistent
recording is authorized by this workflow. The camera stops after each request.

## Hardware gates and evidence

- NEO-208 is **development only**; the owner explicitly excludes this card
  selector from the final release. [Report 292](docs/292-development-sd-systems.md)
  and `development/multiboot/README.md` describe the opt-in card/bundle Tasks.
  The initial Samsung DEV-spare reflash, full readback and owner card movement
  are complete. Diagnostic.26 directory boot, real flag consumption/readback,
  automatic return to fixed recovery and both SSH routes pass. Remote import
  failed closed on a missing `security.capability` xattr: both original kernels
  disable `CONFIG_EXT4_FS_SECURITY`. NEO-209 prepares a capable maintenance
  system; bootstrap, complete import and confirmation remain open. Consult
  report 292 and the live
  evidence before selecting a system. Future flashes still require fresh
  DEV-spare identity, owner card movement/readiness, a current-network transfer
  check and full guarded readback.
  Use the new checkout's Mac helper with explicit `NEO_HARDWARE_CHECKOUT` and
  `NEO_DEVELOPMENT_TRANSFER` to retain established credentials/known-host checks;
  do not overwrite private configuration or production transfer/checkpoints.
  Directory deployments need separate clock/PM provenance admission. New PM
  tooling rejects them; frozen older worktrees retain their historical guards
  and must not be used to bypass this. Flag readback does not establish FAT
  power-cut safety or a reset for a complete kernel hang.
  Use canonical lowercase `next.scr`, `good.scr`, `recover.scr` on `vfat` with
  `shortname=mixed`. The initial uppercase-entry failure and SSH repair are
  preserved. Development-r3 fixes FAT flags but still has the incapable old
  kernel; wait for the capable bootstrap artifact before another physical
  flash. Retain development-r2 as the original failed candidate. Do not repair an old uppercase entry with
  atomic replacement alone: the FAT metadata can retain its uppercase name.

- **NEO-154's SSH-stall investigation was abandoned at the owner's request.**
  Do not reopen it or run the old SSH trace/stall experiments merely because
  their Tasks remain in the tree. Normal remote access/status is still used.
- **NEO-192 remains unresolved:** a battery-guard clock regression and later
  raw-clock evidence block fresh PM qualification. Do not clear restart/PM
  counters, clamp clocks, reboot past the fault or silently replace runtime
  tools to obtain a pass. Preserve the original failures. NEO-191 camera PM
  qualification and NEO-182 battery RTC trial remain dependent on this work.
- Diagnostic.26's original raw image remains built/offline-verified in
  `musb-restart-integration`; `docs/272-clock-provenance-image.md` records its
  image/reader/build-ID pins and recovery checkpoint. Its extracted root now
  boots on the DEV card with explicit `development-directory` provenance;
  report 292 records the exact root inode, markers, source hashes and kernel.
  This deployment needs its own clock/PM adapter and matching awake admission
  before advancing NEO-192. Do not infer pristine-image admission from a login
  banner or reuse the original raw-image checks against the directory root.
- Latest completed selector checks (22 October): diagnostic.26 boot
  `6d4ee9eb-1dcd-4adc-af47-1e340e88d123`, kernel
  `6.18.54-gameshellneo25`, consumed its trial and returned on the next warned
  reboot to fixed recovery boot `9caf10b6-a94f-4c9b-8ca9-e8e6c1580cab`, kernel
  `6.18.54-gameshellneo24`. Both USB and Wi-Fi SSH worked and inspected Kiyo
  frames showed readable login consoles. These are selector/access results,
  not clock/PM clearance; recheck current boot and any active import job.
  The import job `gameshellneo-bundle-import-8c5876d51cac48de8e6a5d530f8a32ce`
  is an expected retained failed unit. Its private staging is unpublished;
  flags and catalog are unchanged. Do not clear the failure or discard its
  archive/staging to obtain a clean status.
- Use the saved PM/RTC/cable test Tasks and their exact matching runtime/image
  admission, original-result ledger, restoration and postflight checks. Keep
  debug stages distinct from actual sleep. The current RTC trial cap is sixty
  seconds; previous successes do not authorize longer endurance claims/tests.
- The owner requires the established **long, approximately one-second speaker
  warning before screen blanking, reboot or shutdown**. Use the existing warned
  commands (for example `device:reboot`); do not bypass them with a bare reboot.
  Video-only observations do not establish that the owner heard a tone.
- Preserve exact boot/image/helper identities and original failures, partial
  captures and evidence gaps. A timeout is inconclusive, not proof that a remote
  action stopped. Do not rerun until clean or relabel a failed original as a
  passing successor. Readiness, display, input, network, timing and energy are
  different acceptance claims.
- NEO-10's replacement battery is an unbranded BL-5C advertised as 3.7 V /
  1020 mAh; exact manufacturer limits remain unknown. The owner has no external
  power meter. Software readings/timed tests cannot independently establish
  electrical accuracy or charging safety. Do not guess ADC offsets, charger
  limits or gauge calibration; extended charging/termination qualification
  remains deferred while the discrepancy is unresolved.
- Cable changes, button-input tests, card swaps and serial wiring need the
  owner. Serial recovery is not established: the small board connector/harness
  remains unresolved. Preserve the original installation and recovery artifacts.

## Builds, tests and process ownership

- Use `task --list`, `task doctor`, `task setup` and the selected branch's saved
  build/check/test Tasks. `task setup` prepares private directories and verifies
  the pinned builder; it is not needed before every command on this configured
  host. Use the locked Docker image/platform and documented explicit input paths
  when building in a worktree. Store secrets/provisioning outside Git.
- Keep maintained image patches distinct from `kernel/candidates/`. The
  completed NEO-202 patch 0054 and preceding Wi-Fi candidates remain outside
  the image queue. NEO-58 retains deliberate integration, matching hardware
  qualification and the separate firmware-startup/reset audit. Reports 284–286
  in `brcmfmac-tx-recovery` record the latest offline work.
- NEO-205/207 preserve the 33 production kernel patch names/hashes. Power-supply
  lifetime, MUSB retirement and wake/startup are explicit offline candidate
  profiles. Invoke their saved Tasks deliberately; passing candidate checks
  does not select an image queue. Wake/startup and retirement still need
  software reconciliation at terminal IRQ/wake cleanup before a combined
  queue can be qualified. NEO-98/102/103/106 remain open for their separately
  documented software, image and physical gates; do not label every remaining
  parent task human-only. Reports 289/291 record the boundaries.
- Inspect the live process/container/session handle before calling a build
  stopped. The NEO-194 baseline proves that a host command can disappear while
  its Docker container keeps writing. Do not start a duplicate build, clear a
  lock/ledger, delete active scratch, or stop unrelated containers on that basis.
- NEO-194 is complete and integrated in main: recorded stage containers and
  `build:stage:status/resume/stop` retain logs/results and exclude duplicate
  writers. Report 287 records qualification; report 288 repeats all twelve
  Docker fixture groups on the merged source. NEO-206's receipt/pinned-run
  interface and managed SMP/QMP runners pass thirteen ownership groups plus
  real ARM guest checks in report 290. Older preserved worktrees still have
  their original wrapper and must not be assumed protected by these fixes.
  Do not bypass ownership to make a retained named/interactive runner work.
- Wait for authoritative completion before changing a test's hashed inputs.
  A session observation timeout does not terminate it; poll the same handle or
  inspect the specific container/job. Preserve logs and terminal results. A
  candidate's native/sanitizer/ARM or object build is not hardware qualification.
- Use existing retention/checkpoint Tasks and confirm references before deleting
  images, old kernels or fixture directories. Keep recovery checkpoints and
  original failed evidence; preview cleanup and exclude active writers.
- For flashing, first identify the physical Samsung DEV spare with fresh Mac
  inspection; disk numbers and volume labels can change. Reuse `mac:stage`,
  `mac:inspect`, `mac:preflight`, `mac:flash` and full readback/ejection. The owner
  has allowed reflashing the DEV spare when required, but never infer the target
  from an old disk number or erase the original card. Card movement still needs
  the owner, and image transfer still needs the network check above.

## Starting or resuming a session

1. Read this file, inspect the current worktree/dirty files, and read the active
   Kaneo ticket/comments before selecting the next action.
2. Revalidate any prior process handle and saved result; classify the prior
   goal turn from evidence rather than repeating a plan or restarting a job.
3. For hardware access, use the integration worktree and its existing private
   configuration. Read fresh USB/Wi-Fi status and, when visual evidence is
   needed, take and inspect a fresh selected-camera baseline.
4. Keep current blockers explicit. A working login screen or a new boot with
   zero counters does not resolve the older clock, power or radio findings.
5. Continue feasible software work while physical actions are pending. Update
   `FOLLOW-UP.md`, the numbered report and Kaneo with exact remaining gates.

## Kaneo

- This project tracks work using Kaneo on the "GameShellNeo" (NEO) project in the "OpenSource" workspace.
- After a plan is approved, create tickets in Kaneo instead of the `PLAN.md` file.
- Whenever a bugfixes or tweaks are requested, please assess what needs to be done, then create the ticket and progress it through the board.
- When working on a ticket, move it to the "In Progress" column.
- Commit and push after each ticket has been completed and update the ticket with a summary of the implementation before closing it off.
- When a review is required before closing the ticket off, move the ticket to the "In Review" column.
