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

Most register maps are fixed, and most drivers declare one as a plain list of
Blocks. Some devices are not fixed: a tracker sub-array controller fronts
however many tracker nodes were installed, and its map is the same fifteen
registers repeated that many times. Such a driver declares an `options` list
describing the settings it needs from the configuration, and passes a callable
for `blocks` that builds the map from them. config.py folds those option names
into its allow-list, so they are validated at startup alongside every other
key rather than being read out of an untyped bag at poll time.
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

# A single Modbus request cannot ask for an unlimited span: the quantity field
# of FC 0x03/0x04 caps at 0x7D registers, and FC 0x01/0x02 at 0x7D0 bits. A
# block over the ceiling is a map that can never be read, and saying so at
# import time beats an exception response at 3am.
MAX_REGISTERS_PER_READ = 125
MAX_BITS_PER_READ = 2000


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
        """Reject register maps that cannot be right.

        Offsets past the end of the block, bit positions outside a 16-bit
        register, and two fields emitting the same name. That last one matters
        because emitting is a dict assignment: a duplicate silently overwrites
        the earlier series, losing data with no error anywhere. Several drivers
        deliberately reuse a Bitfield prefix across status words and rely on
        the bit names not colliding, which is a comment today and a check now.
        """
        if self.count < 1:
            raise ValueError('block %s: count must be positive' % self.name)
        if self.function in (modbus.COILS, modbus.DISCRETE):
            ceiling, unit = MAX_BITS_PER_READ, 'bits'
        else:
            ceiling, unit = MAX_REGISTERS_PER_READ, 'registers'
        if self.count > ceiling:
            raise ValueError(
                'block %s: asks for %d %s, but one %s request can return at '
                'most %d; split it into several blocks'
                % (self.name, self.count, unit,
                   modbus.FUNCTION_NAMES.get(self.function, self.function),
                   ceiling))
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
            for bit in getattr(field, 'bits', ()) or ():
                if not 0 <= bit <= 15:
                    raise ValueError(
                        'block %s: field %r maps bit %d, but a Modbus register '
                        'is 16 bits, so it would always read 0'
                        % (self.name, field.name, bit))

    def emitted_names(self):
        """Every field name this block writes, in order, bitfields expanded."""
        names = []
        for field in self.fields:
            bits = getattr(field, 'bits', None)
            if bits:
                names.extend(field.prefix + bits[b] for b in sorted(bits))
            else:
                names.append(field.name)
        return names

    def __repr__(self):
        return '<Block %s %s@%d+%d, %d fields>' % (
            self.name, modbus.FUNCTION_NAMES.get(self.function, self.function),
            self.address, self.count, len(self.fields))


class OptionError(Exception):
    """A driver option is missing or out of range.

    Carries only what is wrong with the value; the caller adds the file, the
    device and the key, because it knows them and this does not.
    """


class IntOption:
    """A whole-number setting a driver needs from the device configuration.

    Declared by the driver, validated by config.py at startup and again by the
    driver at use, so a value can reach a register map neither unchecked nor
    twice-checked by two different sets of rules.

    A range, not just a type, for the reason DEVICE_INT_RANGES gives in
    config.py: a validator that accepts tracker_count: 0 is not doing the job
    it exists for. Leaving `default` unset makes the option required, which is
    right whenever guessing would be worse than refusing to start -- how many
    trackers a controller fronts is not something to assume.

    `example` is the value --register-map assumes when no device is at hand.
    """

    __slots__ = ('name', 'minimum', 'maximum', 'default', 'example', 'help')

    def __init__(self, name, minimum, maximum, default=None, example=None,
                 help=None):
        if minimum > maximum:
            raise ValueError('option %s: minimum %d exceeds maximum %d'
                             % (name, minimum, maximum))
        self.name = name
        self.minimum = minimum
        self.maximum = maximum
        self.default = default
        self.example = example if example is not None else (
            default if default is not None else minimum)
        self.help = help
        for label, value in (('default', default), ('example', self.example)):
            if value is not None and not minimum <= value <= maximum:
                raise ValueError('option %s: %s %d is outside its own range '
                                 '%d..%d' % (name, label, value, minimum, maximum))

    @property
    def required(self):
        return self.default is None

    def validate(self, value):
        """The value to use, or OptionError saying why there isn't one."""
        if value is None:
            if self.default is None:
                raise OptionError('required by this driver, but not set')
            return self.default
        # bool is an int subclass, and `tracker_count: yes` is a mistake worth
        # naming rather than silently reading as 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise OptionError('must be an integer, found %r (%s)'
                              % (value, type(value).__name__))
        if not self.minimum <= value <= self.maximum:
            raise OptionError('must be between %d and %d, found %d'
                              % (self.minimum, self.maximum, value))
        return value

    def describe(self):
        return {'name': self.name, 'kind': 'int',
                'minimum': self.minimum, 'maximum': self.maximum,
                'required': self.required, 'default': self.default,
                'help': self.help}

    def __repr__(self):
        return '<IntOption %s %d..%d%s>' % (
            self.name, self.minimum, self.maximum,
            '' if self.required else ' default=%d' % self.default)


