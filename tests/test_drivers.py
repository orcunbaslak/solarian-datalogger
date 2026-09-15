# -*- coding: UTF-8 -*-
"""Every driver must keep producing exactly what it produced before.

tests/golden_drivers.json was captured from the original hand-written drivers,
before the declarative rewrite. It pins 392 decoded values across 10 devices
against a deterministic fake transport. If a register map, a divisor or a bit
index is ever disturbed, this test names the field that moved.

Driver version strings are excluded: those are meant to change.
"""

import io
import os
import json
import contextlib

import pytest

import fake_modbus
from snapshot import DRIVERS, device_for, normalise

from solarian import driver as registry

GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'golden_drivers.json')

with open(GOLDEN_PATH) as _fh:
    GOLDEN = json.load(_fh)


@pytest.fixture(scope='module', autouse=True)
def fake_transport():
    fake_modbus.install_all()


def sample(name):
    fake_modbus.reset()
    registry._CACHE.pop(name, None)
    drv = registry.load(name)
    with contextlib.redirect_stderr(io.StringIO()):
        values = drv.read(device_for(name))
    return drv, values, fake_modbus.last_master()


@pytest.mark.parametrize('name', DRIVERS)
def test_driver_output_matches_golden(name):
    expected = GOLDEN[name]
    _, values, _ = sample(name)
    actual = normalise(dict(values))

    missing = sorted(set(expected['values']) - set(actual))
    added = sorted(set(actual) - set(expected['values']))
    assert not missing, '%s stopped emitting: %s' % (name, missing)
    assert not added, '%s started emitting: %s' % (name, added)

    for field, want in expected['values'].items():
        assert actual[field] == want, (
            '%s.%s changed: %r -> %r' % (name, field, want, actual[field]))


@pytest.mark.parametrize('name', DRIVERS)
def test_driver_reads_the_same_registers(name):
    """The register blocks requested must not drift."""
    _, _, master = sample(name)
    assert [list(c) for c in master.calls] == GOLDEN[name]['modbus_calls']


@pytest.mark.parametrize('name', DRIVERS)
def test_driver_uses_the_same_transport(name):
    """A TCP device must not silently become serial, or the reverse."""
    _, _, master = sample(name)
    assert type(master).__name__ == GOLDEN[name]['transport']
    assert [master.host, master.port] == GOLDEN[name]['endpoint']


def test_every_shipped_driver_is_covered():
    """A new driver must be added to the snapshot set, not quietly untested."""
    shipped = set(registry.available())
    assert shipped == set(DRIVERS), (
        'drivers not covered by the golden snapshot: %s'
        % sorted(shipped.symmetric_difference(DRIVERS)))


def test_all_drivers_are_declarative():
    """No driver should still be going through the legacy adapter."""
    for name in DRIVERS:
        drv = registry.load(name)
        assert isinstance(drv, registry.Driver), (
            '%s is still a %s' % (name, type(drv).__name__))
