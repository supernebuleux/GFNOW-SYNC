"""
Minimal VDF binary (de)serializer for Steam shortcuts.vdf.
Compatible subset of ValvePython/vdf (https://github.com/ValvePython/vdf).
Only implements binary_loads / binary_dumps — no text VDF support.
"""
__version__ = "1.0-gfnsync"

import struct
from io import BytesIO

# Binary VDF type markers
BIN_NONE      = 0x00  # Nested dict / sub-map
BIN_STRING    = 0x01  # Null-terminated UTF-8 string
BIN_INT32     = 0x02  # Signed 32-bit integer (little-endian)
BIN_END       = 0x08  # End of current map


def binary_loads(data):
    """Deserialize binary VDF bytes → dict."""
    buf = BytesIO(data)

    def _read_string():
        chars = []
        while True:
            c = buf.read(1)
            if not c or c == b'\x00':
                break
            chars.append(c)
        return b''.join(chars).decode('utf-8', errors='replace')

    def _read_map():
        result = {}
        while True:
            type_byte = buf.read(1)
            if not type_byte:
                break
            t = type_byte[0]
            if t == BIN_END:
                break
            key = _read_string()
            if t == BIN_NONE:
                result[key] = _read_map()
            elif t == BIN_STRING:
                result[key] = _read_string()
            elif t == BIN_INT32:
                raw = buf.read(4)
                if len(raw) == 4:
                    result[key] = struct.unpack('<i', raw)[0]
            else:
                # Unknown type — skip (shouldn't happen in shortcuts.vdf)
                break
        return result

    # Root element
    first = buf.read(1)
    if not first or first[0] != BIN_NONE:
        return {}
    root_key = _read_string()
    return {root_key: _read_map()}


def binary_dumps(obj):
    """Serialize dict → binary VDF bytes."""
    buf = BytesIO()

    def _write_string(s):
        buf.write(s.encode('utf-8'))
        buf.write(b'\x00')

    def _write_map(mapping):
        for key, value in mapping.items():
            if isinstance(value, dict):
                buf.write(bytes([BIN_NONE]))
                _write_string(key)
                _write_map(value)
            elif isinstance(value, str):
                buf.write(bytes([BIN_STRING]))
                _write_string(key)
                _write_string(value)
            elif isinstance(value, int):
                buf.write(bytes([BIN_INT32]))
                _write_string(key)
                # Ensure signed int32 range
                v = value & 0xFFFFFFFF
                if v >= 0x80000000:
                    v -= 0x100000000
                buf.write(struct.pack('<i', v))
        buf.write(bytes([BIN_END]))

    root_key = list(obj.keys())[0]
    buf.write(bytes([BIN_NONE]))
    _write_string(root_key)
    _write_map(obj[root_key])
    buf.write(bytes([BIN_END]))  # Root-level end marker (requis par Steam)
    return buf.getvalue()
