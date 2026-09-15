# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2021 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Kernel ST0HS2425 DC combiner box, 24 string channels, Modbus TCP.

Register map as published by Kernel. Addresses are the documented 3xxxx input
register numbers; offsets are positions within the block.

  MEASUREMENTS  51 +47 (input registers, 30052 in PLC numbering)
    +0..+23  string currents I_DC_1..I_DC_24   uint16   1      mA
    +32      combiner bus voltage  (30084)     uint16   1      V
    +37      cabinet temperature   (30089)     uint16   1      degC
    +38      board temperature     (30090)     uint16   1      degC
    +39      total current         (30091)     uint16   0.1    A
    +40      power, low word       (30092)     uint16   1      W
    +41      power, high word      (30093)     uint16   1      W

The whole span is fetched as one 47-register sweep: a combiner box answers a
single long read far faster than a dozen short ones. Offsets +24..+31, +33..+36
and +42..+46 fall inside that sweep but are undocumented, so they are read and
discarded rather than emitted under invented names.

The power register pair is stored low word first, which is why the 32-bit value
is assembled from +41/+40 and not +40/+41.

The sibling driver ``dcb_kernel_st0hs2425_single`` covers the same hardware
wired as a single-channel box; the two maps share no field, so nothing is
factored out between them.
"""

from solarian.decode import U16, U32
from solarian.driver import Driver, Block
from solarian.modbus import INPUT

# One register per string, in channel order, reported in milliamps.
STRING_CURRENTS = [
    U16(offset, 'I_DC_%d' % (offset + 1), divide=1000, unit='A')
    for offset in range(24)
]

DRIVER = Driver(
    name='KERNEL_DCB_ST0HS2425',
    version='0.2',
    description='Kernel ST0HS2425 DC combiner box over Modbus TCP',
    blocks=[
        Block('measurements', INPUT, 51, 47, STRING_CURRENTS + [
            U16(32, 'V_DC', unit='V'),
            U16(37, 'Cabinet_Temp', unit='degC'),
            U16(38, 'Board_Temp', unit='degC'),
            U16(39, 'Total_Current', divide=10, unit='A'),
            U32(41, 40, 'Power', unit='W'),
        ]),
    ],
)
