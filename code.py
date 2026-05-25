"""Generic CircuitPython ESP3 / EnOcean monitor.

Target: Adafruit Feather STM32F405 Express with an ESP3-capable EnOcean
module such as FAM4PI / TCM on the hardware UART.

The monitor is intentionally generic:
  - no sender allow-list
  - no site-specific labels
  - no KNX mapping
  - no packet filtering

It prints timestamped text lines to the USB serial console for every ESP3
frame it receives. On start it also probes the module with CO_RD_VERSION and
CO_RD_IDBASE. Press Ctrl-C in the USB serial console to trigger a clean reload
and print the startup probe again.
"""

import os
import sys
import time

import board
import busio

try:
    import digitalio
except ImportError:
    digitalio = None

try:
    import neopixel
except ImportError:
    neopixel = None

try:
    import supervisor
except ImportError:
    supervisor = None

try:
    import microcontroller
except ImportError:
    microcontroller = None


BAUDRATE = 57600
UART_TIMEOUT_S = 0.02
READ_TIMEOUT_S = 0.5
COMMAND_TIMEOUT_S = 1.25
MAX_FRAME_PAYLOAD = 512

# NeoPixel status indicator. A single pixel on a breakout, DI wired to the
# board pin resolved from the candidates below (see WIRING.md). The pixel
# blinks a per-RORG colour for every received telegram.
NEOPIXEL_PIN_CANDIDATES = ("GPIO10", "GP10", "IO10", "D10")
NEOPIXEL_BRIGHTNESS = 0.25
BLINK_ON_S = 0.08

ESP3_SYNC = 0x55
PT_RADIO_ERP1 = 0x01
PT_RESPONSE = 0x02
PT_RADIO_SUB_TEL = 0x03
PT_EVENT = 0x04
PT_COMMON_COMMAND = 0x05
PT_SMART_ACK_COMMAND = 0x06
PT_REMOTE_MAN_COMMAND = 0x07
PT_RADIO_MESSAGE = 0x09
PT_RADIO_ERP2 = 0x0A

CO_RD_VERSION = 0x03
CO_RD_IDBASE = 0x08


PACKET_TYPES = {
    PT_RADIO_ERP1: "RADIO_ERP1",
    PT_RESPONSE: "RESPONSE",
    PT_RADIO_SUB_TEL: "RADIO_SUB_TEL",
    PT_EVENT: "EVENT",
    PT_COMMON_COMMAND: "COMMON_COMMAND",
    PT_SMART_ACK_COMMAND: "SMART_ACK_COMMAND",
    PT_REMOTE_MAN_COMMAND: "REMOTE_MAN_COMMAND",
    PT_RADIO_MESSAGE: "RADIO_MESSAGE",
    PT_RADIO_ERP2: "RADIO_ERP2",
}

COMMON_COMMANDS = {
    CO_RD_VERSION: "CO_RD_VERSION",
    CO_RD_IDBASE: "CO_RD_IDBASE",
}

RESPONSE_CODES = {
    0x00: "RET_OK",
    0x01: "RET_ERROR",
    0x02: "RET_NOT_SUPPORTED",
    0x03: "RET_WRONG_PARAM",
    0x04: "RET_OPERATION_DENIED",
}

RORG_NAMES = {
    0xF6: "RPS",
    0xD5: "1BS",
    0xA5: "4BS",
    0xD2: "VLD",
    0xD4: "UTE",
    0xD1: "MSC",
    0xC5: "SYS_EX",
}

