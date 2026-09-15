# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Modbus transport, connection lifetime and retry policy.

Everything here is a cross-cutting concern that used to be copied into each
driver, which is why retry budgets had drifted to 3 in some devices and 10 in
others, with sleeps of 0.5s, 3s and a random 0-5s. A driver now says only
*which* registers it wants; how hard to try for them is decided in one place
and is configurable per device.
"""

import time
import random
import logging
import threading

import modbus_tk.defines as cst

log = logging.getLogger('solarian.modbus')

# Function codes, re-exported so drivers never import modbus_tk directly.
HOLDING = cst.READ_HOLDING_REGISTERS
INPUT = cst.READ_INPUT_REGISTERS
COILS = cst.READ_COILS
DISCRETE = cst.READ_DISCRETE_INPUTS

FUNCTION_NAMES = {
    HOLDING: 'holding',
    INPUT: 'input',
    COILS: 'coils',
    DISCRETE: 'discrete',
}

DEFAULTS = {
    'timeout': 3.0,
    'retries': 3,
    'backoff': 0.5,
    'max_backoff': 5.0,
    'baudrate': 19200,
    'bytesize': 8,
    'parity': 'N',
    'stopbits': 1,
    'xonxoff': 0,
}


# One lock per serial port. modbus_tk's own @threadsafe_function decorator
# builds a single RLock at decoration time that every Master in the process
# shares, and holds it across the whole blocking round trip -- so leaving it
# enabled serialises the entire fleet and defeats concurrent polling entirely
# (measured: four 1s devices took 4.02s with it, 1.01s without). Each Session
# owns its own Master and is driven by exactly one thread, so the lock buys
# nothing for TCP. It did, however, incidentally protect an RS-485 bus, where
# devices genuinely share one pair of wires. These locks restore that
# protection precisely: transactions on the same serial port serialise, while
# TCP devices run in parallel.
_BUS_LOCKS = {}
_BUS_LOCKS_GUARD = threading.Lock()


def bus_lock(serial_port):
    """The lock guarding one physical serial bus."""
    with _BUS_LOCKS_GUARD:
        return _BUS_LOCKS.setdefault(serial_port, threading.RLock())


class DeviceError(Exception):
    """A device could not be sampled.

    Carries structured context so callers can alarm on the failure instead of
    pattern-matching log strings.
    """

    def __init__(self, message, device=None, endpoint=None, block=None, attempts=None):
        super().__init__(message)
        self.device = device
        self.endpoint = endpoint
        self.block = block
        self.attempts = attempts

    def __str__(self):
        bits = [Exception.__str__(self)]
        for label, value in (('device', self.device), ('endpoint', self.endpoint),
                             ('block', self.block), ('attempts', self.attempts)):
            if value is not None:
                bits.append('%s=%s' % (label, value))
        return ' '.join(bits)


class Unreachable(DeviceError):
    """The transport could not be established at all."""


def resolve(device, driver_defaults, key):
    """Setting precedence: per-device config, then driver, then framework."""
    for source in (device, driver_defaults):
        if source:
            value = source.get(key)
            if value is not None:
                return value
    return DEFAULTS[key]


class Session:
    """One open connection to a device, with retrying reads.

    Used as a context manager so the transport is closed exactly once, whether
    the reads succeed or give up:

        with Session(device, driver_defaults, 'ABB_PVS800') as session:
            blocks = session.read_blocks(driver.blocks)
    """

    def __init__(self, device, driver_defaults=None, driver_name=''):
        self.device = device
        self.driver_name = driver_name
        self.name = device.get('name', '<unnamed>')
        self.slave_id = device.get('slave_id', 1)

        get = lambda key: resolve(device, driver_defaults, key)
        self.timeout = float(get('timeout'))
        self.retries = max(1, int(get('retries')))
        self.backoff = float(get('backoff'))
        self.max_backoff = float(get('max_backoff'))

        self.serial_port = device.get('serial_port')
        self.is_serial = bool(self.serial_port)
        if self.is_serial:
            self.endpoint = '%s@%s' % (self.serial_port, get('baudrate'))
        else:
            self.endpoint = '%s:%s' % (device.get('ip_address'), device.get('port'))

        self._get = get
        self._master = None
        self._serial = None
        # Only a shared physical bus needs mutual exclusion; see bus_lock().
        self._bus_lock = bus_lock(self.serial_port) if self.is_serial else None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    # -- transport -----------------------------------------------------------

    def open(self):
        if self._master is not None:
            return self._master
        self._master = self._open_serial() if self.is_serial else self._open_tcp()
        self._master.set_timeout(self.timeout)
        self._master.set_verbose(log.isEnabledFor(logging.DEBUG))
        log.debug('%s: connected to %s', self.name, self.endpoint)
        return self._master

    def _open_tcp(self):
        from modbus_tk import modbus_tcp
        address = self.device.get('ip_address')
        if not address:
            raise Unreachable('device declares neither ip_address nor serial_port',
                              device=self.name)
        try:
            return modbus_tcp.TcpMaster(host=address,
                                        port=int(self.device.get('port') or 502))
        except Exception as exc:
            raise Unreachable('cannot open TCP transport: %s' % exc,
                              device=self.name, endpoint=self.endpoint) from exc

    def _open_serial(self):
        import serial
        from modbus_tk import modbus_rtu
        try:
            self._serial = serial.Serial(
                port=self.serial_port,
                baudrate=int(self._get('baudrate')),
                bytesize=int(self._get('bytesize')),
                parity=self._get('parity'),
                stopbits=int(self._get('stopbits')),
                xonxoff=int(self._get('xonxoff')),
            )
            return modbus_rtu.RtuMaster(self._serial)
        except Exception as exc:
            # serial.Serial opens the port on construction. If RtuMaster then
            # raises, __enter__ never completes, so __exit__ -- and therefore
            # close() -- never runs, and the port would stay held until the
            # object was collected. On a Pi polling every minute that can lock
            # the port against the next run.
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    log.debug('%s: could not close serial port after a failed '
                              'RtuMaster construction', self.name)
                self._serial = None
            raise Unreachable('cannot open serial transport: %s' % exc,
                              device=self.name, endpoint=self.endpoint) from exc

    def close(self):
        """Close transport handles. Safe to call repeatedly."""
        for handle in (self._master, self._serial):
            if handle is None:
                continue
            try:
                handle.close()
            except Exception as exc:
                log.debug('%s: error closing transport: %s', self.name, exc)
        self._master = None
        self._serial = None

    # -- reads ---------------------------------------------------------------

    def _backoff_delay(self, attempt):
        """Exponential backoff, jittered and capped.

        Jitter matters when many devices sit behind one gateway: without it
        every retry in the fleet lands on the same instant.
        """
        ceiling = min(self.backoff * (2 ** attempt), self.max_backoff)
        return random.uniform(ceiling / 2.0, ceiling)

    def read(self, block_name, function, address, count):
        """Read one register block, retrying per the configured budget.

        Raises DeviceError once the budget is spent, so a partial or short read
        can never be mistaken for a real measurement.
        """
        master = self.open()
        problem = None

        for attempt in range(self.retries):
            try:
                registers = self._execute(master, function, address, count)
            except Exception as exc:
                problem = exc
            else:
                if registers is not None and len(registers) >= count:
                    log.debug('%s: block %s read on attempt %d/%d',
                              self.name, block_name, attempt + 1, self.retries)
                    return registers
                problem = 'short read, expected %d registers got %d' % (
                    count, 0 if registers is None else len(registers))

            log.warning('%s (%s): block %s attempt %d/%d failed: %s',
                        self.name, self.endpoint, block_name,
                        attempt + 1, self.retries, problem)
            if attempt + 1 < self.retries:
                time.sleep(self._backoff_delay(attempt))

        raise DeviceError('block could not be read: %s' % problem,
                          device=self.name, endpoint=self.endpoint,
                          block=block_name, attempts=self.retries)

    def _execute(self, master, function, address, count):
        """Run one transaction, guarding a shared serial bus if there is one.

        `threadsafe=False` disables modbus_tk's process-wide lock; see the note
        on bus_lock() for why that lock has to go and what replaces it.
        """
        if self._bus_lock is None:
            return master.execute(self.slave_id, function, address, count,
                                  threadsafe=False)
        with self._bus_lock:
            return master.execute(self.slave_id, function, address, count,
                                  threadsafe=False)

    def read_blocks(self, blocks):
        """Read every block in declaration order.

        Returns name -> registers. Raises on the first unreadable block, so a
        device is either sampled completely or reported as failed.
        """
        return {b.name: self.read(b.name, b.function, b.address, b.count)
                for b in blocks}
