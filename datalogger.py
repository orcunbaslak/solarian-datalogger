#!/usr/bin/env python3
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
import sys
import yaml
import logging
import importlib
import gzip
import time
import json

from os import path
from datetime import datetime

import drivers.raspberry as rb

DEVICE_RETRY_COUNT = 3

# Change working dir to the same dir as this file
os.chdir(sys.path[0])

def main(device_yaml):
    # Get device information from yaml file
    #data_path = "/home/pi/solarian-datalogger/data/"
    data_path = os.getcwd()+"/data/"
    devices = read_device_map(device_yaml)
    config_filename = os.path.splitext(os.path.basename(device_yaml))[0]
    data_package = []

    # Get the data from devices in devices yaml file and append to a file
    for device in devices:
        x = 1
        while x < DEVICE_RETRY_COUNT:
            try:
                #Import the device driver
                device_driver = importlib.import_module('drivers.'+device['driver'])
                log.debug('Driver Loaded: %s (%s:%s)',device_driver.get_version(),device['ip_address'],device['port'])
                data = device_driver.get_data(device['ip_address'],device['port'],device['slave_id'],device['name'])
                data_package.append(data)
                x = DEVICE_RETRY_COUNT

            except Exception as e:
                log.error("Exception while reading device:"+str(e))
                x += 1
    
    # Get raspberry internals and also append to the datapack
    data_package.append(rb.get_raspberry_internals())

    #print(json.dumps(data_package, indent=1))
    file_name = data_path+"solarian_"+ \
                rb.get_device_serial()+"_"+ \
                config_filename+"_"+ \
                get_timestamp()+ \
                ".json.gz"

    with gzip.open(file_name, 'wt', encoding="utf-8") as file_to_write:
        json.dump(data_package, file_to_write)
        log.debug('JSON file write successful')


def read_device_map(device_yaml):
    #Check if the configuration file for devices exist. Raise exception if fails
    assert path.exists(device_yaml), 'Device map not found: %s' % device_yaml

    #Read the devices
    log.debug('Reading device list')
    new_map = yaml.load(open(device_yaml), Loader=yaml.FullLoader)
    device_map = new_map['devices']

    #Print the device list to logs
    for device in sorted(device_map, key=lambda x:sorted(x.keys())):
        log.debug('{} <--> {} <--> {} <--> {}'.format( device['name'], device['driver'], device['ip_address'], device['port']))
    
    #Return the device list
    return device_map

def get_timestamp():
    return datetime.today().strftime("%Y%m%d%H%M")

if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='YAML file containing device settings. Default "config.yml"')
    parser.add_argument('--log', default='WARNING', help='Log levels, DEBUG, INFO, WARNING, ERROR or CRITICAL')

    args = parser.parse_args()

    # Setup loggingg
    log = logging.getLogger('solarian-datalogger')
    loglevel = args.log.upper()
    log.setLevel(getattr(logging, loglevel))
    log_filename = "log_"+os.path.splitext(os.path.basename(args.config))[0]+".log"
    loghandle = logging.FileHandler(log_filename, 'a')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    loghandle.setFormatter(formatter)
    log.addHandler(loghandle)
    log.info('============ Datalogger Started =============')

    #Start timer
    start_time = time.time()

    #Run the main code
    try:
        main(device_yaml=args.config)
    except Exception as e:
        log.error("Exception (Main Thread): "+str(e))

    #Finish
    log.info("=== Datalogger Completed : %.4f Seconds ===" % (time.time() - start_time))
