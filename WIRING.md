# Wiring

Hardware wiring for the EnOcean USB Sniffer.

## Components

- **Adafruit Feather STM32F405 Express** — the CircuitPython host running `code.py`.
- **EnOcean FAM4PI** — ESP3-capable EnOcean module, connected to the Feather UART.
- **NeoPixel breakout board** — a single addressable RGB LED (WS2812-style) on a breakout, for status indication.

## EnOcean FAM4PI ↔ Feather UART

The UART is crossed (TX to RX):

| Feather pin | FAM4PI pin | Notes |
|-------------|------------|-------|
| `TX`        | `RX`       | Feather transmit → module receive |
| `RX`        | `TX`       | Feather receive ← module transmit |
| `GND`       | `GND`      | Shared ground |
| power       | power      | Per the module / carrier board requirements |

In CircuitPython this UART is opened on `board.TX` / `board.RX` at `57600 8N1` (see `code.py`).

## NeoPixel breakout ↔ Feather

| NeoPixel pin | Feather pin | Notes |
|--------------|-------------|-------|
| power (VIN/5V) | `USB`     | USB bus power (~5 V) |
| `GND`        | `GND`       | Shared ground |
| `DI` (data in) | `GPIO10`  | Single-wire NeoPixel data |

Notes:

- `DI` is the data **input**; if the breakout exposes a `DO`/data-out pin, leave it unconnected for a single pixel.
- The NeoPixel is powered from `USB` (≈5 V). The Feather data pin idles at 3.3 V logic; a single pixel powered at 5 V generally accepts this, but a level shifter or a ~330 Ω series resistor on `DI` is the robust option if the signal proves unreliable.
- The `GPIO10` label is the pin as wired on the board. `code.py` resolves the actual CircuitPython pin from `NEOPIXEL_PIN_CANDIDATES = ("GPIO10", "GP10", "IO10", "D10")`, picking the first attribute that exists on `board`, and logs the resolved pin on startup as `event=neopixel_config pin=board.<name>`. Check that line against where you physically wired `DI`; if it picked the wrong pin, reorder or edit the candidate list.
- `code.py` drives the NeoPixel as a status indicator: it blinks a colour per received telegram, keyed on the EnOcean RORG family. See the **NeoPixel Status** section in `README.md` for the colour table. The onboard `board.LED` still toggles per valid frame as before.
- The `neopixel` library must be present in `/CIRCUITPY/lib/` (from the Adafruit CircuitPython library bundle). If it is missing, `code.py` logs `event=neopixel_config status=disabled reason=no_neopixel_lib` and runs normally without the pixel.
