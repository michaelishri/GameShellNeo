# External Razer Kiyo screen observation

12 October 2026 NZDT. NEO-193. The owner requested the external camera instead
of the MacBook's built-in camera. **The GameShell screen is clearly visible and
its console text is readable with the present positioning.**

## Selection and reusable workflow

The existing video-only helper now discovers built-in and external cameras.
It uses Apple's [capture-device discovery API](https://developer.apple.com/documentation/avfoundation/avcapturedevice/discoverysession)
with the external device type on macOS 14 or newer (the older external type on
earlier supported systems). The Mac reports **Razer Kiyo** and **FaceTime HD
Camera**. Camera permission remained authorized after compiling and signing
the updated helper.

The private `.env` now selects `NEO_CAMERA_NAME='Razer Kiyo'`. The exact name
must match one device; missing or duplicate matches stop before capture and
never fall back to the built-in camera. Download validation also rejects a
successful result naming a different camera. An explicit Python `--camera`
argument overrides the preference. Existing setups without the preference
retain the original FaceTime default.

```sh
task mac:camera-status
task mac:camera-capture
task mac:camera-capture SECONDS=5 FPS=2
```

Status lists available cameras without starting video capture. Still/sequence
bounds, exposure settling, first-frame readiness, no microphone, private
downloads, stopped-session validation and successful remote cleanup remain in
place. The camera stops after each requested operation.

## Observed evidence

Private evidence remains under ignored `.local/diagnostics/`; no images or
device identifiers are committed.

| Capture | Evidence |
| --- | --- |
| `20261011T115112.152547Z` | Updated Swift helper compiled and signed; camera authorization retained |
| `20261011T115222.319160Z` | One 1920 × 1080 Kiyo JPEG; full display in view, console header and login prompt readable |
| `20261011T115251.504954Z` | Status succeeds, reports both video cameras and authorized permission |
| `20261011T115305.518818Z` | Five-second Kiyo sequence, ten 1920 × 1080 JPEGs; first/last images inspected and readable |

The still and sequence both report success, authorization and camera shutdown.
All sequence receipt timestamps increase, with **4.689 seconds** between the
first and last frame. Both capture directories and the successful status
directory were independently verified removed from the Mac after download;
no `CameraObserver` process remained.

The visible text includes `GameShellNeo 0.1.0 Trixie tty1` and the
`gameshellneo login:` prompt. Focus and framing are sufficient for current
screen-state observations; no repositioning is needed. This is an observation
of an already illuminated display, not a screen transition or PM qualification.

## Launcher correction and validation

Two initial status invocations hit macOS `open -W` reporting an exit-wait
`kevent()` error. The second invocation's saved result independently confirms
that the helper completed status successfully and stopped. The wrapper now
allows collection after that specific exit-1 wait error only when a terminal
result file exists in the fresh capture directory. Normal result validation
still checks action/schema, success and stopped-session evidence. Unexpected
launch errors or missing results remain failures; unsuccessful results remain
failures and are retained. The original failed-launch evidence is preserved.

Nine focused Python tests pass, including private preference/explicit override,
camera mismatch, exact launcher-error handling with/without a terminal result,
literal subprocess arguments, bounded capture parameters and frame validation.
Swift compilation, live status, still and sequence capture passed on the Mac.

No GameShell command, sleep, reboot, brightness change or cable action was
performed. Keep using separate health, input and network evidence. These
images do not measure energy or sub-second latency, and video-only capture
does not confirm warning-tone audibility. Existing NEO-192 clock investigation
and PM admission conditions remain unchanged.
