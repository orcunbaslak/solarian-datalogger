# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Kipp & Zonen SMP11 pyranometer, Modbus TCP.

A single input register, read unscaled. The SMP11 applies its own calibration
and temperature correction, so the register already holds the corrected
irradiance and the logger adds no scaling of its own.

  MEASUREMENT  5 +1 (input)
    +0  IO_SENSOR1_DATA, calibrated and corrected   int16    1    W/m2

The register is signed, and a thermopile pyranometer genuinely reads a few
W/m2 below zero at night, when the dome radiates to a cold sky. Downstream
consumers treat irradiation as non-negative, so the reading is clamped to zero
after decoding — a property of this device, not of the register's encoding,
hence the postprocess hook rather than a field spec.
"""

from solarian.decode import I16
from solarian.driver import Driver, Block
from solarian.modbus import INPUT


def clamp_negative_irradiation(values, blocks, device):
    """Night-time sky cooling reads below zero; report it as zero."""
    if values['Pyranometer_Irradiation'] < 0:
        values['Pyranometer_Irradiation'] = float(0.0)


DRIVER = Driver(
    name='SENSORS_PYRANOMETER_KIPPZONEN_SMP11',
    version='0.2',
    description='Kipp & Zonen SMP11 pyranometer over Modbus TCP',
    postprocess=clamp_negative_irradiation,
    blocks=[
        Block('measurement', INPUT, 5, 1, [
            I16(0, 'Pyranometer_Irradiation', unit='W/m2'),
        ]),
    ],
)
