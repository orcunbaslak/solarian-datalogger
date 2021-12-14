# -*- coding: UTF-8 -*-

"""
 * 
 *    Solarian Datalogger - A datalogging software for solar systems using various drivers
 * 
 *    Copyright (C) 2021 Orçun Başlak
 *
 *    This program is free software: you can redistribute it and/or modify
 *    it under the terms of the GNU General Public License as published by
 *    the Free Software Foundation, either version 3 of the License, or
 *    any later version.
 *
 *    This program is distributed in the hope that it will be useful,
 *    but WITHOUT ANY WARRANTY; without even the implied warranty of
 *    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *    GNU General Public License for more details.
 *
 *    You should have received a copy of the GNU General Public License
 *    along with this program.  If not, see <https://www.gnu.org/licenses/>.
 * 
 */
"""

import os
import time
import struct
from struct import pack, unpack
from datetime import datetime
from collections import OrderedDict

import modbus_tk
import modbus_tk.defines as cst
from modbus_tk import modbus_tcp

import logging
log = logging.getLogger('solarian-datalogger')


DRIVER_NAME = 'ABB_PVS980_TCP'
DRIVER_VERSION = '0.1'
MODBUS_TIMEOUT = 3
TRY_AMOUNT = 10

module_name = os.path.splitext(os.path.basename(__file__))[0]