class Driver:
    """A device's register map plus the metadata the logger needs.

    `defaults` supplies driver-level transport settings (a slow meter may want
    a longer timeout); a device's own configuration still overrides them.
    `postprocess(values, blocks, device)` is the escape hatch for the handful
    of quirks that a declarative map cannot express, such as clamping a sensor
    that reports negative irradiation at night.

    `blocks` is normally a list. A device whose map depends on how it was
    installed passes a callable instead, together with the `options` it needs:

        Driver(name=..., version=...,
               options=[IntOption('tracker_count', 1, 181)],
               blocks=lambda options: [...])

    The callable receives the validated options and nothing else, so the same
    options always produce the same map -- which is what makes caching them
    safe. `blocks` for such a driver holds the map for the options' `example`
    values, so --register-map, field_count and repr still describe something
    real; read() always rebuilds from the device at hand.
    """

    def __init__(self, name, version, blocks, defaults=None, postprocess=None,
                 description=None, options=()):
        self.name = name
        self.version = version
        self.defaults = dict(defaults or {})
        self.postprocess = postprocess
        self.description = description
        self.options = tuple(options)

        option_names = [o.name for o in self.options]
        if len(option_names) != len(set(option_names)):
            raise ValueError('%s: duplicate option names %s' % (name, option_names))

        if callable(blocks):
            self._build = blocks
            # Keyed by the option values, never by the device: two devices with
            # the same options share a map, and a device cannot poison another's.
            # Races are benign -- two threads may build the same list and one
            # wins -- so this stays lock-free, as runner.py polls in parallel.
            self._cache = {}
            self.blocks = self.blocks_for(
                {o.name: o.example for o in self.options})
        else:
            self._build = None
            self._cache = None
            self.blocks = self._validated(list(blocks))

    @property
    def parametric(self):
        """True when the register map is built from the device configuration."""
        return self._build is not None

    def _validated(self, blocks):
        """Reject a map that would lose data, whoever assembled it."""
        names = [b.name for b in blocks]
        if len(names) != len(set(names)):
            raise ValueError('%s: duplicate block names %s' % (self.name, names))

        # Across blocks too: inv_abb_pvs980 shares one Bitfield prefix between
        # two status words in different blocks, so a within-block check alone
        # would miss the collision.
        seen, clashes = set(), []
        for block in blocks:
            for emitted in block.emitted_names():
                if emitted in seen:
                    clashes.append(emitted)
                seen.add(emitted)
        if clashes:
            raise ValueError(
                '%s: these field names are emitted more than once, so the '
                'later value would silently overwrite the earlier one: %s'
                % (self.name, ', '.join(sorted(set(clashes)))))
        return blocks

    # -- options -------------------------------------------------------------

    def resolve_options(self, device):
        """This driver's options for one device, validated and defaulted.

        config.py has normally checked these already and said so in terms of
        the file and the device. This runs anyway, because read() is also
        reachable from tests and scripts that never went through config.py,
        and a register map built from an unchecked number is worth nothing.
        """
        resolved = {}
        for option in self.options:
            try:
                resolved[option.name] = option.validate(device.get(option.name))
            except OptionError as exc:
                raise OptionError('%s: %s: %s' % (self.name, option.name, exc)) from exc
        return resolved

    def blocks_for(self, device):
        """The register map to read for one device's configuration."""
        if self._build is None:
            return self.blocks
        options = self.resolve_options(device)
        key = tuple(sorted(options.items()))
        built = self._cache.get(key)
        if built is None:
            built = self._validated(list(self._build(options)))
            self._cache[key] = built
        return built

    # -- sampling ------------------------------------------------------------

    def read(self, device):
        """Sample the device and return an ordered mapping of named values.

        Raises modbus.DeviceError if the device cannot be read completely.
        """
        values = OrderedDict()
        values['Device_Name'] = device.get('name')
        values['Measurement_Suffix'] = device.get('measurement')
        values['Date'] = utc_minute()

        declared = self.blocks_for(device)
        with modbus.Session(device, self.defaults, self.name) as session:
            blocks = session.read_blocks(declared)

        for block in declared:
            decode_block(blocks[block.name], block.fields, values)

        if self.postprocess is not None:
            self.postprocess(values, blocks, device)
        return values

    # -- introspection -------------------------------------------------------

    @property
    def field_count(self):
        return self.count_fields(self.blocks)

    @staticmethod
    def count_fields(blocks):
        total = 0
        for block in blocks:
            for field in block.fields:
                total += len(getattr(field, 'bits', ())) or 1
        return total

    def register_map(self, device=None):
        """The driver's map as plain data, for documentation or export.

        A parametric driver has no single map, so passing a device describes
        that device's, and passing nothing describes the options' `example`
        configuration -- named in the output, so nobody reads the sample as
        the whole truth.
        """
        blocks = self.blocks_for(device) if device is not None else self.blocks
        info = {
            'driver': self.name,
            'version': self.version,
            'blocks': [{
                'name': b.name,
                'function': modbus.FUNCTION_NAMES.get(b.function, b.function),
                'address': b.address,
                'count': b.count,
                'fields': [f.describe() for f in b.fields],
            } for b in blocks],
        }
        if self.options:
            info['options'] = [o.describe() for o in self.options]
            info['describes'] = (self.resolve_options(device) if device is not None
                                 else {o.name: o.example for o in self.options})
        return info

    def version_string(self):
        return '%s v%s' % (self.name, self.version)

    def __repr__(self):
        return '<Driver %s v%s, %d blocks, %d fields%s>' % (
            self.name, self.version, len(self.blocks), self.field_count,
            ', parametric' if self.parametric else '')


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
        self.options = ()
        self.parametric = False
        self.description = 'legacy driver module'

    def blocks_for(self, device):
        return self.blocks

    def resolve_options(self, device):
        return {}

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

    def register_map(self, device=None):
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
