## Driver engineering

- Driver changes are authorized throughout GameShellNeo's agreed scope, including fixes, refactoring, extensions and replacements. Do not seek separate approval merely because a change belongs in a driver.
- Prioritize a stable, fast, power-efficient driver stack. Fix the underlying driver issue at the appropriate layer where practical rather than accumulating userspace workarounds, retries or delays that mask it.
- Treat existing upstream, vendor and ClockworkPi implementations as reference material, not prescribed code. Prefer maintainable upstream-compatible fixes when suitable, but do not preserve a defective design solely to avoid driver changes.
- If a hardware constraint or unresolved cause requires a temporary workaround, document the evidence, tradeoff and removal criteria, and track the underlying work in `FOLLOW-UP.md`.
- Validate changes with reproducible tests and relevant hardware qualification. Keep claims of stability, latency and energy savings tied to evidence; source-level improvements alone do not establish hardware results.

## Camera observations

- The owner has authorized the MacBook's built-in camera for GameShell screen observations. Use it for tests that only need visual confirmation that the display returns, instead of asking the owner to report the screen state. Camera setup and permission are already verified; a still and a five-second, ten-frame sequence showed readable console text. See [report 166](docs/166-mac-camera-observation.md) and the camera section of [README.md](README.md).
- Keep the Mac open, awake and logged into its desktop, with the GameShell screen clearly in view. If positioning changes, inspect a fresh baseline image before relying on the camera. Tests that sleep the Mac need another observer.
- From the repo, run `task mac:camera-status` to read permission without opening the camera, `task mac:camera-capture` for a still, or `task mac:camera-capture SECONDS=30 FPS=2` for a sequence. Sequences accept 1–300 seconds and 1–5 exported frames per second. Reuse the installed app; run `task mac:camera-setup` if setup is missing or helper source changes. Rebuilding may require macOS permission again.
- For an authorized hardware test, start a sequence first and wait for the readiness message, which follows the first saved image and exposure settling. Then perform the test while capture continues. Camera commands alone do not initiate GameShell sleep, reboot or other device changes.
- Inspect the actual JPEGs and session results under ignored `.local/diagnostics/<capture>/`. Record the observed screen state and confirm successful capture and camera shutdown. The helper captures video only, runs on demand and stops after the bounded capture; no microphone, login item or persistent camera service is used. Successful downloaded captures are removed from the Mac; failed or interrupted captures remain there for diagnosis. Keep raw images private and out of Git.
- An obscured, unreadable or missing image is inconclusive. A lit screen alone does not establish application responsiveness, input or network recovery; verify those separately. Camera frame timestamps do not qualify sub-second resume targets or power consumption. USB unplugging, SD-card swaps and other physical actions still require the owner.

## Kaneo

- This project tracks work using Kaneo on the "GameShellNeo" (NEO) project in the "OpenSource" workspace.
- After a plan is approved, create tickets in Kaneo instead of the `PLAN.md` file.
- Whenever a bugfixes or tweaks are requested, please assess what needs to be done, then create the ticket and progress it through the board.
- When working on a ticket, move it to the "In Progress" column.
- Commit and push after each ticket has been completed and update the ticket with a summary of the implementation before closing it off.
- When a review is required before closing the ticket off, move the ticket to the "In Review" column.
