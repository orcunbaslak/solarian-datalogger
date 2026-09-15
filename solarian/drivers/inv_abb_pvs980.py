# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2021 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""ABB PVS980 central inverter, Modbus TCP.

The PVS980 is the multi-module sibling of the PVS800: temperatures, fans and
contactors are reported per power module M1..M4, which is why this map is
roughly four times the size and carries two fan status words instead of one.

Register map, as published by ABB. Addresses are the documented 4xxxx numbers;
offsets are positions within each block.

  CONTROL  42240 +12 (holding)
    +0  heartbeat                              uint16   1
    +1  control word                           bf16
    +2  active power limit                     int16    0.1    %Pmax
    +3  Qref operation mode                    int16    1
    +4  reactive power reference               uint16   1      kVAr
    +5  reactive power reference               uint16   0.1    %Qnom
    +6  PF reference                           uint16   0.001
    +7  Vac reference                          uint16   0.1    V
    +8  active power limit ramp up rate        uint16   1      %Pnom/ms
    +9  active power limit ramp down rate      uint16   1      %Pnom/ms
    +10 reactive power limit ramp up rate      uint16   1      %Qnom/ms
    +11 reactive power limit ramp down rate    uint16   1      %Qnom/ms

  MAIN  42496 +7 (holding)
    +0  heartbeat                              uint16   1
    +1  inverter main status word              bf16
    +2  active power                           int16    1      kW
    +3  reactive power                         int16    1      kVAr
    +4  grid voltage                           uint16   0.1    V
    +5  grid frequency                         uint16   0.01   Hz
    +6  power factor                           int16    0.001

  MEASUREMENTS  42545 +33 (holding)
    +0  code of the active fault               uint16   1
    +1..+3  main voltage U-V, V-W, W-U         uint16   0.1    V
    +4  grid current                           uint16   0.1    A
    +5  DC input voltage                       uint16   0.1    V
    +6  DC bus voltage                         uint16   0.1    V
    +7  DC input current                       uint16   0.1    A
    +8  grounding current                      uint16   1      mA
    +9  isolation resistance                   uint16   1      kOhm
    +10 ambient temperature                    int16    0.1    degC
    +11..+14 highest IGBT temperature M1..M4   int16    0.1    degC
    +15 control section temperature            int16    0.1    degC
    +16..+19 highest cabinet temperature M1..M4 int16   0.1    degC
    +20..+23 LCL section temperature M1..M4    int16    0.1    degC
    +24 inverter section humidity              uint16   0.1    %
    +25/+26 daily kWh supplied      high/low word
    +27/+28 total kWh supplied      high/low word
    +29/+30 daily kVAh supplied     high/low word
    +31/+32 total kVAh supplied     high/low word

  STATUS  42599 +13 (holding)
    +0  electromechanical switching word #1    bf16
    +1  electromechanical switching word #2    bf16   (not emitted)
    +2  inverter main status word              bf16   (not emitted; the copy in
                                                       the MAIN block is used)
    +3  limitation status word                 bf16
    +4  limitation status word #2              bf16   (not emitted)
    +5  MPPT status word                       bf16
    +6  grid status word                       bf16
    +7  fan status word #1, main channels      bf16   (1 means failure)
    +8  fan status word #2, LCL and cabinets   bf16   (1 means failure)
    +9  environmental status word              bf16
    +10 fault status word #1                   bf16
    +11 fault status word #2                   bf16
    +12 alarm status word                      bf16

ABB documents the status words at 42626..42638, but the block has always been
read from 42599 — the same base as the PVS800 status block. The read address is
what the field devices answer, so it is kept; the documented numbers are
recorded above only as ABB published them.

