# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Turning raw Modbus registers into named, scaled values.

A driver declares its register map as a list of field specs. Each spec knows
its offset within a block and how to interpret the register(s) there, so the
map is executable data rather than a comment sitting next to hand-written
arithmetic that can drift away from it.

Scaling is expressed as an integer DIVISOR, never as a float factor. This is
not a style preference: ``x / 10`` and ``x * 0.1`` disagree for 22943 of the
65536 possible uint16 values, so a float factor would silently shift roughly a
third of all readings.
"""

import struct
from collections import OrderedDict


def signed(value):
    """Reinterpret a uint16 register as a signed int16."""
    return struct.unpack('<h', struct.pack('<H', value & 0xFFFF))[0]


def u32(registers, high, low):
    """Join two registers into an unsigned 32-bit value, high word first."""
    packed = struct.pack('>HH', registers[high] & 0xFFFF, registers[low] & 0xFFFF)
    return struct.unpack('>L', packed)[0]


def i32(registers, high, low):
    """Join two registers into a signed 32-bit value, high word first."""
    packed = struct.pack('>HH', registers[high] & 0xFFFF, registers[low] & 0xFFFF)
    return struct.unpack('>l', packed)[0]


def _scaled(raw, divide, multiply):
    """Apply scaling in a fixed order: divide first, then multiply.

    The order is load-bearing — it reproduces the arithmetic the hand-written
    drivers performed, and floating point is not associative.
    """
    value = float(raw) / divide
    if multiply is not None:
        value = value * multiply
    return value


class Field(object):
    """Base class for one decoded value within a register block."""

    __slots__ = ('name', 'unit', 'note')

    def __init__(self, name, unit=None, note=None):
        self.name = name
        self.unit = unit
        self.note = note

    def emit(self, registers, out):
        raise NotImplementedError

    # Fields describe themselves so a register map can be printed or exported.
    def describe(self):
        return {'name': self.name, 'kind': type(self).__name__,
                'unit': self.unit, 'note': self.note}


class _Scalar(Field):
    """A field backed by a single register."""

    __slots__ = ('offset', 'divide', 'multiply')

    def __init__(self, offset, name, divide=1, multiply=None, unit=None, note=None):
        super().__init__(name, unit, note)
        self.offset = offset
        self.divide = divide
        self.multiply = multiply

    def raw(self, registers):
        raise NotImplementedError

    def emit(self, registers, out):
        out[self.name] = _scaled(self.raw(registers), self.divide, self.multiply)


class U16(_Scalar):
    """Unsigned 16-bit register."""

    __slots__ = ()

    def raw(self, registers):
        return registers[self.offset] & 0xFFFF


class I16(_Scalar):
    """Signed 16-bit register."""

    __slots__ = ()

    def raw(self, registers):
        return signed(registers[self.offset])


class _Wide(Field):
    """A field backed by two registers, high word first."""

    __slots__ = ('high', 'low', 'divide', 'multiply')

    def __init__(self, high, low, name, decimals=0, divide=None, multiply=None,
                 unit=None, note=None):
        super().__init__(name, unit, note)
        self.high = high
        self.low = low
        # `decimals` is the common shorthand for a power-of-ten divisor.
        self.divide = divide if divide is not None else 10 ** decimals
        self.multiply = multiply

    def raw(self, registers):
        raise NotImplementedError

    def emit(self, registers, out):
        out[self.name] = _scaled(self.raw(registers), self.divide, self.multiply)


class U32(_Wide):
    """Unsigned 32-bit value spanning two registers."""

    __slots__ = ()

    def raw(self, registers):
        return u32(registers, self.high, self.low)


class I32(_Wide):
    """Signed 32-bit value spanning two registers."""

    __slots__ = ()

    def raw(self, registers):
        return i32(registers, self.high, self.low)


class Bitfield(Field):
    """A status word expanded into one named 0.0/1.0 flag per bit.

    `bits` maps bit position to a short name. Positions left out of the map are
    not emitted, which keeps reserved and undocumented bits out of the data.
    Names are prefixed so flags from different status words never collide.
    """

    __slots__ = ('offset', 'bits', 'prefix')

    def __init__(self, offset, prefix, bits, unit=None, note=None):
        super().__init__(prefix, unit, note)
        self.offset = offset
        self.prefix = prefix
        self.bits = dict(bits)

    def emit(self, registers, out):
        word = int(registers[self.offset])
        for position in sorted(self.bits):
            out[self.prefix + self.bits[position]] = float((word >> position) & 1)

    def describe(self):
        info = super().describe()
        info['bits'] = dict(self.bits)
        return info


class Raw(Field):
    """The register value itself, unscaled, as an int.

    For values that are codes rather than measurements.
    """

    __slots__ = ('offset',)

    def __init__(self, offset, name, unit=None, note=None):
        super().__init__(name, unit, note)
        self.offset = offset

    def emit(self, registers, out):
        out[self.name] = int(registers[self.offset]) & 0xFFFF


class Computed(Field):
    """A value derived from the block rather than read directly.

    `fn` receives the block's registers and returns the value.
    """

    __slots__ = ('fn',)

    def __init__(self, name, fn, unit=None, note=None):
        super().__init__(name, unit, note)
        self.fn = fn

    def emit(self, registers, out):
        out[self.name] = self.fn(registers)


def decode_block(registers, fields, out=None):
    """Emit every field of a block into an ordered mapping."""
    if out is None:
        out = OrderedDict()
    for field in fields:
        field.emit(registers, out)
    return out
