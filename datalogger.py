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


def main(args):
    # Get device information from yaml file
    #data_path = "/home/pi/solarian-datalogger-test/data/"
    data_path = cwd+"/data/"
    config_file  = cwd+"/config/"+args.config
    devices = read_device_map(config_file)
    config_filename = os.path.splitext(os.path.basename(args.config))[0]
    data_package = []

    # Get the data from devices in devices yaml file and append to a file
    for device in devices:
        if device['enabled']:
            try:
                #Import the device driver
                device_driver = importlib.import_module('drivers.'+device['driver'])
                log.debug('Driver Loaded: %s (%s:%s)',device_driver.get_version(),device['ip_address'],device['port'])
                data = device_driver.get_data(device['ip_address'],device['port'],device['slave_id'],device['name'])
                if data != False:
                    data_package.append(data)

            except Exception as e:
                log.error("Exception while reading device:"+str(e))
    
    # Get raspberry internals and also append to the datapack
    if(args.log_raspberry):
        import drivers.raspberry as rb
        data_package.append(rb.get_raspberry_internals())
        log.debug('Raspberry internals have been acquired')

    # Construct the filename
    file_name = data_path+"solarian_"+ \
                get_device_serial()+"_"+ \
                config_filename+"_"+ \
                get_timestamp()+ \
                ".json.gz"

    if args.verbose:
        print(json.dumps(data_package, indent=4))
    
    if not args.write_disabled:
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
        log.debug('{} <--> {} <--> {} <--> {} <--> {}'.format( device['name'], device['driver'], device['ip_address'], device['port'], device['slave_id']))
    
    #Return the device list
    return device_map

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

def get_timestamp():
    return datetime.today().strftime("%Y%m%d%H%M")

if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='YAML file containing device settings. Default "config.yml"')
    parser.add_argument('--log', default='WARNING', help='Log levels, DEBUG, INFO, WARNING, ERROR or CRITICAL')
    parser.add_argument('--pi-analytics', action='store_true', dest='log_raspberry', help='Enable or disable RaspberryPi device data acquisition')
    parser.add_argument('--verbose', action='store_true', help='Print the acquired data to console')
    parser.add_argument('--write-disabled', action='store_true', dest='write_disabled', help='Disabled file writing. Dry-run.')

    args = parser.parse_args()

    # Get current working directory (Fixes cron related issues)
    cwd = os.path.dirname(os.path.abspath(__file__))
    os.chdir(cwd)

    # Setup loggingg
    log = logging.getLogger('solarian-datalogger')
    loglevel = args.log.upper()
    log.setLevel(getattr(logging, loglevel))
    log_filename = cwd+"/logs/log_"+os.path.splitext(os.path.basename(args.config))[0]+".log"
    loghandle = logging.FileHandler(log_filename, 'a')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    loghandle.setFormatter(formatter)
    log.addHandler(loghandle)
    log.info('============ Datalogger Started =============')

    #Start timer
    start_time = time.time()

    #Run the main code
    try:
        main(args=args)
    except Exception as e:
        log.error("Exception (Main Thread): "+str(e))

    #Finish
    log.info("=== Datalogger Completed : %.4f Seconds ===" % (time.time() - start_time))
