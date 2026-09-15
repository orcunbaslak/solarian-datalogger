# -*- coding: UTF-8 -*-
"""Capture every driver's get_data() output against the fake Modbus master.

Run with a path argument to write a snapshot JSON:
    python tests/snapshot.py before.json
Run with two to diff them:
    python tests/snapshot.py --diff before.json after.json
"""

import io
import os
import re
import sys
import json
import inspect
import importlib
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # project root, for `drivers.*`
sys.path.insert(0, HERE)                    # this directory, for `fake_modbus`

import fake_modbus  # noqa: E402

DRIVERS = [
    "dcb_kernel_st0hs2425",
    "dcb_kernel_st0hs2425_single",
    "ekk_schneider_ion_7650",
    "ekk_socomec_dirisa10",
    "inv_abb_pvs800",
    "inv_abb_pvs980",
    "sensor_irradiation_akfen",
    "sensor_kippzonen_smp11",
    "sensor_lufft_ws600",
    "sensor_sevensolar_3SISTMB",
]

ISO_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z$")

# Base device definition. Transport is chosen from configuration now, so only
# the genuinely serial device carries serial settings — these match the values
# the pre-refactor RTU driver had hardcoded, keeping snapshots comparable.
DEVICE = {
    "name": "DEVICE_UNDER_TEST",
    "driver": None,
    "enabled": True,
    "measurement": "SPP_TEST",
    "slave_id": 1,
    "ip_address": "10.0.0.9",
    "port": 502,
}

SERIAL_DEVICES = {
    "ekk_socomec_dirisa10": {
        "serial_port": "/dev/ttyUSB0",
        "baudrate": 19200,
        "bytesize": 8,
        "parity": "N",
        "stopbits": 1,
        "xonxoff": 0,
    },
}


def device_for(name):
    device = dict(DEVICE, driver=name)
    device.update(SERIAL_DEVICES.get(name, {}))
    return device


def capture(only=None):
    """Sample every driver through the registry, against the fake transport.

    The registry resolves declarative drivers from solarian.drivers and falls
    back to legacy get_data() modules in drivers/, so this captures identical
    output on both sides of the migration.
    """
    fake_modbus.install_all()
    from solarian import driver as registry

    result = {}
    for name in (only or DRIVERS):
        fake_modbus.reset()
        registry._CACHE.pop(name, None)
        device = device_for(name)
        drv = registry.load(name)
        with contextlib.redirect_stderr(io.StringIO()):
            values = drv.read(device)
        master = fake_modbus.last_master()
        result[name] = {
            "version": drv.version_string(),
            "transport": type(master).__name__,
            "endpoint": [master.host, master.port],
            "modbus_calls": [list(c) for c in master.calls],
            "values": normalise(dict(values)),
        }
    return result


def normalise(values):
    """Replace the wall-clock Date with a marker so snapshots are stable."""
    out = {}
    for key, value in values.items():
        if key == "Date":
            assert ISO_MINUTE.match(value), "bad Date format: %r" % (value,)
            out[key] = "<utc-minute>"
        else:
            out[key] = value
    return out


def main(argv):
    """Capture a snapshot, or diff two of them.

    --only limits capture to named drivers so parallel work on different
    drivers does not interfere. --ignore-version skips the version string,
    which is expected to change when a driver is rewritten.
    """
    only = None
    ignore = set()
    args = []
    i = 0
    while i < len(argv):
        if argv[i] == "--only":
            only = argv[i + 1].split(",")
            i += 2
        elif argv[i] == "--ignore-version":
            ignore.add("version")
            i += 1
        else:
            args.append(argv[i])
            i += 1

    if args and args[0] == "--diff":
        with open(args[1]) as fh:
            before = json.load(fh)
        with open(args[2]) as fh:
            after = json.load(fh)
        names = only or sorted(set(before) & set(after))
        failures = []
        for name in names:
            b = {k: v for k, v in before.get(name, {}).items() if k not in ignore}
            a = {k: v for k, v in after.get(name, {}).items() if k not in ignore}
            if b != a:
                failures.append((name, b, a))
        if failures:
            print("SNAPSHOT MISMATCH in: %s" % ", ".join(n for n, _, _ in failures))
            for name, b, a in failures:
                for key in sorted(set(b) | set(a)):
                    if b.get(key) == a.get(key):
                        continue
                    print("  %s.%s" % (name, key))
                    if key == "values":
                        bv, av = b.get(key, {}), a.get(key, {})
                        for vk in sorted(set(bv) | set(av)):
                            if bv.get(vk) != av.get(vk):
                                print("      %-38s %r -> %r"
                                      % (vk, bv.get(vk), av.get(vk)))
                    else:
                        print("      %r -> %r" % (b.get(key), a.get(key)))
            return 1
        print("SNAPSHOTS IDENTICAL across %d driver(s): %s"
              % (len(names), ", ".join(names)))
        return 0

    data = capture(only)
    target = args[0]
    with open(target, "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    total = sum(len(d["values"]) for d in data.values())
    print("captured %d driver(s), %d fields -> %s" % (len(data), total, target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
