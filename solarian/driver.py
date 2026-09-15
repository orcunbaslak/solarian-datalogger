# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""The driver contract and the registry that loads drivers by name.

A driver is a declaration, not a procedure. It states which register blocks a
device exposes and how to read the values inside them; connecting, retrying and
error reporting belong to the framework.

The old contract was ``get_data(ip_address, port, slave_id, device_name,
measurement_suffix)`` — five positional, transport-specific arguments. It could
not express a serial device, so the one RTU driver in the tree ignored
``ip_address`` and ``port`` and hardcoded ``/dev/ttyUSB0`` while still logging
the unused IP. Drivers now receive the device's configuration mapping, which
can grow a field without breaking every other driver. Modules written against
the old contract still load, through LegacyDriver below.
"""

import logging
import importlib

from collections import OrderedDict
from datetime import datetime, timezone

from solarian import modbus
from solarian.decode import decode_block

log = logging.getLogger('solarian.driver')

# Where drivers are looked up, in order. The second entry keeps drivers that
# users dropped into a top-level drivers/ package working.
SEARCH_PACKAGES = ('solarian.drivers', 'drivers')


def utc_minute():
    """UTC timestamp truncated to the minute, the resolution InfluxDB stores."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:00Z')


class Block:
    """One contiguous run of registers, and how to interpret it."""

    __slots__ = ('name', 'function', 'address', 'count', 'fields', 'note')

    def __init__(self, name, function, address, count, fields=(), note=None):
        self.name = name
        self.function = function
        self.address = address
        self.count = count
        self.fields = list(fields)
        self.note = note
        self._check()

    def _check(self):
        """Catch register maps that read past the end of their own block."""
        if self.count < 1:
            raise ValueError('block %s: count must be positive' % self.name)
        for field in self.fields:
            for attr in ('offset', 'high', 'low'):
                position = getattr(field, attr, None)
                if position is None:
                    continue
                if not 0 <= position < self.count:
                    raise ValueError(
                        'block %s: field %r reads offset %d but the block is '
                        'only %d registers long'
                        % (self.name, field.name, position, self.count))

    def __repr__(self):
        return '<Block %s %s@%d+%d, %d fields>' % (
            self.name, modbus.FUNCTION_NAMES.get(self.function, self.function),
            self.address, self.count, len(self.fields))


class Driver:
    """A device's register map plus the metadata the logger needs.

    `defaults` supplies driver-level transport settings (a slow meter may want
    a longer timeout); a device's own configuration still overrides them.
    `postprocess(values, blocks, device)` is the escape hatch for the handful
    of quirks that a declarative map cannot express, such as clamping a sensor
    that reports negative irradiation at night.
    """

    def __init__(self, name, version, blocks, defaults=None, postprocess=None,
                 description=None):
        self.name = name
        self.version = version
        self.blocks = list(blocks)
        self.defaults = dict(defaults or {})
        self.postprocess = postprocess
        self.description = description
        names = [b.name for b in self.blocks]
        if len(names) != len(set(names)):
            raise ValueError('%s: duplicate block names %s' % (name, names))

    # -- sampling ------------------------------------------------------------

    def read(self, device):
        """Sample the device and return an ordered mapping of named values.

        Raises modbus.DeviceError if the device cannot be read completely.
        """
        values = OrderedDict()
        values['Device_Name'] = device.get('name')
        values['Measurement_Suffix'] = device.get('measurement')
        values['Date'] = utc_minute()

        with modbus.Session(device, self.defaults, self.name) as session:
            blocks = session.read_blocks(self.blocks)

        for block in self.blocks:
            decode_block(blocks[block.name], block.fields, values)

        if self.postprocess is not None:
            self.postprocess(values, blocks, device)
        return values

    # -- introspection -------------------------------------------------------

    @property
    def field_count(self):
        total = 0
        for block in self.blocks:
            for field in block.fields:
                total += len(getattr(field, 'bits', ())) or 1
        return total

    def register_map(self):
        """The driver's map as plain data, for documentation or export."""
        return {
            'driver': self.name,
            'version': self.version,
            'blocks': [{
                'name': b.name,
                'function': modbus.FUNCTION_NAMES.get(b.function, b.function),
                'address': b.address,
                'count': b.count,
                'fields': [f.describe() for f in b.fields],
            } for b in self.blocks],
        }

    def version_string(self):
        return '%s v%s' % (self.name, self.version)

    def __repr__(self):
        return '<Driver %s v%s, %d blocks, %d fields>' % (
            self.name, self.version, len(self.blocks), self.field_count)


