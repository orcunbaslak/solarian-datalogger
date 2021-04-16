# -*- coding: UTF-8 -*-

"""
 * 
 *    Solarian Datalogger - A datalogging software for solar systems using various drivers
 * 
 *    Copyright (C) 2020 Orçun Başlak
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


DRIVER_NAME = 'SCHNEIDER_ION_7650_TCP_INAVITAS'
DRIVER_VERSION = '0.1'
MODBUS_TIMEOUT = 3
TRY_AMOUNT = 3

module_name = os.path.splitext(os.path.basename(__file__))[0]

def get_data(ip_address, port, slave_id, device_name, measurement_suffix):
    """Instrument function for SCHNEIDER ION 7650 Power Quality Analyzer Inverter.

    Args:
        * ip_address (str)     : ip address of the TCP device
        * port (int)           : port
        * slave_id (int)       : modbus slave id of the device
        * device_name (string) : name of device to include in json
    
    Modbus Addresses of the device are as follows:

    == READ 1 ==
    Address 	Array Address	    Label 	    Type            R	Format 	Scaling 
    1	        0  	                Vln a 	    Volts 	        1	UINT16 	1
    2	        1	                Vln b 	    Volts 	        1	UINT16 	1
    3	        2	                Vln c 	    Volts 	        1	UINT16 	1

    4	        3	                Vll ab 	    Volts 	        1	UINT16 	1
    5	        4	                Vll bc 	    Volts 	        1	UINT16 	1
    6	        5	                Vll ca 	    Volts 	        1	UINT16 	1

    21	        20	                I1 THD mx 	PF/THD/Kfactor 	1	UINT16 	100
    22	        21	                I2 THD mx 	PF/THD/Kfactor 	1	UINT16 	100
    23	        22	                I3 THD mx 	PF/THD/Kfactor 	1	UINT16 	100
    24	        23	                V1 THD mx 	PF/THD/Kfactor 	1	UINT16 	100
    25	        24	                V2 THD mx 	PF/THD/Kfactor 	1	UINT16 	100
    26	        25	                V3 THD mx 	PF/THD/Kfactor 	1	UINT16 	100


    27	        26	                Freq 	    Amp/freq/unbal 	1	UINT16 	10

    30	        29	                Ia 	        Amp/freq/unbal 	1	UINT16 	10
    31	        30	                Ib 	        Amp/freq/unbal 	1	UINT16 	10
    32	        31	                Ic 	        Amp/freq/unbal 	1	UINT16 	10

    43	        42	                PF lead 	PF/THD/Kfactor 	1	INT16 	100
    44	        43	                PF lag 	    PF/THD/Kfactor 	1	INT16 	100

    50	        49	                kW tot 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    52	        51	                kVAR tot 	kW/kVAr/kVA 	2	INT32 	1/1000 
    54	        53	                kVA tot 	kW/kVAr/kVA 	2	INT32 	1/1000 

    56	        55	                kWh del 	kWh/kVArh 	    2	INT32 	1/1000 
    58	        57	                kWh rec 	kWh/kVArh 	    2	INT32 	1/1000 
    60	        59	                kVARh del 	kWh/kVArh 	    2	INT32 	1/1000 
    62	        61	                kVARh rec 	kWh/kVArh 	    2	INT32 	1/1000 

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
            read1 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 149, 122)
            log.debug('Module: %s - Read 1 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            if(convert_registers_to_long(16, 17, False, 0, read1) == 0):
                log.error('Voltage is zero!!')
                raise Exception('Voltage is zero. Try Again')
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 1 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)
    
    if not "read1" in locals():
        log.error('Modbus Scan Failed (Read1) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False


    #UINT16
    values['Ia']            = float(read1[0])  / 10
    values['Ib']            = float(read1[1])  / 10
    values['Ic']            = float(read1[2])  / 10

    values['Freq']          = float(read1[9])  / 10

    values['Vll_ab']        = convert_registers_to_long(28, 29, False, 0, read1)
    values['Vll_ac']        = convert_registers_to_long(30, 31, False, 0, read1) 
    values['Vll_ca']        = convert_registers_to_long(32, 33, False, 0, read1) 

    values['kW_tot']        = convert_registers_to_long(54, 55, True, 0, read1) 
    values['kVAR_tot']      = convert_registers_to_long(64, 65, True, 0, read1) 
    values['kVA_tot']       = convert_registers_to_long(74, 75, True, 0, read1) 
    values['kWh_del']       = convert_registers_to_long(80, 81, True, 0, read1) 
    values['kWh_rec']       = convert_registers_to_long(82, 83, True, 0, read1) 
    values['kVARh_del']     = convert_registers_to_long(84, 85, True, 0, read1)
    values['kVARh_rec']     = convert_registers_to_long(86, 87, True, 0, read1) 

    values['I1_THD_max']    = float(signed(read1[119])) / 100
    values['I2_THD_max']    = float(signed(read1[120])) / 100
    values['I3_THD_max']    = float(signed(read1[121])) / 100
    values['V1_THD_max']    = float(signed(read1[116])) / 100
    values['V2_THD_max']    = float(signed(read1[117])) / 100
    values['V3_THD_max']    = float(signed(read1[118])) / 100

    values['PF_tot']        = float(signed(read1[115])) / 100




    
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