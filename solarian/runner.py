# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Polling: turn a list of configured devices into a list of readings.

The old datalogger walked the device list in a single loop and sampled each
device to completion before touching the next one, so one sick device delayed
every device behind it. inv_abb_pvs980 read four register blocks with
retries=10 and a 3 s timeout: an unreachable inverter could hold the run for
roughly 280 seconds while cron started another run every minute, and the runs
piled up on top of each other.

Sampling is I/O bound -- nearly all of that time is a thread parked on a
socket read, and modbus_tk releases the GIL while it waits -- so devices are
polled on a small thread pool instead. Threads rather than processes: the work
is waiting, not computing, and a process pool would have to ship the driver
declarations across a pickle boundary for no gain.

Two properties everything downstream depends on are guaranteed here: results
come back in configuration order no matter who finishes first (the readings go
into a file and onto MQTT, and a fleet-wide diff of two runs should not light
up because two inverters swapped places), and a device's failure is recorded
rather than propagated.
"""

import time
import logging

from dataclasses import dataclass
from concurrent.futures import (ThreadPoolExecutor, wait,
                                ALL_COMPLETED, FIRST_COMPLETED)

from solarian import modbus
from solarian import driver as driver_registry

log = logging.getLogger('solarian.runner')

# How often the collector re-examines devices that are still running while a
# per-device timeout is in force: responsive enough for a one-minute cadence,
# lazy enough not to burn a core spinning.
_TIMEOUT_TICK = 0.25


@dataclass
class Result:
    """The outcome of sampling one device: values or an error, never both."""

    device_name: str
    driver_name: str
    values: dict | None = None
    error: Exception | None = None
    duration: float = 0.0

    @property
    def ok(self):
        """True when the device was sampled completely.

        A driver either returns a full set of values or raises, so a partial
        read can never be mistaken here for a successful one.
        """
        return self.error is None and self.values is not None

    def __str__(self):
        state = 'ok' if self.ok else 'failed: %s' % (self.error,)
        return '%s (%s) %s in %.2fs' % (self.device_name, self.driver_name,
                                        state, self.duration)


def poll(devices, max_workers=4, per_device_timeout=None):
    """Sample every enabled device and return one Result per device.

    `devices` is the list of device mappings from the configuration file.
    Devices whose `enabled` key is false are not polled and do not appear in
    the returned list; everything else yields exactly one Result, in the order
    the devices were given, whatever order they actually finished in.

    A device that fails is reported through its own Result.error and never
    affects another device's reading.

    `max_workers=1` polls strictly one device at a time, in configuration
    order -- identical behaviour to the old sequential loop. Use it for RS-485:
    every device on the bus shares one pair of wires, so two transactions in
    flight at once interleave their frames and corrupt both. A TCP fleet, and
    a mixed fleet where the serial devices sit behind their own logger
    process, can use the default.

    `per_device_timeout` bounds *attribution*, not the worker: it decides how
    long a device may hold a slot before it is recorded as failed and the
    collector stops waiting on it. It cannot interrupt the read itself, because
    a thread blocked in a socket read cannot be cancelled from outside.

    Devices still queued are never given up on. They wait for a slot and get
    their own timeout once they start. An earlier version abandoned the whole
    remaining queue as soon as one device stalled, and a later one bounded the
    wait by a budget derived from the timeouts -- but a device that overruns
    holds its worker for its real duration, so it ate the shared budget and
    starved the queue anyway. Both cost the devices behind a slow meter on an
    RS-485 bus, where --workers 1 means everything is behind it. What actually
    bounds a run is each device's own `timeout` x `retries`, which is what to
    turn down if a cycle overruns.

    `per_device_timeout` (seconds, None to wait indefinitely) bounds how long
    the *caller* waits for one device, not how long the worker lives: a thread
    blocked in a socket read cannot be interrupted from outside. The abandoned
    worker still finishes on its own, because modbus.Session caps every read
    with its own timeout and retry budget, but it keeps its slot in the pool
    until it does. Treat this as a backstop for a device whose configured
    timeout budget is unreasonable, not as the primary control -- the honest
    fix for a slow device is a smaller `retries`/`timeout` in its config.
    """
    selected = [device for device in devices if device.get('enabled', True)]
    skipped = len(devices) - len(selected)
    if not selected:
        log.info('nothing to poll: 0 of %d device(s) are enabled', len(devices))
        return []

    workers = max(1, min(int(max_workers or 1), len(selected)))
    bounded = per_device_timeout is not None and per_device_timeout > 0
    began = time.monotonic()

    results = [None] * len(selected)
    # Written by the workers, read by the collector. A dict item assignment is
    # atomic under the GIL, so no lock is needed for a start timestamp.
    started = {}

    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='solarian-poll')
    try:
        pending = {pool.submit(_sample, device, index, started): index
                   for index, device in enumerate(selected)}
        abandoned = []

        while pending:
            if bounded:
                wait(list(pending), timeout=_TIMEOUT_TICK,
                     return_when=FIRST_COMPLETED)
            else:
                wait(list(pending), return_when=ALL_COMPLETED)

            now = time.monotonic()
            for future in list(pending):
                index = pending[future]
                if future.done():
                    results[index] = _harvest(future, selected[index])
                    del pending[future]
                    continue
                if not bounded:
                    continue
                # The clock starts when the device's turn came, not when it
                # was queued: a device waiting for a free worker has not had
                # its chance yet.
                start = started.get(index)
                if start is not None and now - start > per_device_timeout:
                    results[index] = _gave_up(
                        selected[index], now - start,
                        'gave up after %.1fs; the worker is still blocked on '
                        'the device' % per_device_timeout)
                    del pending[future]
                    abandoned.append(future)

    finally:
        # wait=False on purpose. An abandoned worker is inside a blocking read
        # and joining it here would hand back exactly the delay the timeout
        # exists to avoid. Python still joins the pool's threads at interpreter
        # exit, which is why the timeout is a backstop and not a kill switch.
        pool.shutdown(wait=False)

    succeeded = sum(1 for result in results if result.ok)
    log.info('polled %d device(s): %d ok, %d failed, %d disabled, %.2fs total',
             len(selected), succeeded, len(selected) - succeeded, skipped,
             time.monotonic() - began)
    return results


def readings(results):
    """The values of the results that succeeded, in the order polled."""
    return [result.values for result in results if result.ok]


def _sample(device, index, started):
    """Poll one device. Returns a Result; never raises into the pool.

    Swallowing the exception here rather than letting the future carry it is
    what keeps one unreachable inverter from being mistaken for a failed run.
    """
    name = device.get('name', '<unnamed>')
    driver_name = device.get('driver')
    started[index] = time.monotonic()
    begin = started[index]
    try:
        # load() caches by name and importlib serialises concurrent imports of
        # the same module, so several workers may reach this at once safely.
        driver = driver_registry.load(driver_name)
        log.debug('%s: polling with %s', name, driver.version_string())
        values = driver.read(device)
    except Exception as exc:
        duration = time.monotonic() - begin
        # A DeviceError already says which device, endpoint and block failed
        # and how many attempts it took; anything else is unexpected and worth
        # a traceback.
        if isinstance(exc, (modbus.DeviceError, driver_registry.DriverNotFound)):
            log.warning('%s (%s): %s', name, driver_name, exc)
        else:
            log.exception('%s (%s): unexpected error while polling', name, driver_name)
        return Result(name, driver_name, None, exc, duration)
    return Result(name, driver_name, values, None, time.monotonic() - begin)


def _harvest(future, device):
    """Turn a finished future into its Result.

    The worker returns a Result for success and failure alike, so this only
    has to cope with something raised outside the worker's own guard.
    """
    try:
        return future.result()
    except Exception as exc:
        return Result(device.get('name', '<unnamed>'), device.get('driver'),
                      None, exc, 0.0)


def _gave_up(device, duration, message):
    name = device.get('name', '<unnamed>')
    log.error('%s (%s): %s', name, device.get('driver'), message)
    return Result(name, device.get('driver'), None, TimeoutError(message), duration)
