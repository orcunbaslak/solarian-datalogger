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


DRIVER_NAME = 'ABB_PVS800_TCP'
DRIVER_VERSION = '0.2'
MODBUS_TIMEOUT = 3
TRY_AMOUNT = 3

module_name = os.path.splitext(os.path.basename(__file__))[0]

def get_data(ip_address, port, slave_id, device_name, measurement_suffix):
    """Instrument function for ABB PVS800 Inverter.

    Args:
        * ip_address (str)     : ip address of the TCP device
        * port (int)           : port
        * slave_id (int)       : modbus slave id of the device
        * device_name (string) : name of device to include in json
    
    Modbus Addresses of the device are as follows:

    == READ 1 ==
    42496	Heartbeat                   0       	
    42497	Inverter main status word   1            bf16 		
    42498	Active power                2            int16      1       kW
    42499	Reactive power              3            int16      1       kVAR
    42500	Grid voltage                4            uint16     0.1     V
    42501	Grid frequency              5            uint16     0.01    Hz
    42502	Power factor                6            int16      0.001
    
    == READ 2 ==
    42545	Code of the active fault    0               uint16 	1	
    42546	Main voltage, U-V           1               uint16 	0.1	    V
    42547	Main voltage, V-W           2               uint16 	0.1	    V
    42548	Main voltage W-U            3               uint16 	0.1	    V
    42549	Grid current                4               uint16 	0.1	    V
    42550	DC input voltage            5               uint16 	0.1	    V
    42551	DC bus voltage              6               uint16 	0.1	    V
    42552	DC input current            7               uint16 	0.1	    A
    42553	Grounding current3          8               uint16 	1	    mA
    42554	Isolation resistance3       9               uint16 	1	    kOhm
    42555	Ambient temperature         10              int16 	0.1	    °C
    42556	Highest IGBT temperature, PU1    11         int16 	0.1	    °C
    42557	Highest IGBT temperature, PU21   12         int16 	0.1	    °C
    42558	Highest IGBT temperature, PU31   13         int16 	0.1	    °C
    42559	Highest IGBT temperature, PU41   14         int16 	0.1	    °C
    42560	Control section temperature      15         int16 	0.1	    °C
    42561   UNUSED 16
    42562   UNUSED 17
    42563   UNUSED 18
    42564	Daily kWh supplied2, HIGH ORDER BIT 19	    uint16 	0.1	kWh
    42565	Daily kWh supplied2, LOW ORDER BIT  20      uint16 	0.1	kWh -USE THIS-
    42566	Total kWh supplied2, HIGH ORDER BIT 21      uint16 	1	kWh
    42567	Total kWh supplied2, LOW ORDER BIT  22      uint16 	1	kWh -USE THIS-
    42568	Daily kVAh supplied2, HIGH ORDER BIT 23     uint16 	0.1	kVAh
    42569	Daily kVAh supplied2, LOW ORDER BIT 24      uint16 	0.1	kVAh -USE THIS-
    42570	Total kVAh supplied2, HIGH ORDER BIT 25     uint16 	1	kVAh
    42571	Total kVAh supplied2, LOW ORDER BIT 26     uint16	1	kVAh -USE THIS-

    == READ 3 ==                
    42599	Inverter main Status Word   0               bf16		
    42600	Limitation status word      1               bf16
    42601   UNUSED                      2
    42602	MPPT Status Word            3               bf16		
    42603	Grid Status Word            4               bf16		
    42604	Fan Status Word             5               bf16
    42605   UNUSED                      6               
    42606	Environmental Status Word   7               bf16		

    ========= INVERTER MAIN STATUS WORD (42497) =========
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
    11      Grid Connected

    ========= LIMITATION STATUS WORD (42600) =========
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
    10      RESERVED
    11      Power section temperature limitation

    ========= MPPT STATUS WORD (42602) =========
    0       MPPT Mode (0:LowPower - 1:NormalOperation)
    1       Power Limitation Active
    2       Minimum voltage limit active
    3       Maximum voltage limit active

    ========= GRID STATUS WORD (42603) =========
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

    ========= FAN STATUS WORD (42604) =========
    0       Power Unit 1
    1       Power Unit 2
    2       Power Unit 3
    3       Power Unit 4
    4       ISU1 Fan
    5       ISU2 Fan
    6       Door fan circuit breaker

    ========= ENVIRONMENTAL STATUS WORD (42606) =========
    0       AC busbar thermal protection active
    1       DC busbar thermal protection active
    2       Cold ambient temp warning
    3       Cold ambient temp fault
    4       Hot ambient temp warning
    5       Hot ambient temp fault
    6       IGBT temp warning
    7       IGBT temp fault

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
    
    if not "read1" in locals():
        log.error('Modbus Scan Failed (Read1) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #Read second part
    x = 0
    while x < TRY_AMOUNT:
        try:
            read2 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 42545, 27)
            log.debug('Module: %s - Read 2 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 2 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)

    if not "read2" in locals():
        log.error('Modbus Scan Failed (Read2) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #Read third part
    x = 0
    while x < TRY_AMOUNT:
        try:
            read3 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 42599, 8)
            log.debug('Module: %s - Read 3 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 3 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)

    if not "read3" in locals():
        log.error('Modbus Scan Failed (Read3) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False


    #Parse the data for read 1
    values['Active_Power']              = float(signed(read1[2]))
    values['Reactive_Power']            = float(signed(read1[3]))
    values['Grid_Voltage']              = float(read1[4]) / 10
    values['Grid_Frequency']            = float(read1[5]) / 100
    values['PowerFactor']               = float(signed(read1[6])) / 1000
 
    #Parse the data for read 2
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
    values['Highest_IGBT_Temp_PU1']     = float(signed(read2[11])) / 10
    values['Highest_IGBT_Temp_PU21']    = float(signed(read2[12])) / 10
    values['Highest_IGBT_Temp_PU31']    = float(signed(read2[13])) / 10
    values['Highest_IGBT_Temp_PU41']    = float(signed(read2[14])) / 10
    values['Control_Section_Temp']      = float(signed(read2[15])) / 10
    values['Daily_kWh']                 = convert_registers_to_long(19, 20, False, 3, read2) / 1
    values['Total_kWh']                 = convert_registers_to_long(21, 22, False, 1, read2) * 10
    values['Daily_kVAh']                = convert_registers_to_long(23, 24, False, 3, read2) / 1
    values['Total_kVAh']                = convert_registers_to_long(25, 26, False, 1, read2) * 10
    
    #Extract Status-Limiting-Grid-Env-Fan Words
    main_status_word                    = int(read1[1])
    limiting_status_word                = int(read3[1])
    mppt_status_word                    = int(read3[3])
    grid_status_word                    = int(read3[4])
    fan_status_word                     = int(read3[5])
    environmental_status_word           = int(read3[7])

    #Extract bits from words MAIN
    values['Status_Main_ReadyToSwitchOn']        = float(main_status_word >> 0 & 1)
    values['Status_Main_Faulted']                = float(main_status_word >> 1 & 1)
    values['Status_Main_Warning']                = float(main_status_word >> 2 & 1)
    values['Status_Main_MPPTEnabled']            = float(main_status_word >> 3 & 1)
    values['Status_Main_GridStable']             = float(main_status_word >> 4 & 1)
    values['Status_Main_DCVoltageWithinLimits']  = float(main_status_word >> 5 & 1)
    values['Status_Main_StartInhibited']         = float(main_status_word >> 6 & 1)
    values['Status_Main_ReducedRun']             = float(main_status_word >> 7 & 1)
    values['Status_Main_RedundantRun']           = float(main_status_word >> 8 & 1)
    values['Status_Main_QCompansation']          = float(main_status_word >> 9 & 1)
    values['Status_Main_Limited']                = float(main_status_word >> 10 & 1)
    values['Status_Main_GridConnected']          = float(main_status_word >> 11 & 1)

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
    values['Status_Limiting_PowerSectionTempLimitation']     = float(limiting_status_word >> 11 & 1)

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

    #Extract bits from words FAN
    values['Status_Fan_PowerUnit1']                          = float(fan_status_word >> 0 & 1)
    values['Status_Fan_PowerUnit2']                          = float(fan_status_word >> 1 & 1)
    values['Status_Fan_PowerUnit3']                          = float(fan_status_word >> 2 & 1)
    values['Status_Fan_PowerUnit4']                          = float(fan_status_word >> 3 & 1)
    values['Status_Fan_ISU1Fan']                             = float(fan_status_word >> 4 & 1)
    values['Status_Fan_ISU2Fan']                             = float(fan_status_word >> 5 & 1)
    values['Status_Fan_DoorFanCircuitBreaker']               = float(fan_status_word >> 6 & 1)

    #Extract bits from words ENVIRONMENT
    values['Status_Environment_ACBusbarThermalProtection']   = float(environmental_status_word >> 0 & 1)
    values['Status_Environment_DCBusbarThermalProtection']   = float(environmental_status_word >> 1 & 1)
    values['Status_Environment_ColdAmbientTempWarning']      = float(environmental_status_word >> 2 & 1)
    values['Status_Environment_ColdAmbientTempFault']        = float(environmental_status_word >> 3 & 1)
    values['Status_Environment_HotAmbientTempWarning']       = float(environmental_status_word >> 4 & 1)
    values['Status_Environment_HotAmbientTempFault']         = float(environmental_status_word >> 5 & 1)
    values['Status_Environment_IGBTTempWarning']             = float(environmental_status_word >> 6 & 1)
    values['Status_Environment_IGBTTempFault']               = float(environmental_status_word >> 7 & 1) 

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