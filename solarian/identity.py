# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Who this logger is: the Raspberry Pi's CPU serial number.

The serial ends up in every data filename and on every log line, which is the
only way an operator can tell which of a fleet of Pis produced a file. That
makes its exact spelling part of the data format, not an implementation
detail, so the fallbacks below are deliberately preserved:

    '00000000'   /proc/cpuinfo was readable but had no Serial line
    'ERROR0000'  /proc/cpuinfo could not be read at all

Both already appear in archived filenames; changing them would split a plant's
history across two identities.

The value cannot change while the process runs, so it is read once. The old
implementation reopened /proc/cpuinfo on every call — four or more times per
run, once per filename component and once per log filter — and swallowed
everything including KeyboardInterrupt with a bare ``except``.
"""

import logging

from functools import lru_cache

log = logging.getLogger('solarian.identity')

CPUINFO_PATH = '/proc/cpuinfo'
NO_SERIAL = '00000000'
UNREADABLE = 'ERROR0000'

# The Pi reports a 16 hex digit serial whose top half is zero padding. The old
# code sliced line[18:26], i.e. the low 8 digits, and those 8 digits are what
# historical filenames contain, so the width is kept even though the parsing
# is not positional any more.
SERIAL_DIGITS = 8


@lru_cache(maxsize=None)
def device_serial(path=CPUINFO_PATH):
    """Return this machine's serial, reading /proc/cpuinfo at most once.

    The path argument exists so tests can point at a fixture; production code
    calls this with no arguments.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            serial = _find_serial(handle)
    except OSError as exc:
        # Not a Pi, or /proc is not mounted. Both are normal on a developer
        # machine, so this is not an error the operator needs to see.
        log.debug('cannot read %s: %s', path, exc)
        return UNREADABLE

    if not serial:
        log.debug('%s has no Serial line', path)
        return NO_SERIAL
    return serial


def _find_serial(lines):
    """Pull the Serial field out of cpuinfo-style ``key : value`` lines."""
    for line in lines:
        key, separator, value = line.partition(':')
        if not separator or key.strip() != 'Serial':
            continue
        value = value.strip()
        if value:
            return value[-SERIAL_DIGITS:]
    return ''


def reset_cache():
    """Forget the cached serial. For tests; nothing in production needs it."""
    device_serial.cache_clear()
