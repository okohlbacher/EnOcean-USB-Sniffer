# Changelog

## v1.0 - 2026-05-25

- Initial generic CircuitPython ESP3 / EnOcean USB sniffer.
- Parses ESP3 frames from `board.TX` / `board.RX` at `57600 8N1`.
- Emits timestamped USB serial text output with raw ESP3 frames.
- Probes `CO_RD_VERSION` and `CO_RD_IDBASE` on startup and after Ctrl-C reload.
- Documents ESP3 reference material and output fields.
