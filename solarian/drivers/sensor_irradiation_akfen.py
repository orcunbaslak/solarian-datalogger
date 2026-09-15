# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Inavitas irradiation sensor as deployed at Akfen, Modbus TCP.

A single holding register, read unscaled.

  MEASUREMENT  6 +1 (holding)
    +0  irradiation                           int16    1      W/m2

The register is signed and the sensor drifts a little below zero at night, so
the reading is clamped to zero after decoding. That clamp belongs to this
device rather than to the register's encoding, which is why it is a
postprocess hook and not part of the field spec.
"""

from solarian.decode import I16
from solarian.driver import Driver, Block
from solarian.modbus import HOLDING


def clamp_negative_irradiation(values, blocks, device):
    """Darkness reads a little below zero; report it as zero."""
    if values['Irradiation'] < 0:
        values['Irradiation'] = float(0.0)


DRIVER = Driver(
    name='SENSORS_INAVITAS_IRRADIATION',
    version='0.2',
    description='Inavitas irradiation sensor over Modbus TCP',
    postprocess=clamp_negative_irradiation,
    blocks=[
        Block('measurement', HOLDING, 6, 1, [
            I16(0, 'Irradiation', unit='W/m2'),
        ]),
    ],
)
