# -*- coding: UTF-8 -*-
"""Polling behaviour: isolation, ordering, and honouring `enabled`."""

import time

import pytest

from solarian import runner
from solarian.modbus import DeviceError


class StubDriver:
    """A driver that returns, raises, or stalls, on command."""

    def __init__(self, name, behaviour='ok', delay=0.0):
        self.name = name
        self.version = '1'
        self.behaviour = behaviour
        self.delay = delay

    def read(self, device):
        if self.delay:
            time.sleep(self.delay)
        if self.behaviour == 'raise':
            raise DeviceError('unreachable', device=device['name'])
        if self.behaviour == 'boom':
            raise RuntimeError('driver bug')
        return {'Device_Name': device['name'], 'Value': 1.0}

    def version_string(self):
        return '%s v%s' % (self.name, self.version)


@pytest.fixture
def stub_registry(monkeypatch):
    """Route driver lookups to stubs named by the device's `driver` key."""
    behaviours = {}

    def fake_load(name):
        behaviour, delay = behaviours.get(name, ('ok', 0.0))
        return StubDriver(name, behaviour, delay)

    monkeypatch.setattr(runner.driver_registry, 'load', fake_load)
    return behaviours


def device(name, driver='d_ok', enabled=True):
    return {'name': name, 'driver': driver, 'enabled': enabled,
            'measurement': 'M', 'slave_id': 1,
            'ip_address': '10.0.0.1', 'port': 502}


def test_one_failing_device_does_not_affect_the_others(stub_registry):
    """The whole point of per-device isolation."""
    stub_registry['d_bad'] = ('raise', 0.0)
    results = runner.poll([device('A'), device('B', 'd_bad'), device('C')])

    by_name = {r.device_name: r for r in results}
    assert by_name['A'].ok and by_name['C'].ok
    assert not by_name['B'].ok
    assert isinstance(by_name['B'].error, DeviceError)
    assert by_name['A'].values['Value'] == 1.0


def test_an_unexpected_driver_bug_is_contained_too(stub_registry):
    """A crash in driver code must not take the run down."""
    stub_registry['d_boom'] = ('boom', 0.0)
    results = runner.poll([device('A'), device('B', 'd_boom')])
    assert results[0].ok
    assert not results[1].ok
    assert isinstance(results[1].error, RuntimeError)


def test_results_follow_configuration_order_not_completion_order(stub_registry):
    """Readings go into a file and onto MQTT; the order must be deterministic."""
    stub_registry['d_slow'] = ('ok', 0.25)
    devices = [device('SLOW', 'd_slow'), device('FAST1'), device('FAST2')]
    results = runner.poll(devices, max_workers=3)
    assert [r.device_name for r in results] == ['SLOW', 'FAST1', 'FAST2']


def test_disabled_devices_are_not_polled_and_not_reported(stub_registry):
    results = runner.poll([device('ON'), device('OFF', enabled=False)])
    assert [r.device_name for r in results] == ['ON']


def test_concurrency_actually_overlaps(stub_registry):
    """Four 0.2s devices in parallel must finish far faster than serially."""
    stub_registry['d_slow'] = ('ok', 0.2)
    devices = [device('D%d' % i, 'd_slow') for i in range(4)]

    started = time.time()
    results = runner.poll(devices, max_workers=4)
    parallel = time.time() - started

    assert all(r.ok for r in results)
    assert parallel < 0.6, 'expected overlap, took %.2fs' % parallel


def test_single_worker_is_strictly_sequential(stub_registry):
    """max_workers=1 is the RS-485 mode: one transaction on the wire at a time."""
    stub_registry['d_slow'] = ('ok', 0.1)
    devices = [device('D%d' % i, 'd_slow') for i in range(3)]

    started = time.time()
    results = runner.poll(devices, max_workers=1)
    elapsed = time.time() - started

    assert [r.device_name for r in results] == ['D0', 'D1', 'D2']
    assert elapsed >= 0.28, 'expected serialised reads, took %.2fs' % elapsed


def test_readings_returns_only_successful_values(stub_registry):
    stub_registry['d_bad'] = ('raise', 0.0)
    results = runner.poll([device('A'), device('B', 'd_bad'), device('C')])
    values = runner.readings(results)
    assert [v['Device_Name'] for v in values] == ['A', 'C']


def test_empty_and_all_disabled_inputs(stub_registry):
    assert runner.poll([]) == []
    assert runner.poll([device('X', enabled=False)]) == []
