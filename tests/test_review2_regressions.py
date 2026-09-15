# -*- coding: UTF-8 -*-
"""Regressions for the six defects found in the second review, through 0655fc7.

Each test fails against that commit.
"""

import time
import logging

import pytest

from solarian import modbus as sol_modbus
from solarian import runner, cli
from solarian.config import ConfigError, load_devices
from solarian.decode import U16, Bitfield
from solarian.driver import Driver, Block


# --- 1. retries must genuinely reconnect ------------------------------------

class _CountingMaster:
    """Counts reconnections; every round trip fails like a reset connection."""

    def __init__(self, host=None, port=None, **kw):
        self.opens = 1          # constructed == connected
        _CountingMaster.last = self

    def set_timeout(self, value):
        pass

    def set_verbose(self, value):
        pass

    def execute(self, *a, **kw):
        raise IOError('connection reset by peer')

    def close(self):
        pass


def test_each_retry_opens_a_fresh_transport(monkeypatch):
    """A gateway that resets an idle connection must not burn the budget.

    modbus_tk's Master.open() is a no-op while _is_opened is True and nothing
    clears that flag on an I/O error, so without an explicit close() between
    attempts every retry reuses the same dead socket.
    """
    built = []

    def factory(host=None, port=None, **kw):
        master = _CountingMaster(host, port)
        built.append(master)
        return master

    monkeypatch.setattr('modbus_tk.modbus_tcp.TcpMaster', factory)
    monkeypatch.setattr(sol_modbus.Session, '_backoff_delay', lambda *a: 0)

    device = {'name': 'GW', 'ip_address': '10.0.0.9', 'port': 502, 'retries': 3}
    session = sol_modbus.Session(device, None, 'T')
    with pytest.raises(sol_modbus.DeviceError):
        session.read('b', sol_modbus.HOLDING, 0, 1)
    session.close()

    assert len(built) == 3, (
        'expected one fresh transport per attempt, got %d for 3 attempts'
        % len(built))


# --- 2. a broken optional config must not cost the data write ---------------

def _site(tmp_path, mqtt_body):
    for name in ('config', 'data', 'tmp', 'logs'):
        (tmp_path / name).mkdir()
    (tmp_path / 'config' / 'config.yml').write_text('devices: []\n')
    (tmp_path / 'config' / 'mqtt.yml').write_text(mqtt_body)
    return [
        '--config', 'config.yml', '--mqtt',
        '--config-dir', str(tmp_path / 'config'),
        '--data-dir', str(tmp_path / 'data'),
        '--temp-dir', str(tmp_path / 'tmp'),
        '--log-dir', str(tmp_path / 'logs'),
    ]


def test_a_broken_mqtt_config_still_polls_and_writes(tmp_path, monkeypatch):
    """An unquoted password in mqtt.yml used to mean the plant recorded nothing."""
    polled = {}

    def fake_poll(devices, **kw):
        polled['ran'] = True
        return []

    monkeypatch.setattr(runner, 'poll', fake_poll)
    # `port: not-a-number` fails validation.
    code = cli.main(_site(tmp_path, 'servers:\n  - {topic: T, ip_address: h,'
                                   ' port: nope, enabled: yes}\n'))

    assert polled.get('ran'), 'devices were never polled because of a bad sink config'
    assert code == cli.EXIT_CONFIG, 'the problem should still be reported'


# --- 3. queued devices deserve their turn -----------------------------------

class _SlowDriver:
    name, version = 'slow', '1'

    def __init__(self, delay):
        self.delay = delay

    def read(self, device):
        time.sleep(self.delay)
        return {'Device_Name': device['name']}

    def version_string(self):
        return 'slow v1'


