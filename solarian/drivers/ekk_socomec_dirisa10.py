# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""SOCOMEC DIRIS A10 power analyser, Modbus RTU.

This is the one serial device in the tree, and the reason the driver contract
changed. The old ``get_data(ip_address, port, slave_id, device_name,
measurement_suffix)`` signature had nowhere to name a serial line, so this
module used to build its own ``serial.Serial(port='/dev/ttyUSB0',
baudrate=19200, ...)`` and then log the ip_address and port it had been handed
and ignored — two different lies about where the data came from.

Transport is now part of the device's configuration, so what follows is only a
register map. No serial port appears in this file; it belongs in the YAML:

    - name: METER_1
      driver: ekk_socomec_dirisa10
      serial_port: /dev/ttyUSB0
      baudrate: 19200
      bytesize: 8
      parity: N
      stopbits: 1

The meter answers slowly enough that the old module raised MODBUS_TIMEOUT to
5s; that survives as a driver default, which a device may still override.

Register map. Every instantaneous and energy value is a 32-bit quantity
spanning two registers, high word first; offsets are positions within a block.

  MEASUREMENTS  50514 +30 (holding)
    +0/+1    phase-to-phase voltage U12       uint32   0.01    V
    +2/+3    phase-to-phase voltage U23       uint32   0.01    V
    +4/+5    phase-to-phase voltage U31       uint32   0.01    V
    +6/+7    phase-to-neutral voltage V1      uint32   0.01    V
    +8/+9    phase-to-neutral voltage V2      uint32   0.01    V
    +10/+11  phase-to-neutral voltage V3      uint32   0.01    V
    +12/+13  frequency                        uint32   0.01    Hz
    +14/+15  current I1                       uint32   0.001   A
    +16/+17  current I2                       uint32   0.001   A
    +18/+19  current I3                       uint32   0.001   A
    +20/+21  neutral current In               uint32   0.001   A
    +22/+23  active power P                   int32    x10     W
    +24/+25  reactive power Q                 int32    x10     var
    +26/+27  apparent power S                 uint32   x10     VA
    +28/+29  power factor                     int32    0.001

  ENERGY  50780 +10 (holding)
    +0/+1    active energy, imported          uint32   1       Wh
    +2/+3    reactive energy, imported        uint32   1       varh
    +4/+5    apparent energy                  int32    1       VAh
    +6/+7    active energy, exported          int32    1       Wh
    +8/+9    reactive energy, exported        int32    1       varh

  THD  51536 +9 (holding)
    +0..+2   THD of U12, U23, U31             uint16   0.1     %
    +3..+5   THD of V1, V2, V3                uint16   0.1     %
    +6..+8   THD of I1, I2, I3                uint16   0.1     %

The signedness above is the original module's, kept as-is so readings do not
shift under the refactor: P, Q and the power factor are read signed, apparent
power unsigned, and the three energy counters mix the two. The map itself is
the one the original's *code* read — its docstring documented the ABB PVS800
register map instead, a copy-paste that never described this meter.
"""

from solarian.decode import U16, U32, I32
from solarian.driver import Driver, Block
from solarian.modbus import HOLDING

DRIVER = Driver(
    name='SOCOMEC_DIRIS_A10',
    version='0.2',
    description='SOCOMEC DIRIS A10 power analyser over Modbus RTU',
    # The meter is slow to answer on a shared RS-485 line.
    defaults={'timeout': 5.0},
    blocks=[
        Block('measurements', HOLDING, 50514, 30, [
            U32(0, 1, 'U12', decimals=2, unit='V'),
            U32(2, 3, 'U23', decimals=2, unit='V'),
            U32(4, 5, 'U31', decimals=2, unit='V'),
            U32(6, 7, 'V1', decimals=2, unit='V'),
            U32(8, 9, 'V2', decimals=2, unit='V'),
            U32(10, 11, 'V3', decimals=2, unit='V'),
            U32(12, 13, 'F', decimals=2, unit='Hz'),
            U32(14, 15, 'I1', decimals=3, unit='A'),
            U32(16, 17, 'I2', decimals=3, unit='A'),
            U32(18, 19, 'I3', decimals=3, unit='A'),
            U32(20, 21, 'In', decimals=3, unit='A'),
            I32(22, 23, 'P', multiply=10, unit='W'),
            I32(24, 25, 'Q', multiply=10, unit='var'),
            # Unsigned where P and Q are signed: apparent power has no
            # direction, so the top bit is magnitude rather than a sign.
            U32(26, 27, 'S', multiply=10, unit='VA'),
            I32(28, 29, 'Pf', decimals=3),
        ]),
        Block('energy', HOLDING, 50780, 10, [
            U32(0, 1, 'Active_Energy_Positive', unit='Wh'),
            U32(2, 3, 'Reactive_Energy_Positive', unit='varh'),
            I32(4, 5, 'Apparent_Energy', unit='VAh'),
            I32(6, 7, 'Active_Energy_Negative', unit='Wh'),
            I32(8, 9, 'Reactive_Energy_Negative', unit='varh'),
        ]),
        Block('thd', HOLDING, 51536, 9, [
            U16(0, 'THD_U12', divide=10, unit='%'),
            U16(1, 'THD_U23', divide=10, unit='%'),
            U16(2, 'THD_U31', divide=10, unit='%'),
            U16(3, 'THD_V1', divide=10, unit='%'),
            U16(4, 'THD_V2', divide=10, unit='%'),
            U16(5, 'THD_V3', divide=10, unit='%'),
            U16(6, 'THD_I1', divide=10, unit='%'),
            U16(7, 'THD_I2', divide=10, unit='%'),
            U16(8, 'THD_I3', divide=10, unit='%'),
        ]),
    ],
)
