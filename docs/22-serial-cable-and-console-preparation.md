# Serial cable provenance and console preparation

Inspection date: **27 September 2026**. The owner has confirmed **CPI v3.1** printed on the GameShell mainboard. No serial leads have been connected to it, and no serial transmit/receive or boot-capture test has been performed.

## Current conclusion

**Serial setup is deferred and does not block initial base development.** The [implementation plan](20-base-implementation-plan.md) uses USB/Wi-Fi SSH and spare-card recovery for that work. Revisit the harness when early-boot or resume diagnostics require it; there is no need to locate or purchase it before preparing the first-build specification.

The owner's corrected purchase reference identifies **Banggood product 1055396**, a USB-to-TTL Raspberry Pi debug cable. The original listing and its linked wiring guide have now been recovered. The guide shows this cable connected directly to the Raspberry Pi UART, with the red power wire disconnected. This provides a reasonable documentary basis for its **intended use with a 3.3 V UART**, replacing the earlier reliance on wire colours and USB identity alone. It does not measure this individual cable's output or establish voltage tolerances.

When serial setup resumes, the next step is to identify the GameShell's expansion harness and connector orientation. A replacement serial adapter is no longer the default recommendation solely because the live listing disappeared. If physical inspection or testing contradicts the recovered documentation, revisit electrical qualification.

The owner additionally reports that this same cable worked on an **Orange Pi Zero**. That is useful practical evidence of prior board-console use, but the exact wiring, test conditions and signal voltage were not independently observed.

## Evidence chain

