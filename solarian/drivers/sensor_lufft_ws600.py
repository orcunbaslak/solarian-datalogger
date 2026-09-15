# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Lufft WS600 compact weather station, Modbus TCP.

One input-register block covers the whole station. The map is sparse — eight
of the fifty registers are emitted and the rest are read and dropped — so the
offsets below are the only ones this driver claims to understand.

Every value is decoded as a signed int16, including the quantities that cannot
physically go negative. That is the original driver's arithmetic, kept so no
reading shifts across the refactor.

  MEASUREMENTS  0 +50 (input)
    +10  relative humidity                    int16    0.1    %
    +14  air pressure                         int16    0.1    hPa
    +18  wind direction                       int16    0.1    deg
    +27  global radiation                     int16    0.1    W/m2
    +31  air temperature                      int16    0.1    degC
    +35  dew point                            int16    0.1    degC
    +42  wind speed                           int16    0.1    m/s
    +48  precipitation                        int16    0.01   mm
"""

from solarian.decode import I16
from solarian.driver import Driver, Block
from solarian.modbus import INPUT

DRIVER = Driver(
    name='SENSORS_LUFFT_WS600',
    version='0.2',
    description='Lufft WS600 weather station over Modbus TCP',
    blocks=[
        Block('measurements', INPUT, 0, 50, [
            I16(10, 'Relative_Humidity', divide=10, unit='%'),
            I16(14, 'Air_Pressure', divide=10, unit='hPa'),
            I16(18, 'Wind_Direction', divide=10, unit='deg'),
            I16(27, 'GlobalRadiation', divide=10, unit='W/m2'),
            I16(31, 'Air_Temperature', divide=10, unit='degC'),
            I16(35, 'Dew_Point', divide=10, unit='degC'),
            I16(42, 'Wind_Speed', divide=10, unit='m/s'),
            I16(48, 'Precipitation', divide=100, unit='mm'),
        ]),
    ],
)