Bit 0 of the environmental word and bit 13 of the limitation word are reserved
by ABB and are deliberately not emitted, as are the heartbeats and the three
status registers marked above.
"""

from solarian.decode import U16, I16, U32, Bitfield
from solarian.driver import Driver, Block
from solarian.modbus import HOLDING

# Commands the SCADA side has written, read back so the log shows which
# external limit was in force when a reading was taken.
CONTROL_WORD = {
    0: 'StopInverter',
    1: 'PriorityMode',
    2: 'NightQCompensation',
    3: 'FaultReset',
    4: 'TransferTrip',
    5: 'RebootInverter',
    6: 'OpenMVBreaker',
    7: 'CloseMVBreaker',
}

ELECTROMECHANICAL = {
    0: 'ACContactorM1',
    1: 'ACContactorM2',
    2: 'ACContactorM3',
    3: 'ACContactorM4',
    4: 'DCContactorM1',
    5: 'DCContactorM2',
    6: 'DCContactorM3',
    7: 'DCContactorM4',
    8: 'ACSwitchM1',
    9: 'ACSwitchM2',
    10: 'ACSwitchM3',
    11: 'ACSwitchM4',
    12: 'DCSwitchM1',
    13: 'DCSwitchM2',
    14: 'DCSwitchM3',
    15: 'DCSwitchM4',
}

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
    10: 'ControlSectionTempLimitation',
    11: 'ACDCSectionTempLimitation',
    12: 'LCLSectionTempLimitation',
    # bit 13 reserved by ABB
    14: 'InputDCDCSectionTempLimitation',
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

# Both fan words set a bit to mean "this fan has failed", not "running".
FAN_STATUS_MAIN = {
    0: 'MainChannel1Fan1',
    1: 'MainChannel1Fan2',
    2: 'MainChannel1Fan3',
    3: 'MainChannel1Fan4',
    4: 'MainChannel2Fan1',
    5: 'MainChannel2Fan2',
    6: 'MainChannel2Fan3',
    7: 'MainChannel2Fan4',
    8: 'MainChannel3Fan1',
    9: 'MainChannel3Fan2',
    10: 'MainChannel3Fan3',
    11: 'MainChannel3Fan4',
    12: 'MainChannel4Fan1',
    13: 'MainChannel4Fan2',
    14: 'MainChannel4Fan3',
    15: 'MainChannel4Fan4',
}

FAN_STATUS_LCL = {
    0: 'LCLM1Fan1',
    1: 'LCLM1Fan2',
    2: 'LCLM2Fan1',
    3: 'LCLM2Fan2',
    4: 'LCLM3Fan1',
    5: 'LCLM3Fan2',
    6: 'LCLM4Fan1',
    7: 'LCLM4Fan2',
    8: 'ACDCIndoorFanM1',
    9: 'ACDCIndoorFanM2',
    10: 'ACDCIndoorFanM3',
    11: 'ACDCIndoorFanM4',
}

ENVIRONMENT_STATUS = {
    # bit 0 reserved by ABB
    1: 'OverTempDetected',
    2: 'ColdAmbientTempDetected',
    3: 'ExcessHumidityDetected',
    4: 'CabinetHeatingOn',
    5: 'HotAmbientTempDetected',
    6: 'ColdPowerSectionTemp',
}

FAULT_STATUS_1 = {
    0: 'FastPoweroff',
    1: 'AmbientSituation',
    2: 'GroundingCurrent',
    3: 'InsulationResistance',
    4: 'GroundingCircuitVoltage',
    5: 'ReverseCurrentFault',
    6: 'DCOvercurrentFault',
    7: 'PLCLinkFault',
    8: 'FanFault',
    9: 'ACContactor',
    10: 'DCContactor',
    11: 'DCSwitch',
    12: 'MainCircuitSPDFault',
    13: 'DCFuse',
    14: '48VPowerSupply',
    15: 'InternalSWFault1',
}

FAULT_STATUS_2 = {
    0: '48VBuffer',
    1: '24VBuffer',
    2: 'AuxCircuit',
    3: 'LCLPressureSensor',
    4: 'Door',
    5: 'ACBreaker',
    6: 'ACOvercurrent',
    7: 'ShortCircuit',
    8: 'BUCurrentDifference',
    9: 'InputPhaseLoss',
    10: 'ControlSectionOverTemp',
    11: 'IGBTOverTemp',
    12: 'ACDCCabinetOverTemp',
    13: 'LCLSectionOverTemp',
    14: 'PowerUnitLost',
    15: 'InternalSWFault2',
}

ALARM_STATUS = {
    0: 'GroundingCurrentSuddenChange',
    1: 'ResidualCurrent',
    2: 'GroundingCurrentOvervoltage',
    3: 'InsulationResistance',
    4: 'TempSensorAlarm',
    5: 'SCADADataInputOutOfRange',
    6: 'DCLinkOvervoltage',
    7: 'DCInputOvervoltage',
    8: 'MainCircuit',
    9: 'SPD',
    10: '48VPowerSupply',
    11: '48VBuffer',
    12: '24VBuffer',
    13: 'AuxCircuitBreaker',
    14: 'LCLPressureSensor',
    15: 'ACDCDoor',
}

DRIVER = Driver(
    name='ABB_PVS980_TCP',
    version='0.2',
    description='ABB PVS980 central inverter over Modbus TCP',
    blocks=[
        Block('control', HOLDING, 42240, 12, [
            # ABB documents +6..+11 as unsigned; the field reading has always
            # been signed, and the stored history depends on it.
            I16(2, 'Active_Power_Limit', divide=10, unit='%Pmax'),
            I16(3, 'QRef_Operation_Mode'),
            U16(4, 'Reactive_Power_Ref_kVAR', unit='kVAr'),
            U16(5, 'Reactive_Power_Ref_Per', divide=10, unit='%Qnom'),
            I16(6, 'PF_Reference', divide=1000),
            I16(7, 'Vac_Reference', divide=10, unit='V'),
            I16(8, 'Active_RampUp_Rate', unit='%Pnom/ms'),
            I16(9, 'Active_RampDown_Rate', unit='%Pnom/ms'),
            I16(10, 'Reactive_RampUp_Rate', unit='%Qnom/ms'),
            I16(11, 'Reactive_RampDown_Rate', unit='%Qnom/ms'),
            Bitfield(1, 'Status_ControlWord_', CONTROL_WORD),
        ]),
        Block('main', HOLDING, 42496, 7, [
            I16(2, 'Active_Power', unit='kW'),
            I16(3, 'Reactive_Power', unit='kVAr'),
            U16(4, 'Grid_Voltage', divide=10, unit='V'),
            U16(5, 'Grid_Frequency', divide=100, unit='Hz'),
            I16(6, 'PowerFactor', divide=1000),
            Bitfield(1, 'Status_Main_', MAIN_STATUS),
        ]),
        Block('measurements', HOLDING, 42545, 33, [
            U16(0, 'Code_ActiveFault'),
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
            I16(11, 'Highest_IGBT_Temp_M1', divide=10, unit='degC'),
            I16(12, 'Highest_IGBT_Temp_M2', divide=10, unit='degC'),
            I16(13, 'Highest_IGBT_Temp_M3', divide=10, unit='degC'),
            I16(14, 'Highest_IGBT_Temp_M4', divide=10, unit='degC'),
            I16(15, 'Control_Section_Temp', divide=10, unit='degC'),
            I16(16, 'Highest_Cabinet_Temp_M1', divide=10, unit='degC'),
            I16(17, 'Highest_Cabinet_Temp_M2', divide=10, unit='degC'),
            I16(18, 'Highest_Cabinet_Temp_M3', divide=10, unit='degC'),
            I16(19, 'Highest_Cabinet_Temp_M4', divide=10, unit='degC'),
            I16(20, 'Highest_LCL_Temp_M1', divide=10, unit='degC'),
            I16(21, 'Highest_LCL_Temp_M2', divide=10, unit='degC'),
            I16(22, 'Highest_LCL_Temp_M3', divide=10, unit='degC'),
            I16(23, 'Highest_LCL_Temp_M4', divide=10, unit='degC'),
            # Humidity cannot be negative, but the reading is signed here and
            # in the history; ABB documents the register as unsigned.
            I16(24, 'Inverter_Section_Humidity', divide=10, unit='%'),
            U32(25, 26, 'Daily_kWh', decimals=3, unit='kWh'),
            U32(27, 28, 'Total_kWh', decimals=1, multiply=10, unit='kWh'),
            U32(29, 30, 'Daily_kVAh', decimals=3, unit='kVAh'),
            U32(31, 32, 'Total_kVAh', decimals=1, multiply=10, unit='kVAh'),
        ]),
        Block('status', HOLDING, 42599, 13, [
            Bitfield(0, 'Status_Electromechanical_', ELECTROMECHANICAL),
            Bitfield(3, 'Status_Limiting_', LIMITING_STATUS),
            Bitfield(5, 'Status_MPPT_', MPPT_STATUS),
            Bitfield(6, 'Status_Grid_', GRID_STATUS),
            # Both fan words share one prefix; their bit names do not overlap.
            Bitfield(7, 'Status_Fan_', FAN_STATUS_MAIN),
            Bitfield(8, 'Status_Fan_', FAN_STATUS_LCL),
            Bitfield(9, 'Status_Environment_', ENVIRONMENT_STATUS),
            Bitfield(10, 'Status_Fault_', FAULT_STATUS_1),
            Bitfield(11, 'Status_Fault_', FAULT_STATUS_2),
            Bitfield(12, 'Status_Alarm_', ALARM_STATUS),
        ]),
    ],
)
