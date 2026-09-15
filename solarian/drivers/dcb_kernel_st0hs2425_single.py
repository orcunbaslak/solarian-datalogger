# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2021 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Kernel ST0HS2425 DC combiner box wired as a single string channel, Modbus TCP.

Same hardware and same register base as ``dcb_kernel_st0hs2425``, but a box
carrying one string reports only that channel. It is named I_DC_25, continuing
the numbering of the 24-channel box rather than restarting at 1, so the two
boxes of a combiner group produce non-colliding field names.

  MEASUREMENT  51 +2 (input registers, 30052 in PLC numbering)
    +0  string current I_DC_25                 uint16   1      mA

The read asks for two registers to serve one value. That is what the boxes in
the field have been polled with since they were commissioned, and shortening
the request would change the bytes on the wire for no gain. Offset +1 is
undocumented and is not emitted.

The two drivers are kept separate because they are separate hardware
configurations, not variants selected at run time. They share no field name,
scaling or status word, so there is nothing to factor into a common module.
"""

from solarian.decode import U16
from solarian.driver import Driver, Block
from solarian.modbus import INPUT

DRIVER = Driver(
    name='KERNEL_DCB_ST0HS2425',
    version='0.2',
    description='Kernel ST0HS2425 single-channel DC combiner box over Modbus TCP',
    blocks=[
        Block('measurement', INPUT, 51, 2, [
            U16(0, 'I_DC_25', divide=1000, unit='A'),
        ]),
    ],
)
