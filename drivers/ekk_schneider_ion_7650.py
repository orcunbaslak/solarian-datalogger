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
    Parameter	    Address	ModbusAddress	ARRAY	Regs	Format	Scaling
    I a	            40150	149	            0	    1	    UINT16	10
    I b	            40151	150	            1	    1	UINT16	10
    I c	            40152	151	            2	    1	UINT16	10
    Freq	        40159	158	            9	    1	UINT16	10
    Vln a	        40166	165	            16	    2	UINT32	1
    Vln b	        40168	167	            18	    2	UINT32	1
    Vln c	        40170	169	            20	    2	UINT32	1
    Vll ab	        40178	177	            28	    2	UINT32	1
    Vll bc	        40180	179	            30	    2	UINT32	1
    Vll ca	        40182	181	            32	    2	UINT32	1
    kW tot	        40204	203	            54	    2	INT32	1
    kVAR tot	    40214	213	            64	    2	INT32	1
    kVA tot	        40224	223	            74	    2	INT32	1
    kWh del	        40230	229	            80	    2	INT32	1
    kWh rec	        40232	231	            82	    2	INT32	1
    kVARh del	    40234	233	            84	    2	INT32	1
    kVARh rec	    40236	235	            86	    2	INT32	1
    PF sign tot	    40265	264	            115	    1	INT16	100
    V1 THD mx	    40266	265	            116	    1	INT16	100
    V2 THD mx	    40267	266	            117	    1	INT16	100
    V3 THD mx	    40268	267	            118	    1	INT16	100
    I1 THD mx	    40269	268	            119	    1	INT16	100
    I2 THD mx	    40270	269	            120	    1	INT16	100
    I3 THD mx	    40271	270	            121	    1	INT16	100
    I1 K Factor	    40272	271	            122	    1	INT16	100
    I2 K Factor	    40273	272	            123	    1	INT16	100
    I3 K Factor	    40274	273	            124	    1	INT16	100
    I1 Crest Factor	40275	274	            125	    1	INT16	100
    I2 Crest Factor	40276	275	            126	    1	INT16	100
    I3 Crest Factor	40277	276	            127	    1	INT16	100

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