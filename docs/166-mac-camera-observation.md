# Mac camera observation for display qualification

Date: **10 October 2026 NZDT**. Work: **NEO-189**. The owner requested camera
observations to replace manual confirmations that the GameShell display returns.
No GameShell reboot, sleep request, cable change or SD-card operation is part of
this setup.

## Tooling

`task mac:camera-setup` builds an ad-hoc-signed native macOS app from
[`macos-camera.swift`](../tools/macos-camera.swift) through the existing verified
Mac SSH connection. The app has a camera usage description and requests normal
macOS camera permission in the logged-in desktop session. Its identity is
`org.gameshellneo.cameraobserver`, displayed as **GameShellNeo Camera**. The
[`Python wrapper`](../tools/mac-camera.py) reuses an unchanged installed app.

`task mac:camera-status` reads authorization without opening the camera.
`task mac:camera-capture` saves one still; `SECONDS=30 FPS=2` saves a bounded
sequence. The helper selects the built-in FaceTime HD Camera, does not request
microphone access, and exports JPEGs after 1.5 seconds of exposure settling.
Readiness is announced only after its first exported image. Captures are limited
to 300 seconds and five exported frames per second.

Every exported frame has Mac receipt time, monotonic uptime, source presentation
timestamp and dimensions. Successful session results record camera shutdown.
A separate main-thread watchdog also bounds a stalled session-start call.
Only one observation can run at once. The app is launched on demand; no camera
daemon or login item is installed.

Local evidence is kept under ignored `.local/diagnostics/<capture>/`. After
successful validation and download, the corresponding temporary Mac capture
is removed. Failed or interrupted captures are retained privately on the Mac.

## Setup evidence

- The Mac is reachable through the configured SSH route and enumerates a
  **FaceTime HD Camera**. FFmpeg is already installed and also enumerates it.
- A bounded direct-SSH FFmpeg probe did not return a frame within 15 seconds;
  its subprocess was terminated. This does not establish the cause.
- The native helper compiles and signs successfully on the Mac. Its first
  authorization attempt ended with `notDetermined` and a timeout; it correctly
  reported failure and a stopped session.
- A subsequent two-minute authorization attempt also timed out without a grant.
  The Mac desktop is logged in and unlocked. The final helper is installed, and
  its read-only status action succeeds while reporting `notDetermined`.
- Six focused Python tests verify capture bounds, result validation, filename
  traversal rejection, duplicate rejection and literal subprocess arguments.
  The three Task commands are present, and changed-file whitespace checks pass.

## Successful camera verification

The owner approved macOS camera permission, and the installed helper then
completed both capture modes with `authorization=authorized`, `success=true`
and `camera_stopped=true`:

| Private capture under `.local/diagnostics/` | Result |
| --- | --- |
| `20261009T212022.664378Z` | One 1920 × 1080 JPEG; GameShell display clearly visible with readable console text |
| `20261009T212044.150774Z` | Five-second sequence at two exported frames per second; ten 1920 × 1080 JPEGs |

The still and the first/last sequence images were visually inspected. The
screen remains clearly visible and readable in this positioning. All ten
sequence frames were downloaded, with strictly increasing receipt timestamps;
the first-to-last receipt span was **4.621 seconds**. Readiness metadata was
also downloaded. Both successful Mac capture directories were independently
verified absent after cleanup, and no `CameraObserver` process remained.

The camera workflow is ready to supply visual observations for future tests
with this positioning. This setup observed the existing illuminated console;
it did not initiate or qualify any GameShell sleep/resume transition. Earlier
failed authorization attempts do not count as display or hardware qualification.

## Qualification boundary

The Mac must remain open, awake and logged in, with the GameShell screen clearly
in view. Inspect actual images; an obstructed or unreadable screen is inconclusive.
Use SSH, driver logs and input tests separately to establish responsiveness.
An illuminated display alone does not prove a recovered application or network.
These frame timestamps do not qualify the sub-second resume target or measure
energy. Tests that sleep the Mac require another observer, and physical cable,
card, button and recovery actions still require the owner.
