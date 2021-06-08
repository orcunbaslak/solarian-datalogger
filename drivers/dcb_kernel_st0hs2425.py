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


DRIVER_NAME = 'KERNEL_DCB_ST0HS2425'
DRIVER_VERSION = '0.1'
MODBUS_TIMEOUT = 3
TRY_AMOUNT = 3

module_name = os.path.splitext(os.path.basename(__file__))[0]

def get_data(ip_address, port, slave_id, device_name, measurement_suffix):
    """Instrument function for Kernel DCB Current Measurement.

    Args:
        * ip_address (str)     : ip address of the TCP device
        * port (int)           : port
        * slave_id (int)       : modbus slave id of the device
        * device_name (string) : name of device to include in json
    
    Modbus Addresses of the device are as follows (PLC Base Address):

    == READ 1 ==
    30052	I_DC_1                      0       	 uint16     1       mA
    30053	I_DC_2                      1       	 uint16     1       mA
    30054	I_DC_3                      2       	 uint16     1       mA
    30055	I_DC_4                      3       	 uint16     1       mA
    30056	I_DC_5                      4       	 uint16     1       mA
    30057	I_DC_6                      5       	 uint16     1       mA
    30058	I_DC_7                      6       	 uint16     1       mA
    30059	I_DC_8                      7       	 uint16     1       mA
    30060	I_DC_9                      8       	 uint16     1       mA
    30061	I_DC_10                     9       	 uint16     1       mA
    30062	I_DC_11                     10       	 uint16     1       mA
    30063	I_DC_12                     11       	 uint16     1       mA
    30064	I_DC_13                     12       	 uint16     1       mA
    30065	I_DC_14                     13       	 uint16     1       mA
    30066	I_DC_15                     14       	 uint16     1       mA
    30067	I_DC_16                     15       	 uint16     1       mA
    30068	I_DC_17                     16       	 uint16     1       mA
    30069	I_DC_18                     17       	 uint16     1       mA
    30070	I_DC_19                     18       	 uint16     1       mA
    30071	I_DC_20                     19       	 uint16     1       mA
    30072	I_DC_21                     20       	 uint16     1       mA
    30073	I_DC_22                     21       	 uint16     1       mA
    30074	I_DC_23                     22       	 uint16     1       mA
    30075	I_DC_24                     23       	 uint16     1       mA
    30084	DCB_Voltage                 32           uint16     1       V
    30089	Cabinet Temp                37           uint16 	1	    °C
    30090	Board Temperature           38           uint16 	1	    °C
    30091	Total_Current               39       	 uint16     0.1     A
    30092	Power_LSB (LE-ByteSwap)     40       	 uint16     1       W
    30093	Power_MSB (LE-ByteSwap)     41       	 uint16     1       W

    """

    #Start timer to test for execution time
    start_time = time.time()

    #Prepare the modbus stack
    masterTCP = modbus_tcp.TcpMaster(host=ip_address,port=port)				
    masterTCP.set_timeout(MODBUS_TIMEOUT)
    masterTCP.set_verbose(True)

    #Set logging
    log.debug('Module: %s - Driver: %s - Reading device %s:%s - Slave: %s', DRIVER_NAME, device_name, ip_address, port, slave_id)

    #Create an ordered list to store the values
    values = OrderedDict()

    #Append devicename and timestamp for InfluxDB
    values['Device_Name'] = device_name
    values['Measurement_Suffix'] = measurement_suffix
    values['Date'] = get_timestamp_for_influxdb()
    
    # Read the data
    x = 0
    while x < TRY_AMOUNT:
        try:
            read1 = masterTCP.execute(slave_id, cst.READ_INPUT_REGISTERS, 51, 47)
            log.debug('Module: %s - Read 1 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 1 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)
    
    if not "read1" in locals():
        log.error('Modbus Scan Failed (Read1) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #Parse the data
    values['I_DC_1']                    = float(read1[0]) / 1000
    values['I_DC_2']                    = float(read1[1]) / 1000
    values['I_DC_3']                    = float(read1[2]) / 1000
    values['I_DC_4']                    = float(read1[3]) / 1000
    values['I_DC_5']                    = float(read1[4]) / 1000
    values['I_DC_6']                    = float(read1[5]) / 1000
    values['I_DC_7']                    = float(read1[6]) / 1000
    values['I_DC_8']                    = float(read1[7]) / 1000
    values['I_DC_9']                    = float(read1[8]) / 1000
    values['I_DC_10']                   = float(read1[9]) / 1000
    values['I_DC_11']                   = float(read1[10]) / 1000
    values['I_DC_12']                   = float(read1[11]) / 1000
    values['I_DC_13']                   = float(read1[12]) / 1000
    values['I_DC_14']                   = float(read1[13]) / 1000
    values['I_DC_15']                   = float(read1[14]) / 1000
    values['I_DC_16']                   = float(read1[15]) / 1000
    values['I_DC_17']                   = float(read1[16]) / 1000
    values['I_DC_18']                   = float(read1[17]) / 1000
    values['I_DC_19']                   = float(read1[18]) / 1000
    values['I_DC_20']                   = float(read1[19]) / 1000
    values['I_DC_21']                   = float(read1[20]) / 1000
    values['I_DC_22']                   = float(read1[21]) / 1000
    values['I_DC_23']                   = float(read1[22]) / 1000
    values['I_DC_24']                   = float(read1[23]) / 1000

    values['V_DC']                      = float(read1[32])

    values['Cabinet_Temp']              = float(read1[37])
    values['Board_Temp']                = float(read1[38])

    values['Total_Current']             = float(read1[39]) / 10
    values['Power']                     = convert_registers_to_long(41, 40, False, 0, read1)

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