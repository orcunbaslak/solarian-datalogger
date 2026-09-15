# -*- coding: UTF-8 -*-
"""Regressions for the five defects found in review of d9130c8.

Each test fails against the code as it was reviewed. They are kept together so
the reasoning behind each one stays next to it.
"""

import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import pytest

from modbus_tk import modbus

from solarian import modbus as sol_modbus
from solarian import logging_setup, sinks
from solarian.config import ALLOWED_MQTT_KEYS


# --- 1. concurrency ---------------------------------------------------------

class _Query:
    def build_request(self, pdu, slave):
        return b''

    def parse_response(self, response):
        return b'\x00\x00'


class SlowMaster(modbus.Master):
    """A real modbus_tk Master whose round trip blocks."""

    DELAY = 0.4

    def __init__(self, *a, **kw):
        super().__init__(timeout_in_sec=5.0)
        self._is_opened = True

    def _do_open(self):
        pass

    def _do_close(self):
        pass

    def _send(self, buf):
        pass

    def _recv(self, expected_length):
        time.sleep(self.DELAY)
        return b''

    def _make_query(self):
        return _Query()

    def set_verbose(self, value):
        pass


def test_modbus_tk_lock_is_process_wide_not_per_instance():
    """Pins the library behaviour the fix depends on.

    modbus_tk builds one RLock at decoration time and shares it across every
    Master in the process. If a future version changes that, the reasoning
    behind passing threadsafe=False should be revisited.
    """
    locks = [c.cell_contents for c in modbus.Master.execute.__closure__
             if hasattr(c.cell_contents, 'acquire')]
    assert len(locks) == 1, 'expected exactly one shared lock, got %r' % locks


def test_sessions_poll_concurrently_through_a_real_master(monkeypatch):
    """The concurrency guarantee, measured through Session rather than a stub.

    The original test used a driver stub that called time.sleep and never
    touched modbus_tk, so it passed even while every read in the fleet was
    serialised on the library's shared lock.
    """
    monkeypatch.setattr('modbus_tk.modbus_tcp.TcpMaster', SlowMaster)

    def read_one(index):
        device = {'name': 'D%d' % index, 'slave_id': 1,
                  'ip_address': '10.0.0.%d' % index, 'port': 502, 'retries': 1}
        with sol_modbus.Session(device, None, 'T') as session:
            try:
                session.read('b', sol_modbus.HOLDING, 0, 1)
            except sol_modbus.DeviceError:
                pass  # the fake response fails to parse; timing is the point

    started = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(read_one, range(4)))
    elapsed = time.time() - started

    serial_time = SlowMaster.DELAY * 4
    assert elapsed < serial_time * 0.6, (
        'reads serialised: %.2fs for 4 devices of %.2fs each'
        % (elapsed, SlowMaster.DELAY))


def test_devices_sharing_a_serial_bus_are_serialised():
    """RS-485 devices share one pair of wires and must not interleave.

    modbus_tk's global lock used to provide this incidentally; disabling it
    means the guarantee has to be explicit.
    """
    a = sol_modbus.Session({'name': 'A', 'serial_port': '/dev/ttyUSB9'}, None, 'T')
    b = sol_modbus.Session({'name': 'B', 'serial_port': '/dev/ttyUSB9'}, None, 'T')
    c = sol_modbus.Session({'name': 'C', 'serial_port': '/dev/ttyUSB8'}, None, 'T')
    tcp = sol_modbus.Session({'name': 'D', 'ip_address': '10.0.0.1'}, None, 'T')

    assert a._bus_lock is b._bus_lock, 'same port must share one lock'
    assert a._bus_lock is not c._bus_lock, 'different ports must not share'
    assert tcp._bus_lock is None, 'TCP devices need no bus lock'


# --- 2. traceback redaction -------------------------------------------------

def test_a_secret_in_a_traceback_does_not_reach_the_log_file(tmp_path):
    """cli.main calls log.exception around MQTT; tracebacks carry the secret.

    Handler filters run before the formatter, so redacting record.exc_text
    alone was a no-op for the first handler.
    """
    logging_setup.configure(level='DEBUG', log_dir=str(tmp_path),
                            config_name='t_exc')
    try:
        raise RuntimeError('connect failed for password=hunter2')
    except RuntimeError:
        logging.getLogger('solarian.test').exception('sink failed')
    logging.shutdown()

    written = ''.join(p.read_text() for p in tmp_path.glob('*.log'))
    assert 'Traceback' in written, 'the traceback should still be logged'
    assert 'hunter2' not in written, 'secret leaked through the traceback'


# --- 3. timestamp -----------------------------------------------------------

def test_file_stamp_accepts_what_the_cli_actually_passes():
    """A float fell through to the warning path on every single run."""
    moment = datetime(2026, 9, 15, 10, 30)
    assert sinks._file_stamp({'timestamp': moment}) == '202609151030'
    # time.time() is what cli.main used to pass; it must not fall through to
    # the "unusable timestamp" path.
    assert sinks._file_stamp({'timestamp': moment.timestamp()}) == '202609151030'


def test_a_run_logs_no_unusable_timestamp_warning(tmp_path, caplog):
    """The warning fired once a minute at the default level, filling the log."""
    from solarian import cli
    for name in ('config', 'data', 'tmp', 'logs'):
        (tmp_path / name).mkdir()
    (tmp_path / 'config' / 'config.yml').write_text(
        'devices: []\n')

    with caplog.at_level(logging.WARNING):
        cli.main(['--config', 'config.yml',
                  '--config-dir', str(tmp_path / 'config'),
                  '--data-dir', str(tmp_path / 'data'),
                  '--temp-dir', str(tmp_path / 'tmp'),
                  '--log-dir', str(tmp_path / 'logs')])

    assert 'unusable timestamp' not in caplog.text


# --- 4. serial port leak ----------------------------------------------------

def test_a_failed_rtu_master_closes_the_serial_port(monkeypatch):
    """__enter__ raising means __exit__ never runs, so close() never happens.

    The port would stay held until garbage collection, potentially locking it
    against the next cron run.
    """
    opened = []

    class FakeSerial:
        def __init__(self, port=None, **kw):
            self.port = port
            self.is_open = True
            opened.append(self)

        def close(self):
            self.is_open = False

    def exploding_rtu_master(serial_obj):
        raise IOError('cannot configure the port')

    monkeypatch.setattr('serial.Serial', FakeSerial)
    monkeypatch.setattr('modbus_tk.modbus_rtu.RtuMaster', exploding_rtu_master)

    session = sol_modbus.Session({'name': 'M', 'serial_port': '/dev/ttyUSB0'},
                                 None, 'T')
    with pytest.raises(sol_modbus.Unreachable):
        session.open()

    assert opened, 'the port was never opened'
    assert not opened[0].is_open, 'serial port left open after a failed open()'


# --- 5. client_id -----------------------------------------------------------

def test_client_id_is_configurable():
    """MqttSink reads it, so the validator must not reject it."""
    assert 'client_id' in ALLOWED_MQTT_KEYS
