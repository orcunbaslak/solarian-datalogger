# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Command line entry point: parse arguments, wire the pieces, run once.

The logger is a one-shot program driven by cron, not a daemon. Everything it
needs is assembled here and nothing is kept in module-level state, so the whole
run is a function that can be called from a test.
"""

import os
import sys
import json
import time
import signal
import logging
import argparse

from datetime import datetime

from solarian import config as config_module
from solarian import logging_setup, identity, runner, sinks
from solarian.driver import load as load_driver, available as available_drivers

log = logging.getLogger('solarian.cli')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2
EXIT_INTERRUPTED = 130


class Shutdown:
    """Records SIGINT/SIGTERM and lets a second signal through.

    The previous implementation installed handlers that set a `kill_now` flag
    nothing ever read, which replaced Python's default SIGINT behaviour. The
    net effect was the opposite of the name: the process stopped responding to
    Ctrl-C and to systemd's SIGTERM, and only SIGKILL would end it.

    A Modbus read already in flight cannot be abandoned safely, so this does
    not pretend to interrupt one. It records the request, restores the default
    handler so an impatient second signal terminates immediately, and the run
    checks `requested` before starting any further work.
    """

    def __init__(self, start_time=None):
        self.requested = False
        self.start_time = start_time or time.time()
        self._previous = {}

    def install(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                self._previous[signum] = signal.signal(signum, self._handle)
            except (ValueError, OSError):
                # Not the main thread, or the platform lacks the signal.
                pass
        return self

    def _handle(self, signum, frame):
        self.requested = True
        name = signal.Signals(signum).name
        log.critical('%s received after %.2fs; finishing the current read, '
                     'signal again to stop now',
                     name, time.time() - self.start_time)
        previous = self._previous.get(signum, signal.SIG_DFL)
        try:
            signal.signal(signum, previous)
        except (ValueError, OSError):
            pass


def build_parser():
    parser = argparse.ArgumentParser(
        prog='datalogger',
        description='Poll solar plant devices over Modbus and record the readings.')

    parser.add_argument('--config', default='config.yml',
                        help='device inventory inside the config directory, '
                             'or a path. Default: config.yml')
    parser.add_argument('--log', default='WARNING', metavar='LEVEL',
                        help='DEBUG, INFO, WARNING, ERROR or CRITICAL. '
                             'Default: WARNING')
    parser.add_argument('--verbose', action='store_true',
                        help='also print the readings to stdout')
    parser.add_argument('--pi-analytics', action='store_true', dest='host_metrics',
                        help='include CPU, memory and disk figures for this machine')
    parser.add_argument('--write-disabled', action='store_true',
                        help='do not write the data file (dry run)')
    parser.add_argument('--mqtt', action='store_true', dest='mqtt_enabled',
                        help='publish readings over MQTT; needs mqtt.yml')
    parser.add_argument('--graylog', action='store_true',
                        help='send logs to Graylog; needs graylog.yml')
    parser.add_argument('--workers', type=int, default=4, metavar='N',
                        help='devices to poll concurrently. Use 1 for an '
                             'RS-485 bus, where devices share one line. Default: 4')
    parser.add_argument('--device-timeout', type=float, default=None,
                        metavar='SECONDS',
                        help='give up on a device after this long and report '
                             'it as failed, so one stuck device cannot run a '
                             'cron cycle past its interval. Off by default; '
                             'prefer per-device timeout/retries in the config.')

    parser.add_argument('--config-dir', default=os.path.join(ROOT, 'config'))
    parser.add_argument('--data-dir', default=os.path.join(ROOT, 'data'))
    parser.add_argument('--temp-dir', default=os.path.join(ROOT, 'tmp'))
    parser.add_argument('--log-dir', default=os.path.join(ROOT, 'logs'))

    parser.add_argument('--check-config', action='store_true',
                        help='validate the configuration and exit')
    parser.add_argument('--list-drivers', action='store_true',
                        help='list the available drivers and exit')
    parser.add_argument('--register-map', metavar='DRIVER',
                        help='print a driver\'s register map as JSON and exit')
    return parser


def _resolve(path, directory):
    """Treat a bare filename as living in the given directory."""
    if os.path.isabs(path) or os.sep in path:
        return path
    return os.path.join(directory, path)


def main(argv=None):
    start_time = time.time()
    args = build_parser().parse_args(argv)

    # Informational modes need no configuration and no log file.
    if args.list_drivers:
        for name in available_drivers():
            try:
                driver = load_driver(name)
            except Exception as exc:
                print('%-32s <failed to load: %s>' % (name, exc))
                continue
            print('%-32s %s' % (name, driver.version_string()))
        return EXIT_OK

    if args.register_map:
        try:
            driver = load_driver(args.register_map)
        except Exception as exc:
            print('cannot load driver %r: %s' % (args.register_map, exc),
                  file=sys.stderr)
            return EXIT_CONFIG
        print(json.dumps(driver.register_map(), indent=2))
        return EXIT_OK

    config_file = _resolve(args.config, args.config_dir)
    config_name = os.path.splitext(os.path.basename(config_file))[0]

    # A broken optional config must never cost the primary data write. Only
    # the device inventory is fatal, because without it there is nothing to do.
    config_problem = False

    graylog_settings = None
    if args.graylog:
        try:
            graylog_settings = config_module.load_graylog(
                _resolve('graylog.yml', args.config_dir))
        except config_module.ConfigError as exc:
            config_problem = True
            print('graylog configuration rejected, continuing without remote '
                  'logging: %s' % exc, file=sys.stderr)

    logging_setup.configure(
        level=args.log,
        log_dir=args.log_dir,
        config_name=config_name,
        graylog=graylog_settings,
        console=args.verbose,
        device_id=identity.device_serial(),
    )

    shutdown = Shutdown(start_time).install()
    log.info('=== datalogger started (config=%s) ===', config_name)

    try:
        devices = config_module.load_devices(config_file)
    except config_module.ConfigError as exc:
        log.error('configuration rejected: %s', exc)
        print('configuration rejected: %s' % exc, file=sys.stderr)
        return EXIT_CONFIG

    mqtt_servers = []
    if args.mqtt_enabled:
        try:
            mqtt_servers = config_module.load_mqtt(
                _resolve('mqtt.yml', args.config_dir))
        except config_module.ConfigError as exc:
            # Previously this returned before runner.poll, so an unquoted
            # password in mqtt.yml meant no device was polled and no local file
            # was written -- a whole plant recording nothing, every minute,
            # because of a typo in an optional sink's config.
            config_problem = True
            log.error('mqtt configuration rejected, continuing without MQTT: %s',
                      exc)
            print('mqtt configuration rejected, continuing without MQTT: %s'
                  % exc, file=sys.stderr)

    if args.check_config:
        enabled = [d for d in devices if d.get('enabled')]
        print('%s: %d device(s), %d enabled' %
              (config_file, len(devices), len(enabled)))
        for device in devices:
            mark = ' ' if device.get('enabled') else '-'
            print('  %s %-24s %-28s %s' % (
                mark, device['name'], device['driver'],
                device.get('serial_port') or '%s:%s' % (
                    device.get('ip_address'), device.get('port'))))
        if mqtt_servers:
            print('mqtt: %d server(s), %d enabled' % (
                len(mqtt_servers), len([s for s in mqtt_servers if s.get('enabled')])))
        return EXIT_OK

    results = runner.poll(devices, max_workers=args.workers,
                          per_device_timeout=args.device_timeout)
    values = runner.readings(results)

    if args.host_metrics:
        from solarian import host
        try:
            values.append(host.host_metrics())
        except Exception:
            log.exception('could not collect host metrics')

    if shutdown.requested:
        log.warning('shutdown requested; not writing or publishing this run')
        return EXIT_INTERRUPTED

    serial = identity.device_serial()
    context = {
        'device_serial': serial,
        'config_name': config_name,
        # A datetime, not time.time(): _file_stamp takes a datetime or a
        # string, and a float fell through to its warning path on every run.
        'timestamp': datetime.now(),
    }

    # Construction is guarded too, not just emit: JsonFileSink's __init__ calls
    # makedirs and stat, so a read-only SD card used to escape main() as an
    # unhandled traceback and take the MQTT copy down with it.
    wanted = []
    if args.verbose:
        wanted.append(('console', lambda: sinks.ConsoleSink()))
    if not args.write_disabled:
        wanted.append(('file', lambda: sinks.JsonFileSink(
            args.data_dir, args.temp_dir, serial, config_name)))
    if mqtt_servers:
        wanted.append(('mqtt', lambda: sinks.MqttSink(mqtt_servers, serial)))

    active = []
    for label, build in wanted:
        try:
            active.append(build())
        except Exception:
            log.exception('could not start the %s sink; continuing without it',
                          label)

    for sink in active:
        try:
            sink.emit(values, context)
        except Exception:
            log.exception('sink %s failed', type(sink).__name__)
        finally:
            try:
                sink.close()
            except Exception:
                log.exception('closing sink %s failed', type(sink).__name__)

    failed = [r for r in results if not r.ok]
    log.info('=== datalogger finished in %.4fs: %d ok, %d failed ===',
             time.time() - start_time, len(results) - len(failed), len(failed))
    # Report the bad optional config, but only after the readings are written.
    if config_problem:
        return EXIT_CONFIG
    return EXIT_PARTIAL if failed else EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
