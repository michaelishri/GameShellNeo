# First card and boot validation

Date: 27 September 2026. Kaneo: NEO-5, in progress.

## Identified spare

The owner inserted the Samsung 64 GB spare into the Mac's USB card reader and
authorized flashing it. macOS reported the volume as `NO NAME`, rather than
`SAMSUNG-64GB`, with existing data. After this discrepancy was raised, the owner
explicitly confirmed that this was the intended spare and authorized erasing
its contents.

At inspection, the whole device was `/dev/disk16`, partition `disk16s1`, with
64,013,467,648 bytes and 512-byte sectors. It was physical, external, writable
USB media. **Disk numbers are session-specific:** inspect again before another
write. Private records under `.local/flash/` retain the original disk/partition
plists and expected volume UUID, size and reader path.

The separate original GameShell card has not been overwritten. Its full
offline backup is still outstanding. The owner authorized this spare-card
write after identification; that does not satisfy the remaining recovery or
hardware acceptance gates.

## Transfer and write

The source is the [offline-validated image from report 25](25-first-build-validation.md):

- Image: `GameShellNeo-0.1.0-diagnostic.1-cpi31-750fb8829d41.img`
- Image bytes: `4294967296`
- Image SHA-256: `750fb8829d41af96ed58db1b5e5cf6a9051799436bb69740c973afd9656e33ad`
- Transferred gzip bytes: `267878533`
- Gzip SHA-256: `f90f16fa1660fb75bc58ffff52f9bcacc6966e3195c6d619374b611d5caa6563`

The private transfer is staged on the Mac under
`~/.local/share/GameShellNeo/`, with directory mode 0700 and file mode 0600.
Both compressed and decompressed checksums passed on the Mac. The flash
helper's dry run confirmed the recorded target identity.

The first write attempt unmounted the card, then macOS denied opening its raw
device with `Operation not permitted`, despite administrator access. **No image
bytes were written.** The owner then enabled Remote Login's full disk access
and asked to retry; the new SSH session passed the same pre-write checks.
Apple documents the setting under System Settings → General → Sharing → Remote
Login → “Allow full disk access for remote users”. The permission change must
be made through the Mac's settings; an alternative is running the prepared
helper locally from Terminal. [Apple Remote Login documentation](https://support.apple.com/en-mk/guide/mac-help/mchlp1066/mac).

The retry **completed successfully**: all 4,294,967,296 bytes were written,
flushed, and read back from `/dev/rdisk16`. The readback SHA-256 exactly matched
the image hash above. macOS then successfully ejected the card. The private
`flash-result.json` and `flash.log` under `.local/flash/` record this result;
the Mac also retains the report in its private staging directory. The original
card was not the write target.

## Repeatable flashing

[`tools/flash-macos.py`](../tools/flash-macos.py) runs on macOS with Python 3.9
or later. Its default is a dry run. It checks both transfer and expanded-image
hashes, requires physical external USB media, matches the inspected size,
reader path and existing partition UUID, and checks capacity and alignment.
It checks identity again after unmounting, immediately before opening the raw
device for a write. After writing it flushes, reads back the complete image
range, compares SHA-256, and ejects only after success.

Five tests cover rejection of internal, virtual, read-only, changed, undersized
and wrongly identified targets, including reuse of the same disk number for a
different volume. Run them with:

```sh
python3 -m unittest discover -s tools/tests -v
```

On the Mac, use the privately staged `transfer.json`, `target.json`, helper and
gzip file. The current `target.json` describes the original spare contents;
after flashing, its volume UUID changes, so another flash requires a fresh
inspection and target record. Never reuse a stale disk identifier.

```sh
cd "$HOME/.local/share/GameShellNeo"
python3 flash-macos.py \
  --image GameShellNeo-0.1.0-diagnostic.1-cpi31-750fb8829d41.img.gz \
  --manifest transfer.json --target target.json
```

Once the owner has identified and authorized the target, add `sudo`, `--write`
and `--report flash-result.json` to perform the write and save its evidence.
This writes the image's 4 GiB range; it is not a secure erase of the whole card.
The first image has a fixed root partition and does not expand to use 64 GB.

## First boot and acceptance

Awaiting the owner's physical card swap. After the successful verified write
and eject, the owner was given this sequence:

1. Shut down the GameShell normally and disconnect USB power.
2. Remove the original card and put it in the Mac's reader for a read-only
   offline backup, then insert the Samsung spare into the GameShell.
3. Reconnect the known-working USB data cable to the Mac and turn on the GameShell.
4. Establish USB SSH at `192.168.10.1` using the new per-device host key and
   development key. Wi-Fi is a separately provisioned fallback.
5. Capture the boot log, bound drivers, failed units, display/input observations,
   battery data, and frequency/temperature readings before changing settings.

Ten cold boots, ten USB reconnections, control/display checks, CPU/storage
stability, supervised power tests and the offline original-card backup remain
open. Serial remains deferred. A verified flash establishes bytes on the card,
not successful boot or hardware compatibility.
