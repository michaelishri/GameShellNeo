# Diagnostic.22 installation and ADC validation

7 October 2026; capture timestamps are UTC. NEO-132. The diagnostic.22 card write and full readback pass;
owner-confirmed boot and awake hardware checks are pending.
[Report 193](193-diagnostic22-adc-integration.md) records the source-qualified
ADC correction, verified image and source-only Mac transfer.

## Shutdown and card write

The owner confirmed readiness for the DEV-card swap. USB status passed on
kernel `6.18.54-gameshellneo20`, boot
`50dc8224-95e2-4f92-b35e-e35ca5566340`.
`task device:audio-test ROUTE=usb` passed three one-second warning cues with
same-boot mixer/amplifier restoration. Audio run:
`a4f164ee9b3441098381b5a6063b2ffc`; private capture:
`.local/diagnostics/20261007T051839.194263Z/`. Result SHA-256:
`fa778d628b642b098adf2e3b2bfc24521378e2c3c0dffd01540b700fd5011607`.
`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
The owner then confirmed the Samsung DEV card was in the Mac reader.

The saved workflow runs from `.local/worktrees/power-insertion-wake`:

```sh
task mac:status
task mac:inspect DISK=disk16
task mac:preflight
task mac:flash DISK=disk16
```

Fresh inspection found one external physical card, 64,013,467,648 bytes,
with its existing GameShell boot/Linux partitions. Its recorded volume UUID
and device identity passed preflight. Compressed/expanded image hashes passed.
The mount guard successfully vetoed an attempted mount before writing.
Private flash evidence is `.local/diagnostics/20261007T052040.740129Z/`.
The original task logs are `.local/neo132-*.log`.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.22-cpi31-08136efbd5f9.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `08136efbd5f939c88d1390240ecc00cd60f0a40ae7789b90cd6d7377f622fadf` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash result SHA-256 | `66b26f9c3709763dc323bc97d06b4bb7bf3d9ae5b5ac26da7eb8f39e5dc3b4ad` |
| Hardware boot tested by flash helper | False |

The owner has been asked to reinstall the ejected card, reconnect USB and
confirm the normal login screen.

## Qualification boundary

No new-image boot, battery-reading comparison or PM result is established yet.
After installation, check image identity, both SSH routes and saved awake
startup/ADC inventory. Preserve raw bytes and corrected/legacy formulas;
source correctness does not establish physical measurement accuracy or resolve
the earlier voltage discrepancy. Charger/gauge controls remain unchanged.
Attended suspend/resume qualification remains a separate follow-on slice.
