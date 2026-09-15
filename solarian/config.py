# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Reading and, above all, checking the YAML configuration.

A datalogger fails quietly. It runs from cron on a Pi in a switchgear room
that nobody logs into for months, and the only symptom of a broken config is a
gap in the data that shows up weeks later in a report. The old code made that
easy: a device whose driver name was misspelled raised inside a broad
``except Exception`` that logged one line and carried on, a ``measurment:``
typo was accepted and ignored, and two devices sharing a name overwrote each
other downstream without a word.

So every mistake that can be caught by looking at the file is caught here, at
startup, and raised as ConfigError naming the file, the device and the key.
A config that loads is a config whose devices can be attempted.

Loading itself uses ``yaml.safe_load`` -- ``yaml.load(..., FullLoader)`` on a
file that an installer script may have written is a needless liberty -- inside
a ``with`` block, because the old ``yaml.load(open(path))`` left the file
handle to the garbage collector.
"""

import logging

import yaml

log = logging.getLogger('solarian.config')

# Everything a device may say. Anything else is a typo, and typos in this file
# are silent data loss rather than errors, which is why they are rejected.
ALLOWED_DEVICE_KEYS = frozenset({
    'name', 'driver', 'enabled', 'measurement', 'slave_id',
    'ip_address', 'port',
    'serial_port', 'baudrate', 'bytesize', 'parity', 'stopbits', 'xonxoff',
    'timeout', 'retries', 'backoff', 'max_backoff',
})

REQUIRED_DEVICE_KEYS = ('name', 'driver', 'enabled', 'measurement', 'slave_id')

# Optional keys that override solarian.modbus.DEFAULTS per device; keep this
# list in step with that mapping.
DEVICE_INT_KEYS = ('slave_id', 'port', 'baudrate', 'bytesize', 'stopbits', 'xonxoff')

# Float key -> whether zero is meaningful. A zero backoff means "retry at once",
# which is a choice; a zero timeout would make every single read fail.
DEVICE_FLOAT_KEYS = {'timeout': False, 'backoff': True, 'max_backoff': True}
DEVICE_TEXT_KEYS = ('name', 'driver', 'measurement', 'ip_address', 'serial_port')

PARITY_VALUES = ('N', 'E', 'O', 'M', 'S')
DEFAULT_PORT = 502

ALLOWED_MQTT_KEYS = frozenset({
    'topic', 'ip_address', 'port', 'username', 'password', 'enabled',
    'tls', 'tls_insecure', 'ca_certs', 'certfile', 'keyfile',
    # Read by MqttSink to distinguish two loggers publishing from one Pi.
    'client_id',
})
REQUIRED_MQTT_KEYS = ('topic', 'ip_address', 'port', 'enabled')
MQTT_BOOL_KEYS = ('tls', 'tls_insecure')
MQTT_PATH_KEYS = ('ca_certs', 'certfile', 'keyfile')

ALLOWED_GRAYLOG_KEYS = frozenset({'server_address', 'port'})


class ConfigError(Exception):
    """The configuration cannot be trusted; the run must not start."""


# -- loading ----------------------------------------------------------------

def _load_section(path, top_key):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            document = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError('%s: cannot be read: %s' % (path, exc)) from exc
    except yaml.YAMLError as exc:
        raise ConfigError('%s: is not valid YAML: %s' % (path, exc)) from exc

    if document is None:
        raise ConfigError('%s: file is empty' % path)
    if not isinstance(document, dict):
        raise ConfigError("%s: expected a mapping with a '%s:' key at the top "
                          'level, found %s' % (path, top_key,
                                               type(document).__name__))
    if top_key not in document:
        raise ConfigError("%s: missing top-level '%s:' key (found: %s)"
                          % (path, top_key, ', '.join(sorted(document)) or 'nothing'))
    return document[top_key]


def _entries(path, top_key):
    """The section as a list of mappings, or a ConfigError explaining why not."""
    section = _load_section(path, top_key)
    if section is None:
        raise ConfigError("%s: '%s:' has no entries" % (path, top_key))
    if not isinstance(section, list):
        raise ConfigError("%s: '%s:' must be a list, found %s"
                          % (path, top_key, type(section).__name__))
    for index, entry in enumerate(section, start=1):
        if not isinstance(entry, dict):
            raise ConfigError('%s: %s %d: expected a mapping of settings, found %s'
                              % (path, top_key.rstrip('s'), index,
                                 type(entry).__name__))
    return section


# -- validation helpers -----------------------------------------------------

def _where(path, label, index, name):
    if name:
        return '%s: %s %d (%s)' % (path, label, index, name)
    return '%s: %s %d' % (path, label, index)


def _fail(where, key, problem):
    raise ConfigError('%s: %s: %s' % (where, key, problem))


def _check_keys(where, entry, allowed, required):
    unknown = sorted(set(entry) - allowed)
    if unknown:
        raise ConfigError('%s: unknown key(s) %s; allowed keys are %s'
                          % (where, ', '.join(repr(k) for k in unknown),
                             ', '.join(sorted(allowed))))
    missing = [key for key in required if key not in entry]
    if missing:
        raise ConfigError('%s: missing required key(s) %s'
                          % (where, ', '.join(repr(k) for k in missing)))


def _check_int(where, entry, key, minimum=None):
    """Require a real int. YAML quotes turn 502 into '502', which pymodbus
    would only complain about much later, at connect time."""
    if key not in entry:
        return None
    value = entry[key]
    if value is None:
        _fail(where, key, 'has no value')
    # bool is an int subclass, and `slave_id: yes` is a mistake worth naming.
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(where, key, 'must be an integer, found %r (%s)'
              % (value, type(value).__name__))
    if minimum is not None and value < minimum:
        _fail(where, key, 'must be %d or greater, found %d' % (minimum, value))
    return value


def _check_float(where, entry, key, zero_allowed=False):
    if key not in entry:
        return None
    value = entry[key]
    if value is None:
        _fail(where, key, 'has no value')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(where, key, 'must be a number, found %r (%s)'
              % (value, type(value).__name__))
    if value < 0 or (value == 0 and not zero_allowed):
        _fail(where, key, 'must be %s, found %r'
              % ('zero or greater' if zero_allowed else 'greater than zero', value))
    return float(value)


def _check_text(where, entry, key):
    if key not in entry:
        return None
    value = entry[key]
    if not isinstance(value, str) or not value.strip():
        _fail(where, key, 'must be a non-empty string, found %r' % (value,))
    return value.strip()


def _check_bool(where, entry, key):
    value = entry[key]
    if not isinstance(value, bool):
        _fail(where, key, "must be yes/no or true/false, found %r (%s)"
              % (value, type(value).__name__))
    return value


# -- devices ----------------------------------------------------------------

def load_devices(path):
    """Return the validated device list from a config.yml.

    The returned mappings are what a Session and a driver receive: numeric
    settings are real numbers, `port` is filled in for TCP devices, and every
    required key is present, so no caller downstream needs a KeyError guard.
    """
    devices = []
    seen = {}

    for index, entry in enumerate(_entries(path, 'devices'), start=1):
        name = entry.get('name') if isinstance(entry.get('name'), str) else None
        where = _where(path, 'device', index, name)
        _check_keys(where, entry, ALLOWED_DEVICE_KEYS, REQUIRED_DEVICE_KEYS)

        device = dict(entry)
        for key in DEVICE_TEXT_KEYS:
            text = _check_text(where, entry, key)
            if text is not None:
                device[key] = text
        for key in DEVICE_INT_KEYS:
            _check_int(where, entry, key)
        for key, zero_allowed in DEVICE_FLOAT_KEYS.items():
            value = _check_float(where, entry, key, zero_allowed)
            if value is not None:
                device[key] = value
        _check_int(where, entry, 'retries', minimum=1)
        device['enabled'] = _check_bool(where, entry, 'enabled')

        if 'parity' in entry:
            parity = _check_text(where, entry, 'parity').upper()
            if parity not in PARITY_VALUES:
                _fail(where, 'parity', 'must be one of %s, found %r'
                      % (', '.join(PARITY_VALUES), entry['parity']))
            device['parity'] = parity

        _check_transport(where, device)

        first = seen.get(device['name'])
        if first is not None:
            raise ConfigError('%s: name %r is already used by device %d; device '
                              'names must be unique'
                              % (where, device['name'], first))
        seen[device['name']] = index
        devices.append(device)

    log.debug('%s: %d device(s), %d enabled', path, len(devices),
              sum(1 for d in devices if d['enabled']))
    return devices


def _check_transport(where, device):
    """A device is reachable over TCP or over a serial line, but it must be
    reachable over something; the old config could describe neither and the
    failure only surfaced as a connection error at poll time."""
    has_tcp = bool(device.get('ip_address'))
    has_serial = bool(device.get('serial_port'))

    if not has_tcp and not has_serial:
        _fail(where, 'ip_address/serial_port',
              'a device needs either ip_address (with port) for Modbus TCP or '
              'serial_port for Modbus RTU')
    if has_tcp and has_serial:
        log.warning('%s: has both ip_address and serial_port; the serial port '
                    'takes precedence and the address is ignored', where)
    if has_tcp and device.get('port') is None:
        device['port'] = DEFAULT_PORT


# -- mqtt -------------------------------------------------------------------

def load_mqtt(path):
    """Return the validated MQTT server list from an mqtt.yml.

    Nothing here is logged beyond topic, host and port: the old loader logged
    every field of every server, password included, at DEBUG.
    """
    servers = []

    for index, entry in enumerate(_entries(path, 'servers'), start=1):
        topic = entry.get('topic') if isinstance(entry.get('topic'), str) else None
        where = _where(path, 'server', index, topic)
        _check_keys(where, entry, ALLOWED_MQTT_KEYS, REQUIRED_MQTT_KEYS)

        server = dict(entry)
        server['topic'] = _check_text(where, entry, 'topic')
        server['ip_address'] = _check_text(where, entry, 'ip_address')
        _check_int(where, entry, 'port', minimum=1)
        server['enabled'] = _check_bool(where, entry, 'enabled')

        for key in ('username', 'password') + MQTT_PATH_KEYS:
            if key in entry and not isinstance(entry[key], str):
                _fail(where, key, 'must be a string when present')
        for key in MQTT_BOOL_KEYS:
            if key in entry:
                server[key] = _check_bool(where, entry, key)

        if server.get('tls_insecure'):
            log.warning('%s: tls_insecure is set, so the broker certificate is '
                        'not verified and the credentials can be intercepted',
                        where)

        servers.append(server)

    log.debug('%s: %d MQTT server(s), %d enabled', path, len(servers),
              sum(1 for s in servers if s['enabled']))
    return servers


# -- graylog ----------------------------------------------------------------

def load_graylog(path):
    """Return the single Graylog endpoint from a graylog.yml.

    The file's ``server:`` key holds a list for historical reasons but only one
    GELF handler is ever attached, so the first entry is the configuration and
    any others are a mistake worth mentioning.
    """
    section = _load_section(path, 'server')

    if isinstance(section, list):
        if not section:
            raise ConfigError("%s: 'server:' has no entries" % path)
        if len(section) > 1:
            log.warning('%s: %d Graylog servers configured; only the first is '
                        'used', path, len(section))
        entry = section[0]
    else:
        entry = section

    if not isinstance(entry, dict):
        raise ConfigError('%s: server 1: expected a mapping of settings, found %s'
                          % (path, type(entry).__name__))

    where = _where(path, 'server', 1, entry.get('server_address'))
    _check_keys(where, entry, ALLOWED_GRAYLOG_KEYS, ('server_address', 'port'))
    _check_int(where, entry, 'port', minimum=1)

    return {'server_address': _check_text(where, entry, 'server_address'),
            'port': entry['port']}