def test_one_slow_device_does_not_fail_the_queue_behind_it(monkeypatch):
    """--workers 1 is the documented RS-485 mode; one slow meter cost the rest.

    M1 overruns its timeout, but M2 and M3 are instant and would run as soon as
    the slot freed. They used to be failed immediately as 'not polled'.
    """
    def fake_load(name):
        return _SlowDriver(0.6 if name == 'slow_one' else 0.0)

    monkeypatch.setattr(runner.driver_registry, 'load', fake_load)

    devices = [
        {'name': 'M1', 'driver': 'slow_one', 'enabled': True},
        {'name': 'M2', 'driver': 'fast', 'enabled': True},
        {'name': 'M3', 'driver': 'fast', 'enabled': True},
    ]
    results = runner.poll(devices, max_workers=1, per_device_timeout=0.2)

    by_name = {r.device_name: r for r in results}
    assert not by_name['M1'].ok, 'M1 exceeded its timeout and should be failed'
    assert by_name['M2'].ok, 'M2 was abandoned though a slot freed up for it'
    assert by_name['M3'].ok, 'M3 was abandoned though a slot freed up for it'


# --- 4. sink construction is guarded ----------------------------------------

def test_an_unwritable_data_dir_does_not_abort_the_run(tmp_path, monkeypatch):
    """JsonFileSink.__init__ calls makedirs/stat, outside the old try block."""
    for name in ('config', 'data', 'tmp', 'logs'):
        (tmp_path / name).mkdir()
    (tmp_path / 'config' / 'config.yml').write_text('devices: []\n')

    from solarian import sinks

    class Exploding(sinks.JsonFileSink):
        def __init__(self, *a, **kw):
            raise OSError('read-only file system')

    monkeypatch.setattr(sinks, 'JsonFileSink', Exploding)

    # Must not raise out of main().
    code = cli.main([
        '--config', 'config.yml',
        '--config-dir', str(tmp_path / 'config'),
        '--data-dir', str(tmp_path / 'data'),
        '--temp-dir', str(tmp_path / 'tmp'),
        '--log-dir', str(tmp_path / 'logs'),
    ])
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL, cli.EXIT_CONFIG)


# --- 5. integer settings are range-checked ----------------------------------

@pytest.mark.parametrize('key,bad', [
    ('port', 0), ('port', 70000),
    ('slave_id', 0), ('slave_id', -1), ('slave_id', 300),
    ('baudrate', 0), ('bytesize', 0), ('stopbits', 0), ('xonxoff', 5),
])
def test_out_of_range_integers_are_rejected(tmp_path, key, bad):
    path = tmp_path / 'c.yml'
    path.write_text(
        'devices:\n'
        '  - name: A\n    driver: d\n    enabled: yes\n    measurement: M\n'
        '    slave_id: 1\n    ip_address: 10.0.0.1\n'
        '    %s: %s\n' % (key, bad))
    with pytest.raises(ConfigError) as exc:
        load_devices(str(path))
    assert key in str(exc.value)


def test_a_valid_device_still_loads(tmp_path):
    path = tmp_path / 'c.yml'
    path.write_text(
        'devices:\n'
        '  - name: A\n    driver: d\n    enabled: yes\n    measurement: M\n'
        '    slave_id: 247\n    ip_address: 10.0.0.1\n    port: 65535\n')
    assert load_devices(str(path))[0]['slave_id'] == 247


# --- 6. duplicate emitted names are rejected --------------------------------

def test_two_fields_emitting_one_name_are_rejected():
    """A duplicate would silently overwrite the earlier series."""
    with pytest.raises(ValueError) as exc:
        Driver('D', '1', [Block('b', sol_modbus.HOLDING, 0, 4,
                                [U16(0, 'Power'), U16(1, 'Power')])])
    assert 'Power' in str(exc.value)


def test_a_bitfield_colliding_across_blocks_is_rejected():
    """inv_abb_pvs980 shares a prefix across blocks; only a driver-wide check sees it."""
    with pytest.raises(ValueError) as exc:
        Driver('D', '1', [
            Block('a', sol_modbus.HOLDING, 0, 2, [Bitfield(0, 'S_', {0: 'Fault'})]),
            Block('b', sol_modbus.HOLDING, 9, 2, [Bitfield(0, 'S_', {0: 'Fault'})]),
        ])
    assert 'S_Fault' in str(exc.value)


def test_a_bit_position_outside_a_register_is_rejected():
    """Bit 16 of a 16-bit register would always read 0.0."""
    with pytest.raises(ValueError) as exc:
        Block('b', sol_modbus.HOLDING, 0, 2, [Bitfield(0, 'S_', {16: 'Nope'})])
    assert '16 bits' in str(exc.value)
