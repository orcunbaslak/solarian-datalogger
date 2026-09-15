# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Health metrics for the logger machine itself.

This is deliberately not a driver. A driver describes a register map on a
device reached over Modbus; the numbers here come from the host's own kernel,
share none of that machinery, and are collected once per run rather than per
device. Keeping it separate is what lets the driver contract stay narrow.
"""

import shutil
import logging
import subprocess

from collections import OrderedDict

import psutil

from solarian.driver import utc_minute
from solarian.identity import device_serial

log = logging.getLogger('solarian.host')

MIB = 2 ** 20
GIB = 2 ** 30

HOST_DEVICE_NAME = 'SOLARIAN_DATALOGGER'


def cpu_temperature():
    """CPU temperature in degrees Celsius, or None when unavailable.

    Prefers psutil, which works on any Linux exposing thermal zones, and falls
    back to the Raspberry Pi's vcgencmd. The original called
    ``os.popen("vcgencmd measure_temp")`` unconditionally and then did
    ``float("")`` on any machine without that binary, raising ValueError and
    taking the whole reading down with it.
    """
    try:
        sensors = psutil.sensors_temperatures()
    except (AttributeError, OSError) as exc:
        log.debug('psutil could not read temperature sensors: %s', exc)
        sensors = {}

    for label in ('cpu_thermal', 'coretemp', 'soc_thermal', 'k10temp'):
        readings = sensors.get(label)
        if readings:
            return round(float(readings[0].current), 2)

    vcgencmd = shutil.which('vcgencmd')
    if vcgencmd is None:
        return None
    try:
        output = subprocess.run([vcgencmd, 'measure_temp'], capture_output=True,
                                text=True, timeout=5, check=True).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        log.debug('vcgencmd failed: %s', exc)
        return None

    # Output looks like: temp=47.2'C
    cleaned = output.strip().replace('temp=', '').replace("'C", '').replace('C', '')
    try:
        return float(cleaned)
    except ValueError:
        log.debug('unrecognised vcgencmd output: %r', output)
        return None


def host_metrics():
    """CPU, load, memory and disk figures for this machine."""
    values = OrderedDict()
    values['Device_Name'] = HOST_DEVICE_NAME

    temperature = cpu_temperature()
    if temperature is not None:
        values['CPU_Temp'] = temperature
    values['CPU_Usage'] = psutil.cpu_percent()

    # psutil.getloadavg() returns the 1, 5 and 15 minute averages. The previous
    # version labelled these 5, 10 and 15 minutes, so two of the three series
    # recorded in InfluxDB were named for a window they never measured.
    try:
        one, five, fifteen = psutil.getloadavg()
        values['SystemLoad_1min'] = one
        values['SystemLoad_5min'] = five
        values['SystemLoad_15min'] = fifteen
    except (AttributeError, OSError) as exc:
        log.debug('load average unavailable: %s', exc)

    ram = psutil.virtual_memory()
    # `cached` is Linux-specific; absent on some platforms.
    cached = getattr(ram, 'cached', None)
    if cached is not None:
        values['RAM_Cached'] = round(cached / MIB, 2)
    values['RAM_Used'] = round(ram.used / MIB, 2)
    values['RAM_Free'] = round(ram.free / MIB, 2)
    values['RAM_Available'] = round(ram.available / MIB, 2)
    values['RAM_Percent'] = ram.percent

    disk = psutil.disk_usage('/')
    values['DISK_Total'] = round(disk.total / GIB, 2)
    values['DISK_Used'] = round(disk.used / GIB, 2)
    values['DISK_Free'] = round(disk.free / GIB, 2)
    values['DISK_Percent'] = disk.percent

    values['Date'] = utc_minute()
    values['Device_Serial'] = device_serial()
    return values