def get_data(ip_address, port, slave_id, device_name, measurement_suffix):
    """Instrument function for ABB PVS980 Inverter.

    Args:
        * ip_address (str)     : ip address of the TCP device
        * port (int)           : port
        * slave_id (int)       : modbus slave id of the device
        * device_name (string) : name of device to include in json
    
    Modbus Addresses of the device are as follows:

    == READ 1 ==
    42496	Heartbeat                               0       	
    42497	Inverter main status word               1            bf16 		
    42498	Active power                            2            int16      1       kW
    42499	Reactive power                          3            int16      1       kVAR
    42500	Grid voltage                            4            uint16     0.1     V
    42501	Grid frequency                          5            uint16     0.01    Hz
    42502	Power factor                            6            int16      0.001
    
    == READ 2 ==
    42545	Code of the active fault                0             uint16 	1	
    42546	Main voltage, U-V                       1             uint16 	0.1	    V
    42547	Main voltage, V-W                       2             uint16 	0.1	    V
    42548	Main voltage W-U                        3             uint16 	0.1	    V
    42549	Grid current                            4             uint16 	0.1	    V
    42550	DC input voltage                        5             uint16 	0.1	    V
    42551	DC bus voltage                          6             uint16 	0.1	    V
    42552	DC input current                        7             uint16 	0.1	    A
    42553	Grounding current3                      8             uint16 	1	    mA
    42554	Isolation resistance3                   9             uint16 	1	    kOhm
    42555	Ambient temperature                     10            int16 	0.1	    °C
    42556	Highest IGBT temperature, M1            11            int16 	0.1	    °C
    42557	Highest IGBT temperature, M2            12            int16 	0.1	    °C
    42558	Highest IGBT temperature, M3            13            int16 	0.1	    °C
    42559	Highest IGBT temperature, M4            14            int16 	0.1	    °C
    42560	Control section temperature             15            int16 	0.1	    °C
    42561	Highest cabinet temperature, M1         16            int16 	0.1	    °C
    42562	Highest cabinet temperature, M2         17            int16 	0.1	    °C
    42563	Highest cabinet temperature, M3         18            int16 	0.1	    °C
    42564	Highest cabinet temperature, M4         19            int16 	0.1	    °C
    42565	LCL section temperature, M1             20            int16 	0.1	    °C
    42566	LCL section temperature, M2             21            int16 	0.1	    °C
    42567	LCL section temperature, M3             22            int16 	0.1	    °C
    42568	LCL section temperature, M4             23            int16 	0.1	    °C
    42569	Inverter section humidity               24            uint16 	0.1	    %
    42570	Daily kWh supplied2, HIGH ORDER BIT     25	          uint16 	0.1	    kWh
    42571	Daily kWh supplied2, LOW ORDER BIT      26            uint16 	0.1	    kWh -USE THIS-
    42572	Total kWh supplied2, HIGH ORDER BIT     27            uint16 	1	    kWh
    42573	Total kWh supplied2, LOW ORDER BIT      28            uint16 	1	    kWh -USE THIS-
    42574	Daily kVAh supplied2, HIGH ORDER BIT    29            uint16 	0.1	    kVAh
    42575	Daily kVAh supplied2, LOW ORDER BIT     30            uint16 	0.1	    kVAh -USE THIS-
    42576	Total kVAh supplied2, HIGH ORDER BIT    31            uint16 	1	    kVAh
    42577	Total kVAh supplied2, LOW ORDER BIT     32            uint16	1	    kVAh -USE THIS-

    == READ 3 ==    
    42626   Electromechanical switching #1          0               bf16
    42627   Electromechanical switching #2 (unused) 1               bf16       
    42628	Inverter main Status Word               2               bf16		
    42629	Limitation status word                  3               bf16
    42630	Limitation status word (unused)         4               bf16
    42631	MPPT Status Word                        5               bf16		
    42632	Grid Status Word                        6               bf16		
    42633	Fan Status Word #1                      7               bf16
    42634	Fan Status Word #2                      8               bf16  
    42635	Environmental Status Word               9               bf16
    42636	Fault Status 1                          10              bf16
    42637	Fault Status 2                          11              bf16	
    42638	Alarm Status                            12              bf16	

    ========= ELECTROMECHANICAL SWITCHING WORD (42626) =========
    0       AC Contactor M1
    1       AC Contactor M2
    2       AC Contactor M3
    3       AC Contactor M4
    4       DC Contactor M1
    5       DC Contactor M2
    6       DC Contactor M3
    7       DC Contactor M4
    8       AC Breaker/Switch M1
    9       AC Breaker/Switch M2
    10      AC Breaker/Switch M3
    11      AC Breaker/Switch M4
    12      DC Breaker/Switch M1
    13      DC Breaker/Switch M2
    14      DC Breaker/Switch M3
    15      DC Breaker/Switch M4

    ========= INVERTER MAIN STATUS WORD (42628) =========
    0       Ready to switch on
    1       Faulted
    2       Warning
    3       MPPT Enabled
    4       Grid Stable
    5       DC Voltage within running limits
    6       Start inhibited
    7       Reduced run
    8       Redundant run
    9       Q-Compensation
    10      Limited

    ========= LIMITATION STATUS WORD (42629) =========
    0       IGBT Temp current limitation
    1       P(f) limitation
    2       P(U) limitation
    3       Grid fault and connect limitation
    4       External power limitation
    5       FRT recovery limitation
    6       Shutdown ramp limitation
    7       Power gradient limitation
    8       FRT Interaction
    9       Ambient temperature current limitation
    10      Control section temperature limitation
    11      AC/DC section temperature limitation
    12      LCL section temperature limitation
    13      RESERVED
    14      Input DC/DC Contactor Current Limitation

    ========= MPPT STATUS WORD (42631) =========
    0       MPPT Mode (0:LowPower - 1:NormalOperation)
    1       Power Limitation Active
    2       Minimum voltage limit active
    3       Maximum voltage limit active

    ========= GRID STATUS WORD (42632) =========
    0       Undervoltage
    1       Overvoltage
    2       Underfrequency
    3       Overfrequency
    4       Anti-Islanding Trip
    5       RoCoF Trip
    6       Combinatory Trip
    7       Moving average trip
    8       Zero crossing trip
    9       LVRT Trip
    10      HVRT Trip
    11      External monitor trip

    ========= FAN STATUS WORD #1 (42633) (1 MEANS FAILURE)=========
    0       Main channel, 1 fan #1
    1       Main channel, 1 fan #2
    2       Main channel, 1 fan #3
    3       Main channel, 1 fan #4
    4       Main channel, 2 fan #1
    5       Main channel, 2 fan #2
    6       Main channel, 2 fan #3
    7       Main channel, 2 fan #4
    8       Main channel, 3 fan #1
    9       Main channel, 3 fan #2
    10      Main channel, 3 fan #3
    11      Main channel, 3 fan #4
    12      Main channel, 4 fan #1
    13      Main channel, 4 fan #2
    14      Main channel, 4 fan #3
    15      Main channel, 4 fan #4

    ========= FAN STATUS WORD #1 (42634) (1 MEANS FAILURE)=========
    0       LCL M1 Fan 1
    1       LCL M1 Fan 2
    2       LCL M2 Fan 1
    3       LCL M2 Fan 2
    4       LCL M3 Fan 1
    5       LCL M3 Fan 2
    6       LCL M4 Fan 1
    7       LCL M4 Fan 2
    8       AC/DC cabinet indoor fans M1
    9       AC/DC cabinet indoor fans M2
    10      AC/DC cabinet indoor fans M3
    11      AC/DC cabinet indoor fans M4

    ========= ENVIRONMENTAL STATUS WORD (42635) (1:ACTIVE - 0:NOT) =========
    0       Reserved
    1       Over temp detected
    2       Cold ambient temp detected
    3       Excess humidity detected
    4       Cabinet heating on
    5       Hot ambient temp
    6       Cold power section temperature

    ========= FAULT STATUS WORD #1 (42636) (1:ACTIVE - 0:NOT) =========
    0       Fast power off
    1       Ambient situation fault (see Environmental status word for more information)
    2       Grounding current fault
    3       Insulation resistance fault
    4       Grounding circuit voltage fault
    5       Reverse current fault
    6       DC overcurrent fault
    7       PLC link fault
    8       Fan fault (see log for more information)
    9       AC contactor fault
    10      DC contactor fault
    11      DC switch fault
    12      Main circuit SPD fault
    13      DC fuse fault
    14      48V Power supply fault
    15      Internal SW fault #1 (MFA)

    ========= FAULT STATUS WORD #2 (42637) (1:ACTIVE - 0:NOT) =========
    0       48V buffer fault
    1       24V buffer fault
    2       Aux circuit fault
    3       LCL pressure sensor fault
    4       Door fault
    5       AC breaker fault
    6       AC overcurrent fault
    7       Short circuit fault
    8       BU current difference fault
    9       Input phase loss fault
    10      Control section over temperature fault
    11      IGBT over temperature fault
    12      AC or DC cabinet over temperature fault
    13      LCL section over temperature fault
    14      Power unit lost
    15      Internal SW fault #2 (SSW)

    ========= ALARM STATUS WORD #1 (42638) (1:TRIGGERED - 0:NOT) =========
    0       Grounding current sudden change
    1       Residual current
    2       Grounding circuit overvoltage
    3       Insulation resistance
    4       Temperature sensor alarm
    5       SCADA input data out of range
    6       DC link overvoltage alarm
    7       DC input overvoltage alarm
    8       Main circuit
    9       Surge protection device (SPD) alarm
    10      48V Power supply alarm
    11      48V buffer alarm
    12      24V buffer alarm
    13      Aux circuit breaker alarm
    14      LCL pressure sensor alarm
    15      AC/DC door alarm

    """

    #Start timer to test for execution time
    start_time = time.time()

    #Prepare the modbus stack
    masterTCP = modbus_tcp.TcpMaster(host=ip_address,port=port)				
    masterTCP.set_timeout(MODBUS_TIMEOUT)
    masterTCP.set_verbose(True)

    #Set logging
    log.debug('Module: %s - Driver: %s - Reading device %s:%s', DRIVER_NAME, device_name, ip_address,port)

    #Create an ordered list to store the values
    values = OrderedDict()

    #Append devicename and timestamp for InfluxDB
    values['Device_Name'] = device_name
    values['Measurement_Suffix'] = measurement_suffix
    values['Date'] = get_timestamp_for_influxdb()
    
    # Read first part
    x = 0
    while x < TRY_AMOUNT:
        try:
            read1 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 42496, 7)
            log.debug('Module: %s - Read 1 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 1 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)
        finally:
            masterTCP.close()
    
    if not "read1" in locals():
        log.error('Modbus Scan Failed (Read1) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #Read second part
    x = 0
    while x < TRY_AMOUNT:
        try:
            read2 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 42545, 33)
            log.debug('Module: %s - Read 2 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 2 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)
        finally:
            masterTCP.close()

    if not "read2" in locals():
        log.error('Modbus Scan Failed (Read2) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #Read third part
    x = 0
    while x < TRY_AMOUNT:
        try:
            read3 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 42599, 13)
            log.debug('Module: %s - Read 3 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 3 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)
        finally:
            masterTCP.close()

    if not "read3" in locals():
        log.error('Modbus Scan Failed (Read3) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    masterTCP.close()

    #Parse the data for read 1
    values['Active_Power']              = float(signed(read1[2]))
    values['Reactive_Power']            = float(signed(read1[3]))
    values['Grid_Voltage']              = float(read1[4]) / 10
    values['Grid_Frequency']            = float(read1[5]) / 100
    values['PowerFactor']               = float(signed(read1[6])) / 1000
 
    #Parse the data for read 2
    values['Code_ActiveFault']          = float(read2[0])  / 1
    values['L1_Voltage']                = float(read2[1])  / 10
    values['L2_Voltage']                = float(read2[2])  / 10
    values['L3_Voltage']                = float(read2[3])  / 10
    values['Grid_Current']              = float(read2[4])  / 10
    values['DC_Input_Voltage']          = float(read2[5])  / 10
    values['DC_Bus_Voltage']            = float(read2[6])  / 10
    values['DC_Input_Current']          = float(read2[7])  / 10
    values['Grounding_Current']         = float(read2[8])  / 1
    values['Isolation_Resistance']      = float(read2[9])  / 1
    values['Inverter_Ambient_Temp']     = float(signed(read2[10])) / 10
    values['Highest_IGBT_Temp_M1']      = float(signed(read2[11])) / 10
    values['Highest_IGBT_Temp_M2']      = float(signed(read2[12])) / 10
    values['Highest_IGBT_Temp_M3']      = float(signed(read2[13])) / 10
    values['Highest_IGBT_Temp_M4']      = float(signed(read2[14])) / 10
    values['Control_Section_Temp']      = float(signed(read2[15])) / 10
    values['Highest_Cabinet_Temp_M1']   = float(signed(read2[16])) / 10
    values['Highest_Cabinet_Temp_M2']   = float(signed(read2[17])) / 10
    values['Highest_Cabinet_Temp_M3']   = float(signed(read2[18])) / 10
    values['Highest_Cabinet_Temp_M4']   = float(signed(read2[19])) / 10
    values['Highest_LCL_Temp_M1']       = float(signed(read2[20])) / 10
    values['Highest_LCL_Temp_M2']       = float(signed(read2[21])) / 10
    values['Highest_LCL_Temp_M3']       = float(signed(read2[22])) / 10
    values['Highest_LCL_Temp_M4']       = float(signed(read2[23])) / 10
    values['Inverter_Section_Humidity'] = float(signed(read2[24])) / 10
    values['Daily_kWh']                 = convert_registers_to_long(25, 26, False, 3, read2)  
    values['Total_kWh']                 = convert_registers_to_long(27, 28, False, 1, read2) * 10
    values['Daily_kVAh']                = convert_registers_to_long(29, 30, False, 3, read2)
    values['Total_kVAh']                = convert_registers_to_long(31, 32, False, 1, read2) * 10
    
    #Extract Status Words
    electromechanical_word              = int(read3[0])
    main_status_word                    = int(read1[1])
    limiting_status_word                = int(read3[3])
    mppt_status_word                    = int(read3[5])
    grid_status_word                    = int(read3[6])
    fan_status_word_1                   = int(read3[7])
    fan_status_word_2                   = int(read3[8])
    environmental_status_word           = int(read3[9])
    fault_status_word_1                 = int(read3[10])
    fault_status_word_2                 = int(read3[11])
    alarm_status_word                   = int(read3[12])

    #Extract bits from words ELECTROMECHANICAL
    values['Status_Electromechanical_ACContactorM1']        = float(electromechanical_word >> 0 & 1)
    values['Status_Electromechanical_ACContactorM2']        = float(electromechanical_word >> 1 & 1)
    values['Status_Electromechanical_ACContactorM3']        = float(electromechanical_word >> 2 & 1)
    values['Status_Electromechanical_ACContactorM4']        = float(electromechanical_word >> 3 & 1)
    values['Status_Electromechanical_DCContactorM1']        = float(electromechanical_word >> 4 & 1)
    values['Status_Electromechanical_DCContactorM2']        = float(electromechanical_word >> 5 & 1)
    values['Status_Electromechanical_DCContactorM3']        = float(electromechanical_word >> 6 & 1)
    values['Status_Electromechanical_DCContactorM4']        = float(electromechanical_word >> 7 & 1)
    values['Status_Electromechanical_ACSwitchM1']           = float(electromechanical_word >> 8 & 1)
    values['Status_Electromechanical_ACSwitchM2']           = float(electromechanical_word >> 9 & 1)
    values['Status_Electromechanical_ACSwitchM3']           = float(electromechanical_word >> 10 & 1)
    values['Status_Electromechanical_ACSwitchM4']           = float(electromechanical_word >> 11 & 1)
    values['Status_Electromechanical_DCSwitchM1']           = float(electromechanical_word >> 12 & 1)
    values['Status_Electromechanical_DCSwitchM2']           = float(electromechanical_word >> 13 & 1)
    values['Status_Electromechanical_DCSwitchM3']           = float(electromechanical_word >> 14 & 1)
    values['Status_Electromechanical_DCSwitchM4']           = float(electromechanical_word >> 15 & 1)

    #Extract bits from words MAIN
    values['Status_Main_ReadyToSwitchOn']                   = float(main_status_word >> 0 & 1)
    values['Status_Main_Faulted']                           = float(main_status_word >> 1 & 1)
    values['Status_Main_Warning']                           = float(main_status_word >> 2 & 1)
    values['Status_Main_MPPTEnabled']                       = float(main_status_word >> 3 & 1)
    values['Status_Main_GridStable']                        = float(main_status_word >> 4 & 1)
    values['Status_Main_DCVoltageWithinLimits']             = float(main_status_word >> 5 & 1)
    values['Status_Main_StartInhibited']                    = float(main_status_word >> 6 & 1)
    values['Status_Main_ReducedRun']                        = float(main_status_word >> 7 & 1)
    values['Status_Main_RedundantRun']                      = float(main_status_word >> 8 & 1)
    values['Status_Main_QCompansation']                     = float(main_status_word >> 9 & 1)
    values['Status_Main_Limited']                           = float(main_status_word >> 10 & 1)

    #Extract bits from words LIMITING
    values['Status_Limiting_IGBTTempCurrentLimitation']      = float(limiting_status_word >> 0 & 1)
    values['Status_Limiting_PfLimitation']                   = float(limiting_status_word >> 1 & 1)
    values['Status_Limiting_PuLimitation']                   = float(limiting_status_word >> 2 & 1)
    values['Status_Limiting_GridFaultLimitation']            = float(limiting_status_word >> 3 & 1)
    values['Status_Limiting_ExternalPowerLimit']             = float(limiting_status_word >> 4 & 1)
    values['Status_Limiting_FRTRecoveryLimit']               = float(limiting_status_word >> 5 & 1)
    values['Status_Limiting_ShutdownRampLimit']              = float(limiting_status_word >> 6 & 1)
    values['Status_Limiting_PowerGradientLimit']             = float(limiting_status_word >> 7 & 1)
    values['Status_Limiting_FRTInteraction']                 = float(limiting_status_word >> 8 & 1)
    values['Status_Limiting_AmbientTempLimitation']          = float(limiting_status_word >> 9 & 1)
    values['Status_Limiting_ControlSectionTempLimitation']   = float(limiting_status_word >> 10 & 1)
    values['Status_Limiting_ACDCSectionTempLimitation']      = float(limiting_status_word >> 11 & 1)
    values['Status_Limiting_LCLSectionTempLimitation']       = float(limiting_status_word >> 12 & 1)
    values['Status_Limiting_InputDCDCSectionTempLimitation'] = float(limiting_status_word >> 14 & 1)

    #Extract bits from words MPPT
    values['Status_MPPT_MPPTMode']                           = float(mppt_status_word >> 0 & 1)
    values['Status_MPPT_PowerLimitationActive']              = float(mppt_status_word >> 1 & 1)
    values['Status_MPPT_MinVoltageLimitActive']              = float(mppt_status_word >> 2 & 1)
    values['Status_MPPT_MaxVoltageLimitActive']              = float(mppt_status_word >> 3 & 1)

    #Extract bits from words GRID
    values['Status_Grid_Undervoltage']                       = float(grid_status_word >> 0 & 1)
    values['Status_Grid_Overvoltage']                        = float(grid_status_word >> 1 & 1)
    values['Status_Grid_Underfrequency']                     = float(grid_status_word >> 2 & 1)
    values['Status_Grid_Overfrequency']                      = float(grid_status_word >> 3 & 1)
    values['Status_Grid_AntiIslandingTrip']                  = float(grid_status_word >> 4 & 1)
    values['Status_Grid_RoCoFTrip']                          = float(grid_status_word >> 5 & 1)
    values['Status_Grid_CombinatoryTrip']                    = float(grid_status_word >> 6 & 1)
    values['Status_Grid_MovingAverageTrip']                  = float(grid_status_word >> 7 & 1)
    values['Status_Grid_ZeroCrossingTrip']                   = float(grid_status_word >> 8 & 1)
    values['Status_Grid_LVRTTrip']                           = float(grid_status_word >> 9 & 1)
    values['Status_Grid_HVRTTrip']                           = float(grid_status_word >> 10 & 1)
    values['Status_Grid_ExternalMonitorTrip']                = float(grid_status_word >> 11 & 1)

    #Extract bits from words FANS
    values['Status_Fan_MainChannel1Fan1']                    = float(fan_status_word_1 >> 0 & 1)
    values['Status_Fan_MainChannel1Fan2']                    = float(fan_status_word_1 >> 1 & 1)
    values['Status_Fan_MainChannel1Fan3']                    = float(fan_status_word_1 >> 2 & 1)
    values['Status_Fan_MainChannel1Fan4']                    = float(fan_status_word_1 >> 3 & 1)
    values['Status_Fan_MainChannel2Fan1']                    = float(fan_status_word_1 >> 4 & 1)
    values['Status_Fan_MainChannel2Fan2']                    = float(fan_status_word_1 >> 5 & 1)
    values['Status_Fan_MainChannel2Fan3']                    = float(fan_status_word_1 >> 6 & 1)
    values['Status_Fan_MainChannel2Fan4']                    = float(fan_status_word_1 >> 7 & 1)
    values['Status_Fan_MainChannel3Fan1']                    = float(fan_status_word_1 >> 8 & 1)
    values['Status_Fan_MainChannel3Fan2']                    = float(fan_status_word_1 >> 9 & 1)
    values['Status_Fan_MainChannel3Fan3']                    = float(fan_status_word_1 >> 10 & 1)
    values['Status_Fan_MainChannel3Fan4']                    = float(fan_status_word_1 >> 11 & 1)
    values['Status_Fan_MainChannel4Fan1']                    = float(fan_status_word_1 >> 12 & 1)
    values['Status_Fan_MainChannel4Fan2']                    = float(fan_status_word_1 >> 13 & 1)
    values['Status_Fan_MainChannel4Fan3']                    = float(fan_status_word_1 >> 14 & 1)
    values['Status_Fan_MainChannel4Fan4']                    = float(fan_status_word_1 >> 15 & 1)

    values['Status_Fan_LCLM1Fan1']                           = float(fan_status_word_2 >> 0 & 1)
    values['Status_Fan_LCLM1Fan2']                           = float(fan_status_word_2 >> 1 & 1)
    values['Status_Fan_LCLM2Fan1']                           = float(fan_status_word_2 >> 2 & 1)
    values['Status_Fan_LCLM2Fan2']                           = float(fan_status_word_2 >> 3 & 1)
    values['Status_Fan_LCLM3Fan1']                           = float(fan_status_word_2 >> 4 & 1)
    values['Status_Fan_LCLM3Fan2']                           = float(fan_status_word_2 >> 5 & 1)
    values['Status_Fan_LCLM4Fan1']                           = float(fan_status_word_2 >> 6 & 1)
    values['Status_Fan_LCLM4Fan2']                           = float(fan_status_word_2 >> 7 & 1)
    values['Status_Fan_ACDCIndoorFanM1']                     = float(fan_status_word_2 >> 8 & 1)
    values['Status_Fan_ACDCIndoorFanM2']                     = float(fan_status_word_2 >> 9 & 1)
    values['Status_Fan_ACDCIndoorFanM3']                     = float(fan_status_word_2 >> 10 & 1)
    values['Status_Fan_ACDCIndoorFanM4']                     = float(fan_status_word_2 >> 11 & 1)

    #Extract bits from words ENVIRONMENT
    values['Status_Environment_OverTempDetected']            = float(environmental_status_word >> 1 & 1)
    values['Status_Environment_ColdAmbientTempDetected']     = float(environmental_status_word >> 2 & 1)
    values['Status_Environment_ExcessHumidityDetected']      = float(environmental_status_word >> 3 & 1)
    values['Status_Environment_CabinetHeatingOn']            = float(environmental_status_word >> 4 & 1)
    values['Status_Environment_HotAmbientTempDetected']      = float(environmental_status_word >> 5 & 1)
    values['Status_Environment_ColdPowerSectionTemp']        = float(environmental_status_word >> 6 & 1)

    #Extract bits from words FAULT STATUS
    values['Status_Fault_FastPoweroff']                      = float(fault_status_word_1 >> 0 & 1)
    values['Status_Fault_AmbientSituation']                  = float(fault_status_word_1 >> 1 & 1)
    values['Status_Fault_GroundingCurrent']                  = float(fault_status_word_1 >> 2 & 1)
    values['Status_Fault_InsulationResistance']              = float(fault_status_word_1 >> 3 & 1)
    values['Status_Fault_GroundingCircuitVoltage']           = float(fault_status_word_1 >> 4 & 1)
    values['Status_Fault_ReverseCurrentFault']               = float(fault_status_word_1 >> 5 & 1)
    values['Status_Fault_DCOvercurrentFault']                = float(fault_status_word_1 >> 6 & 1)
    values['Status_Fault_PLCLinkFault']                      = float(fault_status_word_1 >> 7 & 1)
    values['Status_Fault_FanFault']                          = float(fault_status_word_1 >> 8 & 1)
    values['Status_Fault_ACContactor']                       = float(fault_status_word_1 >> 9 & 1)
    values['Status_Fault_DCContactor']                       = float(fault_status_word_1 >> 10 & 1)
    values['Status_Fault_DCSwitch']                          = float(fault_status_word_1 >> 11 & 1)
    values['Status_Fault_MainCircuitSPDFault']               = float(fault_status_word_1 >> 12 & 1)
    values['Status_Fault_DCFuse']                            = float(fault_status_word_1 >> 13 & 1)
    values['Status_Fault_48VPowerSupply']                    = float(fault_status_word_1 >> 14 & 1)
    values['Status_Fault_InternalSWFault1']                  = float(fault_status_word_1 >> 15 & 1)

    values['Status_Fault_48VBuffer']                         = float(fault_status_word_2 >> 0 & 1)
    values['Status_Fault_24VBuffer']                         = float(fault_status_word_2 >> 1 & 1)
    values['Status_Fault_AuxCircuit']                        = float(fault_status_word_2 >> 2 & 1)
    values['Status_Fault_LCLPressureSensor']                 = float(fault_status_word_2 >> 3 & 1)
    values['Status_Fault_Door']                              = float(fault_status_word_2 >> 4 & 1)
    values['Status_Fault_ACBreaker']                         = float(fault_status_word_2 >> 5 & 1)
    values['Status_Fault_ACOvercurrent']                     = float(fault_status_word_2 >> 6 & 1)
    values['Status_Fault_ShortCircuit']                      = float(fault_status_word_2 >> 7 & 1)
    values['Status_Fault_BUCurrentDifference']               = float(fault_status_word_2 >> 8 & 1)
    values['Status_Fault_InputPhaseLoss']                    = float(fault_status_word_2 >> 9 & 1)
    values['Status_Fault_ControlSectionOverTemp']            = float(fault_status_word_2 >> 10 & 1)
    values['Status_Fault_IGBTOverTemp']                      = float(fault_status_word_2 >> 11 & 1)
    values['Status_Fault_ACDCCabinetOverTemp']               = float(fault_status_word_2 >> 12 & 1)
    values['Status_Fault_LCLSectionOverTemp']                = float(fault_status_word_2 >> 13 & 1)
    values['Status_Fault_PowerUnitLost']                     = float(fault_status_word_2 >> 14 & 1)
    values['Status_Fault_InternalSWFault2']                  = float(fault_status_word_2 >> 15 & 1)

    #Extract bits from words ALARM STATUS
    values['Status_Alarm_GroundingCurrentSuddenChange']      = float(alarm_status_word >> 0 & 1)
    values['Status_Alarm_ResidualCurrent']                   = float(alarm_status_word >> 1 & 1)
    values['Status_Alarm_GroundingCurrentOvervoltage']       = float(alarm_status_word >> 2 & 1)
    values['Status_Alarm_InsulationResistance']              = float(alarm_status_word >> 3 & 1)
    values['Status_Alarm_TempSensorAlarm']                   = float(alarm_status_word >> 4 & 1)
    values['Status_Alarm_SCADADataInputOutOfRange']          = float(alarm_status_word >> 5 & 1)
    values['Status_Alarm_DCLinkOvervoltage']                 = float(alarm_status_word >> 6 & 1)
    values['Status_Alarm_DCInputOvervoltage']                = float(alarm_status_word >> 7 & 1)
    values['Status_Alarm_MainCircuit']                       = float(alarm_status_word >> 8 & 1)
    values['Status_Alarm_SPD']                               = float(alarm_status_word >> 9 & 1)
    values['Status_Alarm_48VPowerSupply']                    = float(alarm_status_word >> 10 & 1)
    values['Status_Alarm_48VBuffer']                         = float(alarm_status_word >> 11 & 1)
    values['Status_Alarm_24VBuffer']                         = float(alarm_status_word >> 12 & 1)
    values['Status_Alarm_AuxCircuitBreaker']                 = float(alarm_status_word >> 13 & 1)
    values['Status_Alarm_LCLPressureSensor']                 = float(alarm_status_word >> 14 & 1)
    values['Status_Alarm_ACDCDoor']                          = float(alarm_status_word >> 15 & 1)

    log.debug('Modbus Scan Completed in : %.4f (DRIVER: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, ip_address, port)    
    return values

def convert_registers_to_long(start_bit, stop_bit, signed, decimals=0, data=[]):
        decimal = {0: 1,1: 10, 2: 100, 3: 1000}
        mypack = pack('>HH',data[start_bit],data[stop_bit])
        if signed:
            format = '>l'
        else:
            format = '>L'
        long_data = unpack(format, mypack)
        final_data = float(long_data[0]) / decimal[decimals]
        return final_data
    
def get_timestamp_for_influxdb():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:00Z")

def signed(value):
    try:
        packval = struct.pack('<H',value)
        return struct.unpack('<h',packval)[0]
    except Exception as e:
        log.error("Error in signed-unsigned conversion. "+str(e))
    
    return 0

def get_version():
    return DRIVER_NAME+" v"+DRIVER_VERSION