class LegacyDriver:
    """Adapter for a module written against the original get_data() contract.

    Keeps third-party drivers loading unchanged. It cannot supply a serial
    port or per-device timeouts, because the old signature had nowhere to put
    them — which is the reason the contract changed.
    """

    def __init__(self, module, name):
        self.module = module
        self.name = getattr(module, 'DRIVER_NAME', name)
        self.version = getattr(module, 'DRIVER_VERSION', '0')
        self.blocks = []
        self.defaults = {}
        self.description = 'legacy driver module'

    def read(self, device):
        values = self.module.get_data(
            device.get('ip_address'), device.get('port'), device.get('slave_id'),
            device.get('name'), device.get('measurement'))
        # The old contract signalled failure by returning False.
        if values is False or values is None:
            raise modbus.DeviceError('legacy driver reported failure',
                                     device=device.get('name'))
        return values

    def version_string(self):
        getter = getattr(self.module, 'get_version', None)
        if callable(getter):
            return getter()
        return '%s v%s' % (self.name, self.version)

    def register_map(self):
        return {'driver': self.name, 'version': self.version, 'blocks': []}

    def __repr__(self):
        return '<LegacyDriver %s v%s>' % (self.name, self.version)


class DriverNotFound(Exception):
    """No module could be imported for the configured driver name."""


_CACHE = {}


def load(driver_name, use_cache=True):
    """Import a driver by the name used in configuration.

    Returns a Driver (declarative) or LegacyDriver (old get_data contract).
    Raises DriverNotFound with the names tried, rather than letting a typo in
    the YAML disappear into a generic exception handler.
    """
    if use_cache and driver_name in _CACHE:
        return _CACHE[driver_name]

    if not driver_name or not driver_name.replace('_', '').isalnum():
        raise DriverNotFound('invalid driver name: %r' % (driver_name,))

    tried, last_error = [], None
    for package in SEARCH_PACKAGES:
        dotted = '%s.%s' % (package, driver_name)
        tried.append(dotted)
        try:
            module = importlib.import_module(dotted)
        except ImportError as exc:
            # Only swallow "this module isn't here"; a driver whose own
            # imports are broken must surface, not look like a missing driver.
            if getattr(exc, 'name', None) not in (dotted, package):
                raise
            last_error = exc
            continue

        driver = getattr(module, 'DRIVER', None)
        if isinstance(driver, Driver):
            _CACHE[driver_name] = driver
            return driver
        if hasattr(module, 'get_data'):
            legacy = LegacyDriver(module, driver_name)
            log.warning('driver %s uses the legacy get_data() contract; it '
                        'cannot be given a serial port or per-device timeouts',
                        driver_name)
            _CACHE[driver_name] = legacy
            return legacy
        raise DriverNotFound(
            '%s defines neither a DRIVER declaration nor get_data()' % dotted)

    raise DriverNotFound('no module found for driver %r (tried %s)%s' % (
        driver_name, ', '.join(tried),
        '; last error: %s' % last_error if last_error else ''))


def available():
    """Names of the drivers shipped with the package."""
    import pkgutil
    from solarian import drivers as package
    return sorted(m.name for m in pkgutil.iter_modules(package.__path__)
                  if not m.name.startswith('_'))
