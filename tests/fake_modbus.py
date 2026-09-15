# -*- coding: UTF-8 -*-
"""Deterministic fake Modbus master used to characterise driver output.

The drivers do ``from modbus_tk import modbus_tcp`` and then call
``modbus_tcp.TcpMaster(...)`` at run time, so patching the attribute on the
module object is enough to intercept every driver without touching them.
"""

import hashlib


def canned_registers(address, count):
    """Stable pseudo-random uint16 values for a given (address, count) read.

    Deterministic across runs and machines so snapshots stay comparable.
    Values deliberately span the full uint16 range so that signed/unsigned
    conversion paths are exercised.
    """
    out = []
    for i in range(count):
        seed = "%d:%d:%d" % (address, count, i)
        digest = hashlib.sha256(seed.encode()).digest()
        out.append((digest[0] << 8 | digest[1]) & 0xFFFF)
    return tuple(out)


class FakeTcpMaster:
    """Stands in for modbus_tk.modbus_tcp.TcpMaster."""

    instances = []

    def __init__(self, host=None, port=None, **kwargs):
        self.host = host
        self.port = port
        self.timeout = None
        self.verbose = False
        self.closed = 0
        self.calls = []
        FakeTcpMaster.instances.append(self)

    def set_timeout(self, value, *a, **kw):
        self.timeout = value

    def set_verbose(self, value, *a, **kw):
        self.verbose = value

    def execute(self, slave_id, function_code, address, count, *a, **kw):
        self.calls.append((slave_id, function_code, address, count))
        return canned_registers(address, count)

    def close(self):
        self.closed += 1


def install():
    """Patch the fake over the real TcpMaster. Returns the module patched."""
    from modbus_tk import modbus_tcp
    modbus_tcp.TcpMaster = FakeTcpMaster
    return modbus_tcp


class FakeSerial:
    """Stands in for serial.Serial so RTU drivers need no hardware."""

    instances = []

    def __init__(self, port=None, baudrate=None, **kwargs):
        self.port = port
        self.baudrate = baudrate
        self.settings = dict(kwargs)
        self.is_open = True
        FakeSerial.instances.append(self)

    def close(self):
        self.is_open = False


class FakeRtuMaster(FakeTcpMaster):
    """Stands in for modbus_tk.modbus_rtu.RtuMaster."""

    instances = []

    def __init__(self, serial_obj=None, *a, **kw):
        self.serial = serial_obj
        self.host = getattr(serial_obj, "port", None)
        self.port = getattr(serial_obj, "baudrate", None)
        self.timeout = None
        self.verbose = False
        self.closed = 0
        self.calls = []
        FakeRtuMaster.instances.append(self)


def install_all():
    """Patch TCP, RTU and pyserial. Returns nothing; call before importing drivers."""
    import serial
    from modbus_tk import modbus_tcp, modbus_rtu

    modbus_tcp.TcpMaster = FakeTcpMaster
    modbus_rtu.RtuMaster = FakeRtuMaster
    serial.Serial = FakeSerial


def reset():
    FakeTcpMaster.instances = []
    FakeRtuMaster.instances = []
    FakeSerial.instances = []


def last_master():
    """The master most recently constructed, whichever transport it used."""
    both = FakeTcpMaster.instances + FakeRtuMaster.instances
    assert both, "no modbus master was constructed"
    return both[-1]
