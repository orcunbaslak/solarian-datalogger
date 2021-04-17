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
import psutil

from datetime import datetime
from collections import OrderedDict

import logging
log = logging.getLogger('solarian-datalogger')

DRIVER_NAME = 'RASPBERRY'
DRIVER_VERSION = '0.1'


def get_raspberry_internals():
    #Create dictionary 
    values = OrderedDict()
    values['Device_Name'] = "SOLARIAN_DATALOGGER"
    
    # Get CPU and Load related values
    load_averages = psutil.getloadavg()
    values['CPU_Temp'] = measure_raspberry_cpu_temp()
    values['CPU_Usage'] = psutil.cpu_percent()
    values['SystemLoad_5mins'] = load_averages[0]
    values['SystemLoad_10mins'] = load_averages[1]
    values['SystemLoad_15mins'] = load_averages[2]
    
    # Get ram values
    ram = psutil.virtual_memory()
    values['RAM_Cached'] = round(ram.cached / 2**20,2)       # MiB.
    values['RAM_Used'] = round(ram.used / 2**20,2)
    values['RAM_Free'] = round(ram.free / 2**20,2)
    values['RAM_Available'] = round(ram.available / 2**20,2)
    values['RAM_Percent'] = ram.percent
    
    # Get disk usage information
    disk = psutil.disk_usage('/')
    values['DISK_Total'] = round(disk.total / 2**30,2)     # GiB.
    values['DISK_Used'] = round(disk.used / 2**30,2)
    values['DISK_Free'] = round(disk.free / 2**30,2)
    values['DISK_Percent'] = disk.percent

    # Append the time for database
    values['Date'] = get_timestamp_for_influxdb()

    # Add the device serial number also
    values['Device_Serial'] = get_device_serial()

    return values

def get_device_serial():
    # Extract serial from cpuinfo file
    cpuserial = "00000000"
    try:
      f = open('/proc/cpuinfo','r')
      for line in f:
        if line[0:6]=='Serial':
          cpuserial = line[18:26]
      f.close()
    except:
      cpuserial = "ERROR0000"

    return cpuserial

def measure_raspberry_cpu_temp():
    temp = os.popen("vcgencmd measure_temp").readline()
    temp = temp.replace("temp=","").replace("'C","")
    return float(temp)

def get_timestamp_for_influxdb():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:00Z")
