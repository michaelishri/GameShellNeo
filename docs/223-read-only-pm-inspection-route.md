# Read-only PM inspection over either SSH route

9 October 2026, Pacific/Auckland. NEO-162.

`task device:pm-inspect ROUTE=wifi` now uses the configured Wi-Fi route. Previously
the task silently opened USB regardless of that option; this caused an inspection
timeout when USB was physically absent during NEO-109. The default remains USB.

The change selects a transport only for the existing read-only `--inspect`
operation. It writes `route.json` in the private capture before opening SSH, then
saves the unchanged inspection payload as `inspection.json`. An SSH failure is
returned without an automatic retry or alternate route. Active debug cycles,
collection and restoration retain their existing USB behavior. The new
`--inspect-route` argument or `NEO_PM_INSPECT_ROUTE` environment setting is
rejected outside inspection before credentials are loaded or work starts.

Reproduction:

```sh
task device:pm-inspect            # USB
task device:pm-inspect ROUTE=wifi  # Wi-Fi, through the Mac when .env selects it
python3 tools/check-pm-stages.py --inspect --inspect-route wifi
task check
```

Four host regression tests cover default USB despite the general task runner's
Wi-Fi default, explicit/environment Wi-Fi selection, invalid routes and all
non-inspection modes, and preservation of the original connection exception.
They assert that inspection does not invoke service commands, upload helpers,
submit PM cycles or silently fall back to USB.

The complete host check passes: 16 runtime tests and 808 tooling tests, two
optional skips, compiled helper checks and Bash/ShellCheck. Private log:
`.local/neo162-host-check.log`. Skips are the opt-in user-systemd test and a
prepared Armbian-source-dependent check unavailable in this isolated worktree.

Both routes were then checked on the awake GameShell using the saved task:

| Route | Private capture |
| --- | --- |
| Explicit Wi-Fi | `.local/diagnostics/20261008T123632.779087Z/` |
| Default USB | `.local/diagnostics/20261008T123712.871216Z/` |

Both returned kernel `6.18.54-gameshellneo23`, boot
`44b698ad-7fef-46d4-9e0f-71153f6f81e9`, taint zero, PM test `none`, asynchronous PM
enabled, brightness 1 and backlight power 0. These were read-only snapshots;
no sleep, screen blanking, audio, reboot, cable manipulation or image replacement
was performed. This fixes route selection in diagnostics and does not establish
the cause of NEO-154's intermittent SSH stalls.
