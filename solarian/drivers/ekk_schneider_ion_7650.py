# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2021 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Schneider ION 7650 power quality analyser, Modbus TCP.

Register map as configured for the Inavitas export table on these meters. The
ION is freely programmable, so the addresses below are the ones this fleet's
meters were commissioned with, not a factory default — reordering the meter's
export table silently reshuffles every field here.

  MAIN  149 +116 (holding, 40150 in PLC numbering)
    offset  parameter        address  regs  format  scaling
    +0      I a              40150    1     uint16  10
    +1      I b              40151    1     uint16  10
    +2      I c              40152    1     uint16  10
    +9      Freq             40159    1     uint16  10
    +16/+17 Vln a            40166    2     uint32  1
    +18/+19 Vln b            40168    2     uint32  1
    +20/+21 Vln c            40170    2     uint32  1
    +28/+29 Vll ab           40178    2     uint32  1
    +30/+31 Vll bc           40180    2     uint32  1
    +32/+33 Vll ca           40182    2     uint32  1
    +54/+55 kW tot           40204    2     int32   1
    +64/+65 kVAR tot         40214    2     int32   1
    +74/+75 kVA tot          40224    2     int32   1
    +80/+81 kWh del          40230    2     int32   1
    +82/+83 kWh rec          40232    2     int32   1
    +84/+85 kVARh del        40234    2     int32   1
    +86/+87 kVARh rec        40236    2     int32   1
    +115    PF sign tot      40265    1     int16   100

  THD  20 +6 (holding, 40266 in PLC numbering)
    +0      I1 THD mx        40266    1     int16   100
    +1      I2 THD mx        40267    1     int16   100
    +2      I3 THD mx        40268    1     int16   100
    +3      V1 THD mx        40269    1     int16   100
    +4      V2 THD mx        40270    1     int16   100
    +5      V3 THD mx        40271    1     int16   100

The line-to-neutral voltages at +16..+21 are in the meter's table and inside
the block that is read, but they have never been logged; only the line-to-line
pair is. They stay documented here so the offsets of everything after them
remain checkable against the meter.

The second field of that line-to-line group is emitted as ``Vll_ac`` although
the meter calls it Vll bc. The name is wrong but it is the name already in the
time series, so renaming it would break continuity of historical data.

This meter alone asked for ten attempts per read where every other driver in
the tree settled for three, so the budget is carried over as a driver default
rather than lost in the move to a shared retry policy. A device's own
configuration still overrides it.

The original also re-read the whole block whenever Vln a came back as zero, on
the theory that a zero phase voltage meant a truncated response. That check is
not reproduced: it inspected a value the driver never emits, and it could not
actually force another attempt, because the read had already succeeded and its
result was kept. Short and failed reads are the framework's job now.
"""

from solarian.decode import U16, I16, U32, I32
from solarian.driver import Driver, Block
from solarian.modbus import HOLDING

DRIVER = Driver(
    name='SCHNEIDER_ION_7650_TCP_INAVITAS',
    version='0.2',
    description='Schneider ION 7650 power quality analyser over Modbus TCP',
    defaults={'retries': 10},
    blocks=[
        Block('main', HOLDING, 149, 116, [
            U16(0, 'Ia', divide=10, unit='A'),
            U16(1, 'Ib', divide=10, unit='A'),
            U16(2, 'Ic', divide=10, unit='A'),
            U16(9, 'Freq', divide=10, unit='Hz'),
            U32(28, 29, 'Vll_ab', unit='V'),
            U32(30, 31, 'Vll_ac', unit='V'),
            U32(32, 33, 'Vll_ca', unit='V'),
            I32(54, 55, 'kW_tot', unit='kW'),
            I32(64, 65, 'kVAR_tot', unit='kVAr'),
            I32(74, 75, 'kVA_tot', unit='kVA'),
            I32(80, 81, 'kWh_del', unit='kWh'),
            I32(82, 83, 'kWh_rec', unit='kWh'),
            I32(84, 85, 'kVARh_del', unit='kVArh'),
            I32(86, 87, 'kVARh_rec', unit='kVArh'),
            I16(115, 'PF_tot', divide=100),
        ]),
        Block('thd', HOLDING, 20, 6, [
            I16(0, 'I1_THD_max', divide=100, unit='%'),
            I16(1, 'I2_THD_max', divide=100, unit='%'),
            I16(2, 'I3_THD_max', divide=100, unit='%'),
            I16(3, 'V1_THD_max', divide=100, unit='%'),
            I16(4, 'V2_THD_max', divide=100, unit='%'),
            I16(5, 'V3_THD_max', divide=100, unit='%'),
        ]),
    ],
)
