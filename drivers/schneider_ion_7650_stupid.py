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


DRIVER_NAME = 'SCHNEIDER_ION_7650_TCP'
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
    Address 	Array       Address	Label 	R	Format 	Scaling 
    40150	0	Ia 	        Amp/freq/unbal 	1	UINT16 	10
    40151	1	Ib 	        Amp/freq/unbal 	1	UINT16 	10
    40152	2	Ic 	        Amp/freq/unbal 	1	UINT16 	10
    40153	3	I4 	        Amp/freq/unbal 	1	UINT16 	10
    40154	4	I5 	        Amp/freq/unbal 	1	UINT16 	10
    40155	5	I avg 	    Amp/freq/unbal 	1	UINT16 	10
    40156	6	I avg mn 	Amp/freq/unbal 	1	UINT16 	10
    40157	7	I avg mx 	Amp/freq/unbal 	1	UINT16 	10
    40158	8	I avg mean 	Amp/freq/unbal 	1	UINT16 	10
    40159	9	Freq 	    Amp/freq/unbal 	1	UINT16 	10
    40160	10	Freq mn 	Amp/freq/unbal 	1	UINT16 	10
    40161	11	Freq mx 	Amp/freq/unbal 	1	UINT16 	10
    40162	12	Freq mean 	Amp/freq/unbal 	1	UINT16 	10
    40163	13	V unbal 	Amp/freq/unbal 	1	UINT16 	10
    40164	14	I unbal 	Amp/freq/unbal 	1	UINT16 	10
    40165	15	Phase Rev 	Amp/freq/unbal 	1	UINT16 	10

    40166	16	Vln a 	    Volts 	        2	UINT32 	10
    40168	18	Vln b 	    Volts 	        2	UINT32 	10
    40170	20	Vln c 	    Volts 	        2	UINT32 	10
    40172	22	Vln avg 	Volts 	        2	UINT32 	10
    40174	24	Vln avg mx 	Volts 	        2	UINT32 	10
    40178	26	Vll ab 	    Volts 	        2	UINT32 	10
    40180	28	Vll bc 	    Volts 	        2	UINT32 	10
    40182	30	Vll ca 	    Volts 	        2	UINT32 	10
    40184	32	Vll avg 	Volts 	        2	UINT32 	10
    40186	34	Vll avg mx 	Volts 	        2	UINT32 	10
    40188	36	Vll avg mn 	Volts 	        2	UINT32 	10

    40198	38	kW a 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40200	40	kW b 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40202	42	kW c 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40204	44	kW tot 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40206	46	kW tot mx 	kW/kVAr/kVA 	2	INT32 	1/1000 
    40208	48	kVAR a 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40210	50	kVAR b 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40212	52	kVAR c 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40214	54	kVAR tot 	kW/kVAr/kVA 	2	INT32 	1/1000 
    40216	56	kVAR tot mx kW/kVAr/kVA 	2	INT32 	1/1000 
    40218	58	kVA a 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40220	60	kVA b 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40222	62	kVA c 	    kW/kVAr/kVA 	2	INT32 	1/1000 
    40224	64	kVA tot 	kW/kVAr/kVA 	2	INT32 	1/1000 
    40226	66	kVA tot mx 	kW/kVAr/kVA 	2	INT32 	1/1000 
    40230	68	kWh del 	kWh/kVArh 	    2	INT32 	1/1000 
    40232	70	kWh rec 	kWh/kVArh 	    2	INT32 	1/1000 
    40234	72	kVARh del 	kWh/kVArh 	    2	INT32 	1/1000 
    40236	74	kVARh rec 	kWh/kVArh 	    2	INT32 	1/1000 
    40238	76	kVAh d+rec 	kWh/kVArh 	    2	INT32 	1/1000 

    40262	78	PF sign a 	PF/THD/Kfactor 	1	INT16 	100
    40263	79	PF sign b 	PF/THD/Kfactor 	1	INT16 	100
    40264	80	PF sign c 	PF/THD/Kfactor 	1	INT16 	100
    40265	81	PF sign tot PF/THD/Kfactor 	1	INT16 	100
    40266	82	V1 THD mx 	PF/THD/Kfactor 	1	INT16 	100
    40267	83	V2 THD mx 	PF/THD/Kfactor 	1	INT16 	100
    40268	84	V3 THD mx 	PF/THD/Kfactor 	1	INT16 	100
    40269	85	I1 THD mx 	PF/THD/Kfactor 	1	INT16 	100
    40270	86	I2 THD mx 	PF/THD/Kfactor 	1	INT16 	100
    40271	87	I3 THD mx 	PF/THD/Kfactor 	1	INT16 	100
    40272	88	I1 K Fact 	PF/THD/Kfactor 	1	INT16 	100
    40273	89	I2 K Fact 	PF/THD/Kfactor 	1	INT16 	100
    40274	90	I3 K Fact 	PF/THD/Kfactor 	1	INT16 	100
    40275	91	I1 Crest  	PF/THD/Kfactor 	1	INT16 	100
    40276	92	I2 Crest  	PF/THD/Kfactor 	1	INT16 	100
    40277	93	I3 Crest  	PF/THD/Kfactor 	1	INT16 	100


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
            read1 = masterTCP.execute(slave_id, cst.READ_HOLDING_REGISTERS, 40150, 20)
            log.debug('Module: %s - Read 1 Successful : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x = TRY_AMOUNT
        except Exception as e:
            log.error('Module: %s - Read 1 Error : %s - %s:%s - TRIES:%s', DRIVER_NAME, device_name, ip_address, port, x)
            x += 1
            time.sleep(0.5)
    
    if not "read1" in locals():
        log.error('Modbus Scan Failed (Read1) : %.4f (DRIVER: %s - DEVICE: %s - UNIT: %s:%s)',(time.time() - start_time),DRIVER_NAME, device_name, ip_address, port)  
        return False

    #JUST THE VOLTAGES 
    values['Vll_ab']        = convert_registers_to_long(12, 13, False, 0, read1) 
    values['Vll_ac']        = convert_registers_to_long(14, 15, False, 0, read1) 
    values['Vll_ca']        = convert_registers_to_long(16, 17, False, 0, read1) 
    
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