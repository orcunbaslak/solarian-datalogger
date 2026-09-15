# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""ABB PVS800 central inverter, Modbus TCP.

Register map, as published by ABB. Addresses are the documented 4xxxx numbers;
offsets are positions within each block.

  MAIN  42496 +7 (holding)
    +1  inverter main status word              bf16
    +2  active power                           int16    1      kW
    +3  reactive power                         int16    1      kVAr
    +4  grid voltage                           uint16   0.1    V
    +5  grid frequency                         uint16   0.01   Hz
    +6  power factor                           int16    0.001

  MEASUREMENTS  42545 +27 (holding)
    +0  code of the active fault               uint16
    +1..+3  main voltage U-V, V-W, W-U         uint16   0.1    V
    +4  grid current                           uint16   0.1    A
    +5  DC input voltage                       uint16   0.1    V
    +6  DC bus voltage                         uint16   0.1    V
    +7  DC input current                       uint16   0.1    A
    +8  grounding current                      uint16   1      mA
    +9  isolation resistance                   uint16   1      kOhm
    +10 ambient temperature                    int16    0.1    degC
    +11..+14 highest IGBT temperature PU1..PU4 int16    0.1    degC
    +15 control section temperature            int16    0.1    degC
    +19/+20 daily kWh supplied      high/low word
    +21/+22 total kWh supplied      high/low word
    +23/+24 daily kVAh supplied     high/low word
    +25/+26 total kVAh supplied     high/low word

  STATUS  42599 +8 (holding)
    +1  limitation status word                 bf16
    +3  MPPT status word                       bf16
    +4  grid status word                       bf16
    +5  fan status word                        bf16
    +7  environmental status word              bf16

Bit 10 of the limitation word is reserved by ABB and is deliberately not
emitted. Offsets +16..+18 of the measurement block are unused.
"""

from solarian.decode import U16, I16, U32, Bitfield
from solarian.driver import Driver, Block
from solarian.modbus import HOLDING

MAIN_STATUS = {
    0: 'ReadyToSwitchOn',
    1: 'Faulted',
    2: 'Warning',
    3: 'MPPTEnabled',
    4: 'GridStable',
    5: 'DCVoltageWithinLimits',
    6: 'StartInhibited',
    7: 'ReducedRun',
    8: 'RedundantRun',
    9: 'QCompansation',
    10: 'Limited',
    11: 'GridConnected',
}

LIMITING_STATUS = {
    0: 'IGBTTempCurrentLimitation',
    1: 'PfLimitation',
    2: 'PuLimitation',
    3: 'GridFaultLimitation',
    4: 'ExternalPowerLimit',
    5: 'FRTRecoveryLimit',
    6: 'ShutdownRampLimit',
    7: 'PowerGradientLimit',
    8: 'FRTInteraction',
    9: 'AmbientTempLimitation',
    # bit 10 reserved by ABB
    11: 'PowerSectionTempLimitation',
}

MPPT_STATUS = {
    0: 'MPPTMode',
    1: 'PowerLimitationActive',
    2: 'MinVoltageLimitActive',
    3: 'MaxVoltageLimitActive',
}

GRID_STATUS = {
    0: 'Undervoltage',
    1: 'Overvoltage',
    2: 'Underfrequency',
    3: 'Overfrequency',
    4: 'AntiIslandingTrip',
    5: 'RoCoFTrip',
    6: 'CombinatoryTrip',
    7: 'MovingAverageTrip',
    8: 'ZeroCrossingTrip',
    9: 'LVRTTrip',
    10: 'HVRTTrip',
    11: 'ExternalMonitorTrip',
}

FAN_STATUS = {
    0: 'PowerUnit1',
    1: 'PowerUnit2',
    2: 'PowerUnit3',
    3: 'PowerUnit4',
    4: 'ISU1Fan',
    5: 'ISU2Fan',
    6: 'DoorFanCircuitBreaker',
}

ENVIRONMENT_STATUS = {
    0: 'ACBusbarThermalProtection',
    1: 'DCBusbarThermalProtection',
    2: 'ColdAmbientTempWarning',
    3: 'ColdAmbientTempFault',
    4: 'HotAmbientTempWarning',
    5: 'HotAmbientTempFault',
    6: 'IGBTTempWarning',
    7: 'IGBTTempFault',
}

DRIVER = Driver(
    name='ABB_PVS800_TCP',
    version='0.3',
    description='ABB PVS800 central inverter over Modbus TCP',
    blocks=[
        Block('main', HOLDING, 42496, 7, [
            I16(2, 'Active_Power', unit='kW'),
            I16(3, 'Reactive_Power', unit='kVAr'),
            U16(4, 'Grid_Voltage', divide=10, unit='V'),
            U16(5, 'Grid_Frequency', divide=100, unit='Hz'),
            I16(6, 'PowerFactor', divide=1000),
            Bitfield(1, 'Status_Main_', MAIN_STATUS),
        ]),
        Block('measurements', HOLDING, 42545, 27, [
            U16(1, 'L1_Voltage', divide=10, unit='V'),
            U16(2, 'L2_Voltage', divide=10, unit='V'),
            U16(3, 'L3_Voltage', divide=10, unit='V'),
            U16(4, 'Grid_Current', divide=10, unit='A'),
            U16(5, 'DC_Input_Voltage', divide=10, unit='V'),
            U16(6, 'DC_Bus_Voltage', divide=10, unit='V'),
            U16(7, 'DC_Input_Current', divide=10, unit='A'),
            U16(8, 'Grounding_Current', unit='mA'),
            U16(9, 'Isolation_Resistance', unit='kOhm'),
            I16(10, 'Inverter_Ambient_Temp', divide=10, unit='degC'),
            I16(11, 'Highest_IGBT_Temp_PU1', divide=10, unit='degC'),
            I16(12, 'Highest_IGBT_Temp_PU21', divide=10, unit='degC'),
            I16(13, 'Highest_IGBT_Temp_PU31', divide=10, unit='degC'),
            I16(14, 'Highest_IGBT_Temp_PU41', divide=10, unit='degC'),
            I16(15, 'Control_Section_Temp', divide=10, unit='degC'),
            U32(19, 20, 'Daily_kWh', decimals=3, unit='kWh'),
            U32(21, 22, 'Total_kWh', decimals=1, multiply=10, unit='kWh'),
            U32(23, 24, 'Daily_kVAh', decimals=3, unit='kVAh'),
            U32(25, 26, 'Total_kVAh', decimals=1, multiply=10, unit='kVAh'),
        ]),
        Block('status', HOLDING, 42599, 8, [
            Bitfield(1, 'Status_Limiting_', LIMITING_STATUS),
            Bitfield(3, 'Status_MPPT_', MPPT_STATUS),
            Bitfield(4, 'Status_Grid_', GRID_STATUS),
            Bitfield(5, 'Status_Fan_', FAN_STATUS),
            Bitfield(7, 'Status_Environment_', ENVIRONMENT_STATUS),
        ]),
    ],
)
