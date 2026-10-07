# Diagnostic.23 installation and terminal validation

7 October 2026; timestamps are UTC. NEO-137 is in progress. Diagnostic.23 has
been written to the Samsung DEV card, its full 4 GiB readback passed, and the
card was safely ejected. Owner-confirmed login and new-boot qualification are
pending at this checkpoint.

## Transfer and shutdown

[Report 198](198-legacy-pty-startup-candidate.md) records the configuration
change, baseline terminal inventory, build checks and artifact hashes.
After the owner confirmed regular Wi-Fi, `task mac:stage` completed with both
compressed and expanded image checksums verified on the Mac. Private transfer
log: `.local/neo137-stage.log`.

The owner then confirmed readiness for the DEV-card swap. The saved USB status
task reached diagnostic.22, kernel `6.18.54-gameshellneo21`, before shutdown.
Private status capture: `.local/diagnostics/20261007T093129.061170Z/`.

`task device:audio-test ROUTE=usb` passed three one-second warning cues and
restored the same boot's mixer/amplifier state. Run
`294dbc17ffd2487abba7ad200ff368ab` is saved in
`.local/diagnostics/20261007T093146.660595Z/`; result SHA-256:
`5cd678c4fec734f8a17c936dc3519613a9e1db1234360c04d32389f0bac1a9c0`.
Both audio snapshots identify boot `7884d229-2309-47df-9af0-b6fe500ad9ac`.
Four collection attempts returned `RuntimeError` before the original completed
result was retrieved; no second warning test was submitted. Audibility has not
been separately confirmed for this shutdown sequence.

`task device:exec ROUTE=usb -- sudo -n systemctl poweroff` returned success.
Private logs are `.local/neo137-before-shutdown.log`,
`.local/neo137-shutdown-warning.log` and `.local/neo137-shutdown.log`.
The owner confirmed moving the Samsung DEV card to the Mac reader after
shutdown.

## Verified card write

Fresh `task mac:status` found one external physical card with the existing
GameShell boot/Linux partitions. `task mac:inspect DISK=disk16` recorded its
64,013,467,648-byte capacity, physical USB reader path and existing boot-volume
UUID. `task mac:preflight` verified this identity and the source checksums.
`task mac:flash DISK=disk16` then verified the mount guard's veto, wrote the
image, read back every image byte and safely ejected the card.

| Evidence | Result |
| --- | --- |
| Image | `GameShellNeo-0.1.0-diagnostic.23-cpi31-bf64ca854137.img` |
| Written/readback bytes | 4,294,967,296 |
| Readback SHA-256 | `bf64ca85413711b991cfaafbe7d8c7dabcf4355fe1bb8590085850f68b13d726` |
| Readback / mount guard / ejection | Passed / verified / complete |
| Flash result SHA-256 | `56e2319903bddfa7f71434c7445b5ad1658c02dd37e1fb86099c47f982b0b607` |
| Hardware boot tested by flash helper | False |

Original evidence: `.local/diagnostics/20261007T093445.848672Z/`.
Private task logs are `.local/neo137-{mac-status,inspect,preflight,flash}.log`.
The owner was asked to reinstall the card, reconnect USB and confirm the normal
login screen before awake qualification.

## Remaining acceptance

After verified writing and owner-confirmed login, check the exact
diagnostic.23 / `6.18.54-gameshellneo22` identity, both network routes and normal
awake integration, journal, power-key and RTC behavior. Run
`task device:user-startup LEGACY=disabled` to require zero legacy terminal
devices/units while checking modern Unix98 data transfer, resizing and an actual
SSH terminal allocation. Compare fresh-session timing and manager resource
observations with report 198; do not infer an energy saving from unit counts.

Observed suspend/debug and actual sleep qualification require a fresh ready
response on the new boot. Diagnostic.22's existing PM evidence is historical
evidence, not qualification of this candidate.
