# Changelog

## v1.1 - 2026-05-25

- Drive an optional status NeoPixel: blink a colour per received telegram,
  encoded by the EnOcean RORG family (RPS/1BS/4BS/VLD/UTE/MSC/SYS_EX, plus
  distinct colours for unknown RORG, non-radio frames, and bad frames).
- Resolve the NeoPixel data pin from candidate `board` attributes and log the
  resolved pin, brightness, and blink time on startup; degrade gracefully when
  the `neopixel` library or a matching pin is absent.
- Document the colour encoding in `README.md` and the wiring in `WIRING.md`.

## v1.0 - 2026-05-25

- Initial generic CircuitPython ESP3 / EnOcean USB sniffer.
- Parses ESP3 frames from `board.TX` / `board.RX` at `57600 8N1`.
- Emits timestamped USB serial text output with raw ESP3 frames.
- Probes `CO_RD_VERSION` and `CO_RD_IDBASE` on startup and after Ctrl-C reload.
- Documents ESP3 reference material and output fields.