1. **Owner's purchase reference:** [Banggood product 1055396](https://www.banggood.com/USB-To-TTL-Debug-Serial-Port-Cable-For-Raspberry-Pi-3B-2B-COM-Port-p-1055396.html). The live URL returned HTTP 404 during direct retrieval.
2. **Original seller listing:** the [31 May 2016 archive](https://web.archive.org/web/20160531111537/http://www.banggood.com:80/USB-To-TTL-Debug-Serial-Port-Cable-For-Raspberry-Pi-3B-2B-COM-Port-p-1055396.html) was successfully retrieved. Its product-information link points to `raspberrypiwiki.com/index.php/USB_to_TTL`. Its Linux screenshot shows USB ID `067b:2303`, matching the owner's observed interface.
3. **Seller-linked product guide:** the [16 November 2016 archive](https://web.archive.org/web/20161116200217/http://www.raspberrypiwiki.com:80/index.php/USB_to_TTL), revision 2318, was successfully retrieved. The page states a last modification date of 14 July 2016. Its [wiring photograph, captured 27 February 2017](https://web.archive.org/web/20170227160700/http://www.raspberrypiwiki.com/images/5/5c/IMG-1218-W800-EN.jpg), shows green, white and black connected to the Pi UART/GND positions, with red hanging free.
4. **Electrical interpretation:** Raspberry Pi's [UART documentation](https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts) specifies 3.3 V UART operation and identifies GPIO14/TX on physical pin 8 and GPIO15/RX on pin 10. Combining this with the seller-linked wiring photograph supports intended 3.3 V compatibility. The recovered cable text does not itself provide a numerical TX output specification, so this conclusion is an inference from the documented application.
5. **Observed adapter:** the Mac enumerates `Prolific Technology Inc.`, product `USB-Serial Controller`, VID:PID `067b:2303`, device revision descriptor `0x0300`, and serial port `/dev/cu.usbserial-110`. This is consistent with the listing but does not identify a precise chip revision or prove electrical behavior. See [the installed baseline](21-installed-hardware-baseline.md).

Private copies of the original HTML, retrieved diagrams/screenshots and archive lookup responses are preserved under `.local/hardware-baseline/2026-09-27/serial-source-reference/`, with sizes and SHA-256 hashes in `MANIFEST.json`. Archive availability differed between HTTP and HTTPS versions of the original URLs; an empty lookup for one variant was not treated as proof that no archive existed.

## Supplied links that have a narrower role

The [BluPants Hackster article](https://www.hackster.io/blupantsrobot/coding-with-raspberry-pi-and-blupants-d3d4b4) links to this exact Banggood product. However, its suggested use is for the red/black power connection; the author actually used an alligator-clip cable. It establishes a historical link to the product, not a tested UART voltage or serial connection.

The earlier Prolific `ShowProduct.aspx?p_id=229&pcid=41` URL was a **Mac driver-download page**, as shown in Prolific's [PL2303HXD datasheet, page 8](https://web.mit.edu/6.111/volume2/www/f2019/handouts/pl2303v1_4_4.pdf). It did not identify the purchased cable.

The subsequently supplied [PL2303GT datasheet v1.0.2](https://www.prolific.com.tw/wp-content/uploads/2025/07/DS-23181003_PL2303GT_V1.0.2.pdf) describes a different reference device: GT includes an RS-232 transceiver. Pages 13 and 25 distinguish its RS-232 serial pins from its 3.3 V GPIO circuitry; the serial-output table gives a typical bipolar swing of ±9 V under its stated load. Its default PID is `23A3` on page 19, whereas the owner's adapter reports `2303`. USB descriptors are programmable, so the mismatch is supporting evidence, not definitive silicon identification. There is no basis for applying this GT datasheet's pin voltages to the owner's TTL cable. In particular, its references to 3.3 V supplies/GPIOs do not certify a 3.3 V UART output.

## Wire functions and pending GameShell connection

The owner-supplied cable mapping is consistent with the recovered Raspberry Pi wiring photograph:

| USB adapter lead | Function, relative to adapter | Role in a future console connection |
| --- | --- | --- |
| Black | Ground | Common ground |
| White | RXD, input to adapter | Receives the GameShell's transmitted output |
| Green | TXD, output from adapter | Sends input to the GameShell |
| Red | +5 V power | Leave disconnected; GameShell has its own power source |

This table describes signal roles, not a physical GameShell pin-placement instruction. ClockworkPi's [expansion-wire reference](https://www.clockworkpi.com/post/expansion-wire-color-code) identifies UART0 on PB0/PB1 at expansion positions 2/3 and a ground at position 4. It also shows repeated wire colours, including power and ground on different occurrences of the same colour. Match connector position and orientation before mapping the USB adapter leads; colour alone is insufficient on that harness.

The owner is **not sure whether the original 14-wire expansion cable is available**, and observes that the mainboard connector is smaller than the adapter's individual sockets. A [first-hand console setup](https://forum.clockworkpi.com/t/getting-a-serial-port-uart-for-the-gameshell-console-and-u-boot-access/8464) provides a [reference photograph of that cable](https://canada1.discourse-cdn.com/flex029/uploads/clockworkpi/original/2X/7/7856213f54f33ed3836f929970805b4f25f69b42.jpeg): a small white board connector fans out into coloured wires with individual sockets. Those sockets and the adapter's sockets need suitable male-to-male jumper leads between them. Confirm the actual harness/connector before giving step-by-step wiring instructions; do not force the adapter sockets into the fine-pitch mainboard connector. If the harness is absent, identify the precise mating connector before recommending a replacement breakout. The owner has no multimeter.

After identifying the physical connection, begin by capturing output with adapter ground and RX only; leave its TX and power leads disconnected for that first observation. Confirm console parameters against the saved boot configuration, then qualify input separately. A successful receive-only capture does not establish transmit compatibility or complete recovery access. Do not reboot or change boot configuration merely to compensate for an unidentified connection.

### Was the expansion cable included?

Historical owners describe the GPIO breakout as [coming with the GameShell](https://forum.clockworkpi.com/t/is-there-an-app-for-blank/3144), and the photographed console setup calls it the provided cable. ClockworkPi's [D.E.O.T. kit contents](https://www.clockworkpi.com/product-page/gameshell-kit-d-e-o-t-version) explicitly include a 14-pin GPIO development cable. These sources establish that it was a supplied accessory, although the currently published ordinary kit lists do not enumerate it and do not prove every shipment's contents. Check the owner's original box and unused accessories before sourcing another harness; availability in this owner's kit remains unconfirmed.

Outstanding tasks remain in [FOLLOW-UP.md](../FOLLOW-UP.md). Console access remains deferred while source preparation and initial base work proceed.
