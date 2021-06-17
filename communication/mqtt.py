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

import ssl
import yaml
import time
import json
import copy
import logging
from paho.mqtt.publish import multiple
from collections import defaultdict

from os import path

log = logging.getLogger('solarian-datalogger')

def get_mqtt_config(config_yaml):
    #Check if the configuration file for mqtt servers exist. Raise exception if fails
    assert path.exists(config_yaml), 'Device map not found: %s' % config_yaml

    #Read the server list
    log.debug('Reading MQTT server list')
    new_list = yaml.load(open(config_yaml), Loader=yaml.FullLoader)
    server_list = new_list['servers']

    #Print the server list to logs
    for device in sorted(server_list, key=lambda x:sorted(x.keys())):
        log.debug('{} <--> {} <--> {} <--> {} <--> {} <--> {}'.format( device['topic'], device['ip_address'], device['port'], device['username'], device['password'], device['enabled']))
    
    #Return the server list
    return server_list

def send_data(mqtt_config_path, device_serial, data_package):
    #Get timings
    start_time = time.time()

    #Get servers list
    servers = get_mqtt_config(mqtt_config_path)

    #Loop thru each server and PUBLISH
    for server in servers:
        if server['enabled']:
            try:
                #Create the iterable data package
                mqtt_payload = []
                for data in data_package:
                    payload = defaultdict(dict)
                    payload['topic'] = server['topic']+"/"+data['Device_Name']
                    payload['payload'] = json.dumps(data)
                    mqtt_payload.append(copy.deepcopy(payload))
                
                auth_items = defaultdict(dict)
                auth_items['username']= server['username']
                auth_items['password'] = server['password']

                multiple(mqtt_payload,
                        hostname=server['ip_address'],
                        port=server['port'],
                        keepalive=15,
                        auth=auth_items,
                        tls=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2))        

            except Exception as e:
                log.error("Exception while sending MQTT message:"+str(e))
    log.debug('MQTT Send compled in : %.4f',(time.time() - start_time)) 

