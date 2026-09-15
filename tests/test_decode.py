# -*- coding: UTF-8 -*-
"""Register decoding: the arithmetic every reading depends on."""

import struct

import pytest

from solarian.decode import (U16, I16, U32, I32, Bitfield, Raw, Computed,
                             decode_block, signed, u32, i32)


def test_signed_matches_struct_over_the_whole_uint16_range():
    """signed() must agree with a raw struct reinterpretation everywhere.

    Exhaustive rather than sampled: this function scales every temperature and
    power reading in the fleet, and an error at one boundary would be invisible
    in spot checks.
    """
    for value in range(65536):
        expected = struct.unpack('<h', struct.pack('<H', value))[0]
        assert signed(value) == expected


@pytest.mark.parametrize('value,expected', [
    (0, 0), (1, 1), (32767, 32767), (32768, -32768), (65535, -1),
])
def test_signed_boundaries(value, expected):
    assert signed(value) == expected


def test_scaling_uses_a_divisor_not_a_float_factor():
    """x/10 and x*0.1 disagree for about a third of uint16 values.

    Field specs therefore carry an integer divisor. This test pins that down,
    because switching to a float factor would silently shift a third of every
    voltage and temperature series in the historical data.
    """
    disagreeing = [x for x in range(65536) if (x / 10) != (x * 0.1)]
    assert len(disagreeing) == 22943

    for raw in disagreeing[:200]:
        out = decode_block([raw], [U16(0, 'V', divide=10)])
        assert out['V'] == raw / 10


def test_divide_then_multiply_order_is_preserved():
    """Scaling order is load-bearing: floating point is not associative."""
    registers = [0x0001, 0x86A0]
    out = decode_block(registers, [U32(0, 1, 'Total', decimals=1, multiply=10)])
    assert out['Total'] == (float(0x000186A0) / 10) * 10


def test_u32_and_i32_word_order_is_high_then_low():
    registers = [0xFFFF, 0xFFFE]
    assert u32(registers, 0, 1) == 0xFFFFFFFE
    assert i32(registers, 0, 1) == -2


def test_u16_and_i16_apply_the_divisor():
    registers = [21266, 64307]
    out = decode_block(registers, [
        U16(0, 'Grid_Voltage', divide=10),
        I16(1, 'Temp', divide=10),
    ])
    assert out['Grid_Voltage'] == 2126.6
    assert out['Temp'] == float(signed(64307)) / 10


def test_bitfield_emits_only_declared_bits():
    """Reserved bits must stay out of the data, not appear as zeros."""
    out = decode_block([0b1011], [Bitfield(0, 'S_', {0: 'A', 1: 'B', 3: 'D'})])
    assert out == {'S_A': 1.0, 'S_B': 1.0, 'S_D': 1.0}
    assert 'S_C' not in out


def test_bitfield_values_are_floats_for_influx():
    out = decode_block([0b01], [Bitfield(0, 'S_', {0: 'On', 1: 'Off'})])
    assert out['S_On'] == 1.0 and isinstance(out['S_On'], float)
    assert out['S_Off'] == 0.0 and isinstance(out['S_Off'], float)


def test_raw_and_computed_fields():
    out = decode_block([7, 9], [
        Raw(0, 'Fault_Code'),
        Computed('Sum', lambda regs: float(regs[0] + regs[1])),
    ])
    assert out['Fault_Code'] == 7
    assert out['Sum'] == 16.0


def test_decode_block_preserves_declaration_order():
    out = decode_block([1, 2, 3], [U16(2, 'C'), U16(0, 'A'), U16(1, 'B')])
    assert list(out) == ['C', 'A', 'B']


def test_fields_describe_themselves_for_documentation():
    field = U16(4, 'Grid_Voltage', divide=10, unit='V')
    described = field.describe()
    assert described['name'] == 'Grid_Voltage'
    assert described['kind'] == 'U16'
    assert described['unit'] == 'V'