# NeoPixel colour per RORG telegram family (the RORG field of the EEP
# RORG-FUNC-TYPE name). RGB tuples, scaled by NEOPIXEL_BRIGHTNESS at runtime.
RORG_COLORS = {
    0xF6: (0, 255, 0),      # RPS    rocker / window-handle switches   -> green
    0xD5: (255, 170, 0),    # 1BS    single binary contact             -> amber
    0xA5: (0, 180, 255),    # 4BS    temp / humidity / light / occ.    -> cyan
    0xD2: (0, 0, 255),      # VLD    actuators, metering, multichannel -> blue
    0xD4: (255, 0, 255),    # UTE    universal teach-in                -> magenta
    0xD1: (255, 80, 0),     # MSC    manufacturer specific             -> orange
    0xC5: (255, 255, 255),  # SYS_EX remote management / sys exchange  -> white
}
COLOR_UNKNOWN_RORG = (255, 0, 0)   # radio telegram, unrecognised RORG -> red
COLOR_NON_RADIO = (30, 30, 30)     # valid non-RADIO_ERP1 frame        -> dim white
COLOR_BAD_FRAME = (120, 0, 0)      # CRC / size error                  -> dim red
COLOR_OFF = (0, 0, 0)


def hexs(data, sep=" "):
    return sep.join("%02X" % b for b in data)


def hex_compact(data):
    return hexs(data, "")


def local_time_text():
    try:
        t = time.localtime()
        year = getattr(t, "tm_year", t[0])
        mon = getattr(t, "tm_mon", t[1])
        mday = getattr(t, "tm_mday", t[2])
        hour = getattr(t, "tm_hour", t[3])
        minute = getattr(t, "tm_min", t[4])
        second = getattr(t, "tm_sec", t[5])
        return "%04d-%02d-%02dT%02d:%02d:%02d" % (
            year,
            mon,
            mday,
            hour,
            minute,
            second,
        )
    except Exception:
        return "no_rtc"


def stamp():
    uptime = time.monotonic()
    local = local_time_text()
    if local == "no_rtc":
        return "ts=uptime+%.3fs uptime=%.3f" % (uptime, uptime)
    return "ts=%s uptime=%.3f" % (local, uptime)


