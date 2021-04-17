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
import serial
from struct import pack, unpack
from datetime import datetime
from collections import OrderedDict

import modbus_tk
import modbus_tk.defines as cst
from modbus_tk import modbus_rtu

import logging
log = logging.getLogger('solarian-datalogger')


DRIVER_NAME = 'SOCOMEC_DIRIS_A10'
DRIVER_VERSION = '0.1'
MODBUS_TIMEOUT = 5
TRY_AMOUNT = 3

module_name = os.path.splitext(os.path.basename(__file__))[0]

def get_data(ip_address, port, slave_id, device_name, measurement_suffix):
    """Instrument function for SOCOMEC DIRISA10 Power Analyzer.

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

    """

    #Start timer to test for execution time
    start_time = time.time()

    #Prepare the modbus stack
    master = modbus_rtu.RtuMaster(
        serial.Serial(port='/dev/ttyUSB0', baudrate=19200, bytesize=8, parity='N', stopbits=1, xonxoff=0)
    )				
    master.set_timeout(MODBUS_TIMEOUT)
    master.set_verbose(True)

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
            read1 = master.execute(slave_id, cst.READ_HOLDING_REGISTERS, 50514, 30)
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
            read2 = master.execute(slave_id, cst.READ_HOLDING_REGISTERS, 50780, 10)
            log.debug('Module: %s - Read 2 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 2 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            print(e)
            x += 1
            time.sleep(0.5)

    if not "read2" in locals():
        log.error('Modbus Scan Failed (Read2) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #Read third part
    x = 0
    while x < TRY_AMOUNT:
        try:
            read3 = master.execute(slave_id, cst.READ_HOLDING_REGISTERS, 51536, 9)
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
    values['U12']   = convert_registers_to_long(0, 1, signed=False, decimals=2, data=read1)
    values['U23']   = convert_registers_to_long(2, 3, signed=False, decimals=2, data=read1)
    values['U31']   = convert_registers_to_long(4, 5, signed=False, decimals=2, data=read1)
    values['V1']    = convert_registers_to_long(6, 7, signed=False, decimals=2, data=read1)
    values['V2']    = convert_registers_to_long(8, 9, signed=False, decimals=2, data=read1)
    values['V3']    = convert_registers_to_long(10, 11, signed=False, decimals=2, data=read1)
    values['F']     = convert_registers_to_long(12, 13, signed=False, decimals=2, data=read1)
    values['I1']    = convert_registers_to_long(14, 15, signed=False, decimals=3, data=read1)
    values['I2']    = convert_registers_to_long(16, 17, signed=False, decimals=3, data=read1)
    values['I3']    = convert_registers_to_long(18, 19, signed=False, decimals=3, data=read1)
    values['In']    = convert_registers_to_long(20, 21, signed=False, decimals=3, data=read1)
    values['P']     = convert_registers_to_long(22, 23, signed=True, decimals=0, data=read1) * 10
    values['Q']     = convert_registers_to_long(24, 25, signed=True, decimals=0, data=read1) * 10
    values['S']     = convert_registers_to_long(26, 27, signed=False, decimals=0, data=read1) * 10
    values['Pf']    = convert_registers_to_long(28, 29, signed=True, decimals=3, data=read1)
 
    #Parse the data for read 2
    values['Active_Energy_Positive']    = convert_registers_to_long(0, 1, signed=False, decimals=0, data=read2)
    values['Reactive_Energy_Positive']  = convert_registers_to_long(2, 3, signed=False, decimals=0, data=read2)
    values['Apparent_Energy']           = convert_registers_to_long(4, 5, signed=True, decimals=0, data=read2)
    values['Active_Energy_Negative']    = convert_registers_to_long(6, 7, signed=True, decimals=0, data=read2)
    values['Reactive_Energy_Negative']  = convert_registers_to_long(8, 9, signed=True, decimals=0, data=read2)
    
    #Parse the data for read 3
    values['THD_U12']   = float(read3[0]) / 10
    values['THD_U23']   = float(read3[1]) / 10
    values['THD_U31']   = float(read3[2]) / 10
    values['THD_V1']    = float(read3[3]) / 10
    values['THD_V2']    = float(read3[4]) / 10
    values['THD_V3']    = float(read3[5]) / 10
    values['THD_I1']    = float(read3[6]) / 10
    values['THD_I2']    = float(read3[7]) / 10
    values['THD_I3']    = float(read3[8]) / 10

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