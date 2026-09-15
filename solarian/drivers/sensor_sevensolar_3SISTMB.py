# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""7Solar 3SISTMB reference-cell irradiation sensor, Modbus TCP.

A reference cell with two temperature probes. Nine input registers are read
and three are emitted; offsets +1..+6 carry variants the logger does not use.

  MEASUREMENTS  0 +9 (input)
    +0  irradiation                           int16    0.1    W/m2
    +7  reference cell temperature            int16    0.1    degC
    +8  external cell temperature             int16    0.1    degC

A reference cell reads slightly negative in darkness — the cell's offset and
the sensor's own zero do not cancel exactly — so at night the irradiation
channel returns a small negative number. Nothing downstream expects negative
sunlight, so it is clamped to zero after decoding. The clamp is a property of
this device, not of the register, which is why it lives in postprocess rather
than in the field spec.

The original module was named for the sensor but carried the driver name
SENSORS_IRRADIATION_VANARISU; that name is kept so existing series do not
split in two.
"""

from solarian.decode import I16
from solarian.driver import Driver, Block
from solarian.modbus import INPUT


def clamp_negative_irradiation(values, blocks, device):
    """Darkness reads a little below zero; report it as zero."""
    if values['Irradiation'] < 0:
        values['Irradiation'] = float(0.0)


DRIVER = Driver(
    name='SENSORS_IRRADIATION_VANARISU',
    version='0.2',
    description='7Solar 3SISTMB reference cell over Modbus TCP',
    postprocess=clamp_negative_irradiation,
    blocks=[
        Block('measurements', INPUT, 0, 9, [
            I16(0, 'Irradiation', divide=10, unit='W/m2'),
            I16(7, 'Ref_Cell_Temp', divide=10, unit='degC'),
            I16(8, 'Ext_Cell_Temp', divide=10, unit='degC'),
        ]),
    ],
)
