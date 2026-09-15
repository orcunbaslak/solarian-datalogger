# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""One place that decides where log records go, and what may not be in them.

Three problems with the previous arrangement, all of them field problems:

* Logging went to ``FileHandler(path, 'a')``. Cron runs the logger every
  minute, so at DEBUG the file grew without bound until the SD card filled and
  the Pi stopped recording data. Rotation is not a nicety here.
* MQTT credentials were logged in cleartext (``communication/mqtt.py`` printed
  the whole server entry, password included), so the secret ended up in the
  log file and, with --graylog, on the wire to a central server.
* Logging was configured inline in ``datalogger.py`` against a filter that read
  module globals, which meant nothing else could be configured for logging and
  nothing could be tested.

Filters are attached to the handlers rather than to the logger on purpose. A
record made by ``solarian.modbus`` reaches the ``solarian`` logger's handlers
by propagation, and propagation does not run the ancestor logger's filters --
only the handlers' own. A redaction filter on the logger would therefore miss
every record raised by a child module, which is most of them.
"""

import os
import re
import logging
import logging.handlers

from solarian import identity

log = logging.getLogger('solarian.logging_setup')

LOGGER_NAME = 'solarian'
LOG_FORMAT = ('%(asctime)s %(levelname)-8s %(device_id)s %(config_file)s '
              '%(name)s: %(message)s')

# ~5 MB x 5 keeps a bounded worst case of ~30 MB on the SD card.
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

FILE_HANDLER = 'solarian.file'
GELF_HANDLER = 'solarian.gelf'
CONSOLE_HANDLER = 'solarian.console'
NULL_HANDLER = 'solarian.null'

REDACTED = '***'

# A printf conversion specifier, used both to recognise a placeholder sitting
# where a secret would be and to work out which argument it will consume.
_CONVERSION_SOURCE = (r'%(?:\((?P<mapkey>[^)]*)\))?[-+ #0]*[\d*]*'
                      r'(?:\.[\d*]+)?[hlL]?(?P<type>[diouxXeEfFgGcrsa%])')
_CONVERSION = re.compile(_CONVERSION_SOURCE)

# Matches ``key = value`` / ``key: value`` / ``'key': 'value'`` for the key
# names that carry credentials. The value group stops at the first delimiter so
# that only the secret itself is replaced and the surrounding message survives.
#
# The bare-space separator catches ``log.info('with password %s', pw)``, where
# nothing but a space stands between the key and the secret. It is deliberately
# limited to a following placeholder: ``'auth failed for %s'`` names a key and
# has a placeholder in it, but the two are not next to each other, and blanking
# the username there would help nobody.
#
# A whole conversion specifier is tried before the general value, so that
# ``%(password)s`` is recognised as one placeholder rather than being cut at
# the closing parenthesis.
SECRET_PATTERN = re.compile(
    r'(?P<key>\b(?:api[_-]?key|password|passwd|secret|token|auth)\b)'
    r'(?P<sep>["\']?\s*[:=]>?\s*["\']?|\s+(?=[%{]))'
    r'(?P<value>' + _CONVERSION_SOURCE + r'|[^\s,;"\'})\]]+)',
    re.IGNORECASE)

# Key names, reduced to letters and digits, whose values are never loggable.
SECRET_KEYS = frozenset({'apikey', 'password', 'passwd', 'secret', 'token', 'auth'})


def _is_secret_key(key):
    """True for 'password', 'API_KEY', 'mqtt_password' and friends."""
    if not isinstance(key, str):
        return False
    flat = re.sub(r'[^a-z0-9]', '', key.lower())
    return any(flat == name or flat.endswith(name) for name in SECRET_KEYS)


def _redact_text(text):
    """Replace ``key=secret`` values in a plain string."""
    def swap(match):
        return match.group('key') + match.group('sep') + REDACTED
    return SECRET_PATTERN.sub(swap, text)


def _redact_mapping(mapping):
    """Copy a mapping with secret-named values replaced, recursing into it."""
    clean = {}
    for key, value in mapping.items():
        clean[key] = REDACTED if _is_secret_key(key) else _redact_value(value)
    return clean


def _redact_value(value):
    if isinstance(value, dict):
        return _redact_mapping(value)
    if isinstance(value, (list, tuple)):
        rebuilt = [_redact_value(item) for item in value]
        return type(value)(rebuilt) if isinstance(value, list) else tuple(rebuilt)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _positional_index(message, before):
    """How many positional conversions appear in message[:before]."""
    count = 0
    for conversion in _CONVERSION.finditer(message, 0, before):
        if conversion.group('type') != '%' and conversion.group('mapkey') is None:
            count += 1
    return count


def _redact_args(args, positions, mapkeys):
    if args is None:
        return None
    if isinstance(args, dict):
        clean = _redact_mapping(args)
        for key in mapkeys:
            if key in clean:
                clean[key] = REDACTED
        return clean
    clean = []
    for index, value in enumerate(args):
        clean.append(REDACTED if index in positions else _redact_value(value))
    return tuple(clean)


def _redact_record(message, args):
    """Scrub a record's format string and its arguments together.

    ``log.info('password=%s', pw)`` hides the secret behind a placeholder, so
    the format string cannot simply be rewritten -- replacing ``%s`` there
    would leave an argument with nothing to fill and raise at format time. The
    placeholder is instead traced back to the argument it consumes and that
    argument is replaced.
    """
    if not isinstance(message, str):
        return message, _redact_args(args, (), ())

    matches = list(SECRET_PATTERN.finditer(message))
    if not matches:
        return message, _redact_args(args, (), ())

    pieces = []
    consumed = 0
    positions = set()
    mapkeys = []
    for match in matches:
        value = match.group('value')
        conversion = _CONVERSION.fullmatch(value)
        if conversion is not None and conversion.group('type') != '%':
            if conversion.group('mapkey') is None:
                positions.add(_positional_index(message, match.start('value')))
            else:
                mapkeys.append(conversion.group('mapkey'))
            continue
        pieces.append(message[consumed:match.start('value')])
        pieces.append(REDACTED)
        consumed = match.end('value')
    pieces.append(message[consumed:])
    return ''.join(pieces), _redact_args(args, positions, mapkeys)


class RedactingFilter(logging.Filter):
    """Removes credentials from records on their way to a handler.

    Nothing is dropped: a record with a secret in it is still logged, minus the
    secret. The filter is idempotent, which matters because handlers share one
    record object and each handler filters it again.
    """

    def filter(self, record):
        record.msg, record.args = _redact_record(record.msg, record.args)
        if getattr(record, 'exc_text', None):
            record.exc_text = _redact_text(record.exc_text)
        return True


class ContextFilter(logging.Filter):
    """Stamps every record with the machine and the config it came from.

    A Graylog stream mixes the whole fleet together; without these two fields
    a message cannot be traced back to a plant.
    """

    def __init__(self, device_id='unknown', config_file='unknown'):
        super().__init__()
        self.device_id = device_id
        self.config_file = config_file

    def filter(self, record):
        record.device_id = self.device_id
        record.config_file = self.config_file
        return True


def _level_value(level):
    """Translate a level name into its number, rejecting nonsense loudly.

    ``getattr(logging, level)`` raised AttributeError deep inside startup for
    a typo like --log DEBIG; a clear ValueError is easier to act on.
    """
    if isinstance(level, int) and not isinstance(level, bool):
        return level
    value = logging.getLevelName(str(level).strip().upper())
    if not isinstance(value, int):
        raise ValueError('unknown log level: %r' % (level,))
    return value


def _file_handler(target):
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return logging.handlers.RotatingFileHandler(
        target, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
        encoding='utf-8', delay=True)


def _gelf_handler(settings):
    """Build a GELF handler, or None when graypy is not installed.

    graypy is imported here rather than at module import time so a plant that
    does not use Graylog does not need the dependency at all.
    """
    try:
        import graypy
    except ImportError:
        log.warning('graylog requested but graypy is not installed; '
                    'remote logging disabled')
        return None
    return graypy.GELFTCPHandler(settings['server_address'], int(settings['port']))


def _attach(handler, formatter, context):
    """(Re)apply our formatter and filters without stacking duplicates."""
    handler.setFormatter(formatter)
    for existing in list(handler.filters):
        if isinstance(existing, (ContextFilter, RedactingFilter)):
            handler.removeFilter(existing)
    handler.addFilter(context)
    handler.addFilter(RedactingFilter())


def configure(level='WARNING', log_dir=None, config_name='config', graylog=None,
              console=False, device_id=None):
    """Set up the 'solarian' logger and return it.

    Declarative and repeatable: the handlers asked for are the handlers the
    logger ends up with, so calling this twice reconfigures rather than
    duplicating. That is what makes it safe to call from both the CLI and a
    test, and it is why each handler carries a name and the settings it was
    built from.

    ``graylog`` is the mapping from config.load_graylog (server_address, port);
    ``log_dir`` of None means no file logging, which is only useful for tests
    and for --verbose one-off runs.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_level_value(level))

    # The root logger belongs to whatever else is in the process; our records
    # are fully handled here and must not be re-emitted unfiltered elsewhere.
    logger.propagate = False

    if device_id is None:
        device_id = identity.device_serial()
    context = ContextFilter(device_id=device_id, config_file=config_name)
    formatter = logging.Formatter(LOG_FORMAT)

    wanted = []
    if log_dir is not None:
        target = os.path.join(log_dir, 'log_%s.log' % config_name)
        wanted.append((FILE_HANDLER, target, lambda: _file_handler(target)))
    if graylog:
        endpoint = '%s:%s' % (graylog.get('server_address'), graylog.get('port'))
        wanted.append((GELF_HANDLER, endpoint, lambda: _gelf_handler(graylog)))
    if console:
        wanted.append((CONSOLE_HANDLER, 'stderr', logging.StreamHandler))

    existing = {handler.get_name(): handler for handler in logger.handlers}
    for name, settings, build in wanted:
        handler = existing.pop(name, None)
        if handler is not None and getattr(handler, 'solarian_settings', None) == settings:
            _attach(handler, formatter, context)
            continue
        if handler is not None:
            logger.removeHandler(handler)
            handler.close()
        handler = build()
        if handler is None:
            continue
        handler.set_name(name)
        handler.solarian_settings = settings
        _attach(handler, formatter, context)
        logger.addHandler(handler)

    for name, handler in existing.items():
        if name and name.startswith(LOGGER_NAME + '.'):
            logger.removeHandler(handler)
            handler.close()

    if not logger.handlers:
        # Without a handler logging falls back to lastResort, which writes to
        # stderr with no formatter and, more to the point, no redaction.
        placeholder = logging.NullHandler()
        placeholder.set_name(NULL_HANDLER)
        placeholder.solarian_settings = None
        logger.addHandler(placeholder)

    return logger
