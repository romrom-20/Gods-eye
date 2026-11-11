"""Bounded, data-only import of the fixed Breakout tensor archive.

No extraction, numpy.load, pickle, model code, inference, or format guessing.
"""
import ast
import base64
import binascii
import io
import json
import os
import stat
import struct
import zipfile
import zlib

import numpy as np

from .core import NAMES

MAX_NPZ = 128 * 1024
MAX_JSON = 192 * 1024
MAX_HEADER = 1024
ERROR = 'Invalid Breakout NPZ: use the documented finite float32 tensor archive'


def compatible(backend):
    # An id or matching layout alone must not opt custom executable backends in.
    from .backends import BreakoutBackend
    return type(backend) is BreakoutBackend


def metadata(name, provenance):
    if type(name) is not str or not 1 <= len(name) <= 80 or not name.strip():
        raise ValueError('Name must contain 1–80 characters')
    if type(provenance) is not str or len(provenance) > 2000:
        raise ValueError('Provenance must contain 0–2,000 characters')


def request_payload(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    try:
        if len(raw) > MAX_JSON:
            raise ValueError()
        body = json.loads(raw, object_pairs_hook=pairs)
        if type(body) is not dict or set(body) != {'name', 'provenance', 'npz_base64'}:
            raise ValueError()
        metadata(body['name'], body['provenance'])
        encoded = body['npz_base64']
        if type(encoded) is not str or not 1 <= len(encoded) <= 4 * ((MAX_NPZ + 2) // 3):
            raise ValueError()
        data = base64.b64decode(encoded, validate=True)
        # Also reject noncanonical pad bits, excess padding and alternate encodings.
        if len(data) > MAX_NPZ or base64.b64encode(data).decode('ascii') != encoded:
            raise ValueError()
        return data, body['name'], body['provenance']
    except (ValueError, TypeError, RecursionError, UnicodeError, binascii.Error):
        raise ValueError('Invalid import request: exact name, provenance and strict npz_base64 required') from None


def read_local(path):
    """Bounded regular-file read; never save a source pathname as provenance."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_NPZ:
            raise ValueError('Import requires a regular NPZ file of at most 128 KiB')
        stream = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    with stream:
        raw = stream.read(MAX_NPZ + 1)
    if len(raw) > MAX_NPZ:
        raise ValueError('NPZ exceeds 128 KiB')
    return raw


def read_weights(raw):
    """Validate all bounded members/headers before constructing any tensor arrays."""
    try:
        if type(raw) is not bytes or not 22 <= len(raw) <= MAX_NPZ:
            raise ValueError()
        # No preambles, trailing payloads, comments, multi-disk, or ZIP64 directory.
        end = struct.unpack('<4s4H2LH', raw[-22:])
        sig, disk, central_disk, count_disk, count, size, offset, comment = end
        if (sig != b'PK\x05\x06' or disk or central_disk or comment
                or count != len(NAMES) or count_disk != count
                or offset + size != len(raw) - 22):
            raise ValueError()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            expected = {key + '.npy' for key, _ in NAMES.values()}
            if len(members) != len(expected) or {m.filename for m in members} != expected:
                raise ValueError()
            if archive.start_dir != offset:
                raise ValueError()
            position, total = 0, 0
            payloads = {}
            for member in sorted(members, key=lambda m: m.header_offset):
                if (member.header_offset != position or member.flag_bits != 0
                        or member.compress_type not in (0, 8) or member.extra or member.comment):
                    raise ValueError()
                key = member.filename
                shape = next(shape for path, shape in NAMES.values() if path + '.npy' == key)
                tensor_bytes = int(np.prod(shape)) * 4
                if not tensor_bytes <= member.file_size <= tensor_bytes + MAX_HEADER + 10:
                    raise ValueError()
                total += member.file_size
                if total > 100 * 1024:
                    raise ValueError()
                header = struct.unpack_from('<4s5H3L2H', raw, position)
                signature, _, flags, method, _, _, crc, compressed, expanded, nlen, xlen = header
                start = position + 30
                extra = raw[start + nlen:start + nlen + xlen]
                if (signature != b'PK\x03\x04' or flags != member.flag_bits
                        or method != member.compress_type or crc != member.CRC
                        or raw[start:start + nlen] != key.encode('ascii')):
                    raise ValueError()
                # numpy.savez uses ZIP64 local sizes even for tiny arrays.
                if extra:
                    if len(extra) != 20 or extra[:4] != b'\x01\x00\x10\x00':
                        raise ValueError()
                    large_expanded, large_compressed = struct.unpack('<QQ', extra[4:])
                    if (expanded not in (0xffffffff, large_expanded)
                            or compressed not in (0xffffffff, large_compressed)):
                        raise ValueError()
                    expanded, compressed = large_expanded, large_compressed
                if compressed != member.compress_size or expanded != member.file_size:
                    raise ValueError()
                start += nlen + xlen
                position = start + compressed
                if position > offset:
                    raise ValueError()
                packed = raw[start:position]
                if method == 8:
                    decoder = zlib.decompressobj(-15)
                    data = decoder.decompress(packed, expanded + 1)
                    if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail):
                        raise ValueError()
                else:
                    data = packed
                if len(data) != expanded or zlib.crc32(data) != crc:
                    raise ValueError()
                # v1 NPY only: bounded header, exact dtype/order/schema and payload.
                if data[:8] != b'\x93NUMPY\x01\x00':
                    raise ValueError()
                header_size = struct.unpack_from('<H', data, 8)[0]
                if header_size > MAX_HEADER or header_size + 10 > len(data):
                    raise ValueError()
                header_text = data[10:10 + header_size].decode('ascii')
                tree = ast.parse(header_text.strip(), mode='eval')
                if not isinstance(tree.body, ast.Dict):
                    raise ValueError()
                keys = [ast.literal_eval(key) for key in tree.body.keys]
                if len(keys) != 3 or set(keys) != {'descr', 'fortran_order', 'shape'}:
                    raise ValueError()
                header_value = ast.literal_eval(tree)
                actual = header_value['shape']
                if (header_value['descr'] != '<f4' or header_value['fortran_order'] is not False
                        or type(actual) is not tuple or any(type(v) is not int for v in actual)
                        or actual != shape or not header_text.endswith('\n')
                        or len(data) - header_size - 10 != tensor_bytes):
                    raise ValueError()
                payloads[key] = data[header_size + 10:]
            if position != offset:
                raise ValueError()
        result = {name: np.frombuffer(payloads[key + '.npy'], dtype='<f4').reshape(shape).copy()
                  for name, (key, shape) in NAMES.items()}
        if any(not np.isfinite(value).all() for value in result.values()):
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, StopIteration, EOFError, OSError,
            struct.error, zipfile.BadZipFile, zlib.error, NotImplementedError,
            SyntaxError, RecursionError, UnicodeError):
        raise ValueError(ERROR) from None