def crc8(data):
    """ESP3 CRC8, polynomial 0x07, init 0."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def read_exact(uart, count, deadline):
    buf = bytearray()
    while len(buf) < count:
        if time.monotonic() >= deadline:
            return None
        chunk = uart.read(count - len(buf))
        if chunk:
            buf.extend(chunk)
        else:
            time.sleep(0.001)
    return bytes(buf)


def read_esp3_frame(uart, timeout_s):
    """Read one ESP3 frame.

    Returns a frame dict, None on timeout, or a bad-frame dict with "error".
    """
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        first = uart.read(1)
        if not first:
            time.sleep(0.001)
            continue
        if first[0] == ESP3_SYNC:
            break
    else:
        return None

    header = read_exact(uart, 4, deadline)
    if header is None:
        return None
    header_crc = read_exact(uart, 1, deadline)
    if header_crc is None:
        return None

    raw_prefix = bytes((ESP3_SYNC,)) + header + header_crc
    expected_hcrc = crc8(header)
    if expected_hcrc != header_crc[0]:
        return {
            "error": "header_crc",
            "expected": expected_hcrc,
            "actual": header_crc[0],
            "raw": raw_prefix,
        }

    data_len = (header[0] << 8) | header[1]
    opt_len = header[2]
    packet_type = header[3]
    total_len = data_len + opt_len

    if total_len > MAX_FRAME_PAYLOAD:
        return {
            "error": "frame_too_large",
            "length": total_len,
            "raw": raw_prefix,
        }

    payload = read_exact(uart, total_len, deadline)
    if payload is None:
        return None
    data_crc = read_exact(uart, 1, deadline)
    if data_crc is None:
        return None

    raw = raw_prefix + payload + data_crc
    expected_dcrc = crc8(payload)
    if expected_dcrc != data_crc[0]:
        return {
            "error": "data_crc",
            "expected": expected_dcrc,
            "actual": data_crc[0],
            "raw": raw,
        }

    return {
        "packet_type": packet_type,
        "data_len": data_len,
        "opt_len": opt_len,
        "data": payload[:data_len],
        "opt": payload[data_len:],
        "raw": raw,
    }


def build_esp3_packet(packet_type, data, optional_data=b""):
    data = bytes(data)
    optional_data = bytes(optional_data)
    header = bytes((
        (len(data) >> 8) & 0xFF,
        len(data) & 0xFF,
        len(optional_data) & 0xFF,
        packet_type & 0xFF,
    ))
    payload = data + optional_data
    return (
        bytes((ESP3_SYNC,))
        + header
        + bytes((crc8(header),))
        + payload
        + bytes((crc8(payload),))
    )


def make_uart():
    try:
        return busio.UART(
            board.TX,
            board.RX,
            baudrate=BAUDRATE,
            timeout=UART_TIMEOUT_S,
            receiver_buffer_size=4096,
        )
    except TypeError:
        return busio.UART(
            board.TX,
            board.RX,
            baudrate=BAUDRATE,
            timeout=UART_TIMEOUT_S,
        )


def make_led():
    if digitalio is None or not hasattr(board, "LED"):
        return None
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
    return led


def make_pixel():
    """Create the status NeoPixel.

    Returns (pixel, status). On success pixel is a NeoPixel and status is the
    resolved "board.<pin>" string. On failure pixel is None and status is a
    short reason: no_neopixel_lib, no_pin, or init_error:<pin>.
    """
    if neopixel is None:
        return None, "no_neopixel_lib"
    for name in NEOPIXEL_PIN_CANDIDATES:
        if not hasattr(board, name):
            continue
        try:
            pixel = neopixel.NeoPixel(
                getattr(board, name),
                1,
                brightness=NEOPIXEL_BRIGHTNESS,
                auto_write=True,
            )
        except Exception:
            return None, "init_error:%s" % name
        pixel.fill(COLOR_OFF)
        return pixel, "board.%s" % name
    return None, "no_pin"


def telegram_color(frame):
    """RGB colour for a received frame, keyed on the EnOcean RORG family."""
    if "error" in frame:
        return COLOR_BAD_FRAME
    if frame.get("packet_type") != PT_RADIO_ERP1:
        return COLOR_NON_RADIO
    data = frame.get("data") or b""
    if not data:
        return COLOR_NON_RADIO
    return RORG_COLORS.get(data[0], COLOR_UNKNOWN_RORG)


def flush_uart(uart):
    while True:
        try:
            waiting = uart.in_waiting
        except AttributeError:
            waiting = 0
        if not waiting:
            return
        uart.read(waiting)
        time.sleep(0.01)


def safe_ascii(data):
    out = []
    for b in data:
        if 32 <= b <= 126:
            out.append(chr(b))
        elif b == 0:
            break
        else:
            out.append(".")
    return "".join(out).strip()


def response_name(code):
    return RESPONSE_CODES.get(code, "RET_0x%02X" % code)


def packet_type_name(packet_type):
    return PACKET_TYPES.get(packet_type, "PT_0x%02X" % packet_type)


def rorg_name(rorg):
    return RORG_NAMES.get(rorg, "RORG_0x%02X" % rorg)


def radio_erp1_fields(frame):
    data = frame["data"]
    opt = frame["opt"]
    if len(data) < 6:
        return "radio_error=short_radio_erp1"

    rorg = data[0]
    payload = data[1:-5]
    sender = data[-5:-1]
    status = data[-1]

    parts = [
        "rorg=%s(0x%02X)" % (rorg_name(rorg), rorg),
        "sender=%s" % hex_compact(sender),
        "status=0x%02X" % status,
        "payload=%s" % hexs(payload),
    ]

    if len(opt) >= 7:
        parts.extend((
            "subtel=%d" % opt[0],
            "dest=%s" % hex_compact(opt[1:5]),
            "rssi_dbm=-%d" % opt[5],
            "security=0x%02X" % opt[6],
        ))
    elif opt:
        parts.append("opt=%s" % hexs(opt))

    return " ".join(parts)


def response_fields(frame):
    data = frame["data"]
    if not data:
        return "response=empty"
    return "return=%s(0x%02X) data_tail=%s" % (
        response_name(data[0]),
        data[0],
        hexs(data[1:]),
    )


def frame_summary(frame):
    packet_type = frame["packet_type"]
    parts = [
        "type=%s(0x%02X)" % (packet_type_name(packet_type), packet_type),
        "data_len=%d" % frame["data_len"],
        "opt_len=%d" % frame["opt_len"],
    ]

    if packet_type == PT_RADIO_ERP1:
        parts.append(radio_erp1_fields(frame))
    elif packet_type == PT_RESPONSE:
        parts.append(response_fields(frame))
    else:
        parts.append("data=%s" % hexs(frame["data"]))
        if frame["opt"]:
            parts.append("opt=%s" % hexs(frame["opt"]))

    parts.append("raw=%s" % hexs(frame["raw"]))
    return " ".join(parts)


def print_frame(frame, stats, note=None):
    if frame is None:
        return

    if "error" in frame:
        stats["bad"] += 1
        details = [
            stamp(),
            "BAD",
            "error=%s" % frame["error"],
        ]
        if "expected" in frame:
            details.append("expected_crc=0x%02X" % frame["expected"])
        if "actual" in frame:
            details.append("actual_crc=0x%02X" % frame["actual"])
        if "length" in frame:
            details.append("length=%d" % frame["length"])
        details.append("raw=%s" % hexs(frame.get("raw", b"")))
        print(" ".join(details))
        return

    stats["frames"] += 1
    prefix = "%s frame=%06d" % (stamp(), stats["frames"])
    if note:
        prefix += " note=%s" % note
    print("%s %s" % (prefix, frame_summary(frame)))


def request_common_command(uart, command, stats):
    command_name = COMMON_COMMANDS.get(command, "CO_0x%02X" % command)
    print("%s event=command_send command=%s(0x%02X)" % (
        stamp(),
        command_name,
        command,
    ))
    uart.write(build_esp3_packet(PT_COMMON_COMMAND, bytes((command,))))

    deadline = time.monotonic() + COMMAND_TIMEOUT_S
    while time.monotonic() < deadline:
        frame = read_esp3_frame(uart, min(0.25, deadline - time.monotonic()))
        if frame is None:
            continue
        if "error" in frame:
            print_frame(frame, stats, note="during_command")
            continue
        if frame["packet_type"] == PT_RESPONSE:
            return frame
        print_frame(frame, stats, note="during_command")
    return None


def print_version_response(frame):
    command = "CO_RD_VERSION"
    if frame is None:
        print("%s event=module_info command=%s response=timeout" % (
            stamp(),
            command,
        ))
        return

    data = frame["data"]
    if not data:
        print("%s event=module_info command=%s response=empty" % (
            stamp(),
            command,
        ))
        return

    ret = data[0]
    if ret != 0x00:
        print("%s event=module_info command=%s return=%s(0x%02X) raw=%s" % (
            stamp(),
            command,
            response_name(ret),
            ret,
            hexs(data),
        ))
        return

    app = data[1:5]
    api = data[5:9]
    chip_id = data[9:13]
    chip_version = data[13:17]
    description = safe_ascii(data[17:])
    print(
        "%s event=module_info command=%s return=RET_OK "
        "app_version=%s api_version=%s chip_id=%s chip_version=%s "
        "description=\"%s\" raw=%s"
        % (
            stamp(),
            command,
            hex_compact(app),
            hex_compact(api),
            hex_compact(chip_id),
            hex_compact(chip_version),
            description,
            hexs(data),
        )
    )


def print_idbase_response(frame):
    command = "CO_RD_IDBASE"
    if frame is None:
        print("%s event=module_info command=%s response=timeout" % (
            stamp(),
            command,
        ))
        return

    data = frame["data"]
    if not data:
        print("%s event=module_info command=%s response=empty" % (
            stamp(),
            command,
        ))
        return

    ret = data[0]
    if ret != 0x00:
        print("%s event=module_info command=%s return=%s(0x%02X) raw=%s" % (
            stamp(),
            command,
            response_name(ret),
            ret,
            hexs(data),
        ))
        return

    base_id = data[1:5]
    remaining = data[5] if len(data) > 5 else -1
    print(
        "%s event=module_info command=%s return=RET_OK "
        "base_id=%s remaining_writes=%d raw=%s"
        % (
            stamp(),
            command,
            hex_compact(base_id),
            remaining,
            hexs(data),
        )
    )


def print_startup():
    machine = "unknown"
    runtime = sys.version.replace("\n", " ")
    try:
        uname = os.uname()
        machine = uname.machine
        runtime = "%s %s %s" % (
            getattr(uname, "sysname", "CircuitPython"),
            getattr(uname, "release", sys.version),
            getattr(uname, "version", ""),
        )
    except Exception:
        pass

    print("")
    print("# Generic ESP3 EnOcean monitor")
    print("%s event=start board=\"%s\" runtime=\"%s\"" % (
        stamp(),
        machine,
        runtime,
    ))
    print("%s event=uart_config uart=board.TX/board.RX baud=%d format=8N1" % (
        stamp(),
        BAUDRATE,
    ))
    print("%s event=output_format destination=USB_serial raw_frames=true" % stamp())


def print_ready(stats):
    print("%s event=ready frames=%d bad=%d" % (
        stamp(),
        stats["frames"],
        stats["bad"],
    ))


def reload_board():
    print("%s event=reload reason=ctrl_c" % stamp())
    time.sleep(0.25)
    if supervisor is not None:
        supervisor.reload()
    if microcontroller is not None:
        microcontroller.reset()
    raise KeyboardInterrupt


def main():
    stats = {"frames": 0, "bad": 0}
    print_startup()
    uart = make_uart()
    led = make_led()
    pixel, pixel_status = make_pixel()
    if pixel is not None:
        print("%s event=neopixel_config pin=%s brightness=%.2f blink_s=%.3f" % (
            stamp(),
            pixel_status,
            NEOPIXEL_BRIGHTNESS,
            BLINK_ON_S,
        ))
    else:
        print("%s event=neopixel_config status=disabled reason=%s" % (
            stamp(),
            pixel_status,
        ))
    flush_uart(uart)

    version = request_common_command(uart, CO_RD_VERSION, stats)
    print_version_response(version)

    idbase = request_common_command(uart, CO_RD_IDBASE, stats)
    print_idbase_response(idbase)

    flush_uart(uart)
    print_ready(stats)

    pixel_off_at = 0.0
    while True:
        frame = read_esp3_frame(uart, READ_TIMEOUT_S)
        now = time.monotonic()
        # Non-blocking blink: turn the pixel off once its on-time has elapsed.
        if pixel is not None and pixel_off_at and now >= pixel_off_at:
            pixel.fill(COLOR_OFF)
            pixel_off_at = 0.0
        if frame is None:
            continue
        if led is not None and "error" not in frame:
            led.value = not led.value
        if pixel is not None:
            pixel.fill(telegram_color(frame))
            pixel_off_at = now + BLINK_ON_S
        print_frame(frame, stats)


while True:
    try:
        main()
    except KeyboardInterrupt:
        reload_board()
    except Exception as exc:
        print("%s event=fatal_exception type=%s message=\"%s\"" % (
            stamp(),
            exc.__class__.__name__,
            str(exc),
        ))
        try:
            sys.print_exception(exc)
        except Exception:
            pass
        time.sleep(5.0)
        if supervisor is not None:
            supervisor.reload()
        if microcontroller is not None:
            microcontroller.reset()
        raise
