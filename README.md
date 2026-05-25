# EnOcean USB Sniffer

Version: `v1.0`

Generic CircuitPython ESP3 / EnOcean USB serial sniffer for an Adafruit Feather STM32F405 Express attached to an ESP3-capable EnOcean module such as FAM4PI / TCM.

Copy `code.py` and `README.md` to the `CIRCUITPY` volume. The board then becomes a USB serial ESP3 monitor.

## Install

With the board mounted as `CIRCUITPY`:

```sh
cp code.py README.md /Volumes/CIRCUITPY/
```

Open the USB serial console. On boot, save, reset, or Ctrl-C reload, the monitor prints module information and then streams ESP3 frames.

## Behavior

- Reads ESP3 frames from the EnOcean UART on `board.TX` / `board.RX` at `57600 8N1`.
- Prints timestamped text lines to the USB serial console.
- Blinks an optional status NeoPixel a colour per received telegram, keyed on the EnOcean RORG family (see [NeoPixel Status](#neopixel-status)).
- Does not filter by sender, EEP, KNX group address, or application.
- Does not contain HKK-specific sender labels or mappings.
- Validates both ESP3 CRC8 bytes.
- Prints raw ESP3 frame bytes for every valid frame.
- Prints bad-frame diagnostics for CRC or size errors.
- On startup, probes the module with:
  - `CO_RD_VERSION`
  - `CO_RD_IDBASE`
- Pressing `Ctrl-C` in the USB serial console triggers a reload, so the startup probe is printed again. The hardware reset button behaves the same from an operator perspective.

## Serial Console

On macOS, find the USB serial device with:

```sh
ls /dev/tty.usbmodem*
```

Then connect, for example:

```sh
screen /dev/tty.usbmodemXXXX 115200
```

The USB baud rate is only a terminal setting; the EnOcean module UART is fixed at `57600`.

Exit `screen` with `Ctrl-A`, then `Ctrl-\`.

## Wiring

UART wiring is crossed:

- Feather `TX` -> EnOcean module `RX`
- Feather `RX` -> EnOcean module `TX`
- Shared `GND`
- Power according to the module/carrier board requirements

A NeoPixel breakout is also wired for status indication (USB power, `GND`, `DI` -> `GPIO10`). See `WIRING.md` for the full pin map.

## NeoPixel Status

If a NeoPixel is wired (see `WIRING.md`) and the `neopixel` library is present in
`/CIRCUITPY/lib/`, the monitor blinks it once for every received frame. The colour
encodes the EnOcean telegram family, taken from the RORG byte — the first field of
the EEP `RORG-FUNC-TYPE` profile name — so the colour tells you the device class at
a glance without reading the serial console.

| Colour | RORG | Family | Typical devices |
|--------|------|--------|-----------------|
| Green | `0xF6` RPS | Repeated Switch | rocker switches, window handles |
| Amber | `0xD5` 1BS | 1-byte sensor | single binary contact (door, window) |
| Cyan | `0xA5` 4BS | 4-byte sensor | temperature, humidity, light, occupancy |
| Blue | `0xD2` VLD | Variable Length Data | actuators, metering, multi-channel |
| Magenta | `0xD4` UTE | Universal Teach-in | teach-in handshakes |
| Orange | `0xD1` MSC | Manufacturer Specific | proprietary telegrams |
| White | `0xC5` SYS_EX | Remote management | commissioning / system exchange |
| Red | other | unrecognised RORG | radio telegram with an unknown RORG |
| Dim white | n/a | non-radio frame | valid `RESPONSE` / `EVENT` / other packet types |
| Dim red | n/a | bad frame | CRC or size error |

Notes:

- The blink is non-blocking; the on-time is `BLINK_ON_S` (default 80 ms) and brightness
  is `NEOPIXEL_BRIGHTNESS` (default 0.25). Both are constants at the top of `code.py`.
- The data pin is resolved from `NEOPIXEL_PIN_CANDIDATES` and logged on startup as
  `event=neopixel_config pin=board.<name>`.
- If the NeoPixel cannot be set up (no library, no matching pin), the monitor logs
  `event=neopixel_config status=disabled reason=...` and runs normally without it. The
  onboard `board.LED` still toggles per valid frame regardless.

## Output Format

Startup example:

```text
# Generic ESP3 EnOcean monitor
ts=2000-01-01T00:00:02 uptime=2.153 event=start board="Adafruit Feather STM32F405 Express with STM32F405RG" runtime="..."
ts=2000-01-01T00:00:02 uptime=2.155 event=uart_config uart=board.TX/board.RX baud=57600 format=8N1
ts=2000-01-01T00:00:02 uptime=2.160 event=command_send command=CO_RD_VERSION(0x03)
ts=2000-01-01T00:00:02 uptime=2.172 event=module_info command=CO_RD_VERSION return=RET_OK ...
ts=2000-01-01T00:00:02 uptime=2.180 event=module_info command=CO_RD_IDBASE return=RET_OK base_id=...
ts=2000-01-01T00:00:02 uptime=2.190 event=ready frames=0 bad=0
```

Frame example:

```text
ts=2000-01-01T00:00:14 uptime=14.225 frame=000001 type=RADIO_ERP1(0x01) data_len=7 opt_len=7 rorg=RPS(0xF6) sender=01020304 status=0x20 payload=50 subtel=1 dest=FFFFFFFF rssi_dbm=-72 security=0x00 raw=55 ...
```

The board has no network time source in this monitor. If its RTC is unavailable, `ts=` falls back to `uptime+...s`. If the RTC exists but has not been set, the date can start around year 2000. The `uptime=` field is always useful.

## ESP3 References

These are the key protocol documents for agents or humans that need to interpret the output:

- EnOcean ESP3 landing page: <https://www.enocean.com/esp3>
- Current EnOcean Serial Protocol 3 technical specification PDF: <https://www.enocean.com/wp-content/uploads/Knowledge-Base/EnOceanSerialProtocol3-1.pdf>
- EnOcean Knowledge Base, including the ESP3 document and related radio protocol documents: <https://www.enocean.com/en/support/faq-knowledge-base/>
- DolphinV4 API ESP3 overview: <https://www.enocean.com/wp-content/uploads/redaktion/support/dolphin4-api/EO3100I_API_Documentation/enocean_serial_protocols.html>

The monitor output follows the ESP3 packet model:

- `raw=` is the full ESP3 packet, starting with sync byte `0x55`.
- `type=` is the ESP3 packet type, for example `RADIO_ERP1(0x01)` or `RESPONSE(0x02)`.
- `data_len=` and `opt_len=` are the ESP3 data and optional-data lengths from the packet header.
- `rorg=`, `sender=`, `status=`, `payload=`, `subtel=`, `dest=`, `rssi_dbm=`, and `security=` are parsed from `RADIO_ERP1` packets.
- `event=module_info command=CO_RD_VERSION` and `event=module_info command=CO_RD_IDBASE` are decoded ESP3 common-command responses.

## Files

- `code.py`: the monitor.
- `README.md`: this file.
- `WIRING.md`: hardware pin map (Feather, FAM4PI, NeoPixel).
- `CHANGELOG.md`: release notes.
- `LICENSE`: MIT license.
