# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Where readings go once they have been collected.

Acquisition and delivery used to be welded together in main(): the file write,
the MQTT push and the --verbose print were three blocks of inline code sharing
mutable locals, which is how the file write ended up computing its timestamp
twice and why a broken MQTT config could take the file write down with it.
A sink is one destination behind one method, so a run can have any combination
of them and a destination that fails only loses its own copy.

Every sink takes the same pair: the list of readings, and a context mapping
carrying at least `device_serial`, `config_name` and `timestamp` -- the facts
about the run rather than about the measurements.
"""

from __future__ import annotations

import os
import ssl
import sys
import gzip
import json
import logging

from datetime import datetime

log = logging.getLogger('solarian.sinks')

# Downstream tooling globs for this, so the layout is fixed:
# solarian_<serial>_<config>_<YYYYMMDDHHMM>.json.gz
FILENAME_TEMPLATE = 'solarian_%s_%s_%s.json.gz'
FILENAME_STAMP = '%Y%m%d%H%M'

# One exotic value -- a Decimal out of a postprocess hook, say -- should not
# throw away a whole run's readings, so every serialisation falls back to str.
_JSON = {'default': str}


class Sink:
    """One destination for a set of readings.

    Implementations report failure by logging it, not by raising: a sink that
    cannot deliver must not abort a polling run that other sinks can still
    complete. Exceptions that indicate a programming error rather than a sick
    environment are left to propagate.
    """

    def emit(self, readings, context):
        """Deliver `readings` (a list of dicts). Returns nothing."""
        raise NotImplementedError

    def close(self):
        """Release whatever the sink holds. Safe to call more than once."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


class ConsoleSink(Sink):
    """Pretty-printed JSON on stdout: the old --verbose flag as a sink."""

    def __init__(self, stream=None, indent=4):
        self.stream = stream
        self.indent = indent

    def emit(self, readings, context):
        # Resolved per call so that redirecting stdout after construction --
        # a test, or a caller piping a dry run somewhere -- still works.
        stream = self.stream if self.stream is not None else sys.stdout
        stream.write(json.dumps(readings, indent=self.indent, **_JSON))
        stream.write('\n')
        stream.flush()


class JsonFileSink(Sink):
    """A gzipped JSON file per run, published into data_dir by rename.

    The write goes to temp_dir first and is then renamed into place, which is
    the one part of the original the redesign keeps unchanged: rename is
    atomic within a filesystem, so an uploader watching data_dir sees either
    no file or a complete one, never a half-written archive.

    What changed, all of it bugs the original had in production:

    * The timestamp is computed once. The old code called get_timestamp()
      separately for the temporary name and the final name, so a run that
      crossed a minute boundary between the two renamed the file to a name
      that did not match the data inside it.
    * A failed rename no longer leaks. The old code logged the error and left
      the temporary file in tmp/ forever; every failed run added another one.
    * data_dir and temp_dir are created if missing.
    * The two directories are checked for being on the same filesystem, since
      rename across a boundary cannot work at all.
    * An empty reading set writes nothing by default (`skip_empty`). A run
      where every device failed used to produce a perfectly valid archive
      containing `[]`, which downstream read as "the site reported zero".
    """

    def __init__(self, data_dir, temp_dir, device_serial, config_name,
                 skip_empty=True):
        self.data_dir = os.path.abspath(os.path.expanduser(str(data_dir)))
        self.temp_dir = os.path.abspath(os.path.expanduser(str(temp_dir)))
        self.device_serial = device_serial
        self.config_name = config_name
        self.skip_empty = skip_empty

        for directory in (self.data_dir, self.temp_dir):
            os.makedirs(directory, exist_ok=True)
        self._check_same_filesystem()

    def _check_same_filesystem(self):
        """Warn loudly when rename cannot be atomic -- or work at all.

        os.rename() refuses to cross a filesystem boundary (EXDEV), so a
        temp_dir on a tmpfs while data_dir is on the SD card means every
        single write fails. Better to say so at startup than once a minute.
        """
        try:
            data_device = os.stat(self.data_dir).st_dev
            temp_device = os.stat(self.temp_dir).st_dev
        except OSError as exc:
            log.warning('cannot compare the filesystems of %s and %s: %s',
                        self.temp_dir, self.data_dir, exc)
            return
        if data_device != temp_device:
            log.warning('temp_dir %s (fs %s) and data_dir %s (fs %s) are on '
                        'DIFFERENT filesystems: os.rename() cannot move a file '
                        'across a filesystem boundary, so the atomic publish '
                        'will fail every run. Put temp_dir on the same '
                        'filesystem as data_dir.',
                        self.temp_dir, temp_device, self.data_dir, data_device)

    def filename(self, stamp):
        return FILENAME_TEMPLATE % (self.device_serial, self.config_name, stamp)

    def emit(self, readings, context):
        if not readings and self.skip_empty:
            log.warning('no readings in this run; no file written for %s',
                        self.config_name)
            return

        # Once. Both names are derived from this single value, which is the
        # whole point -- see the class docstring.
        stamp = _file_stamp(context)
        name = self.filename(stamp)
        final_path = os.path.join(self.data_dir, name)
        # The temporary name is deliberately not the final name: two runs
        # overlapping (the failure mode that started this redesign) would
        # otherwise write the same temporary file through each other.
        temp_path = os.path.join(self.temp_dir, '.%s.%d.part' % (name, os.getpid()))

        try:
            with gzip.open(temp_path, 'wt', encoding='utf-8') as handle:
                json.dump(readings, handle, **_JSON)
            os.rename(temp_path, final_path)
            log.debug('wrote %d reading(s) to %s', len(readings), final_path)
        except OSError as exc:
            log.error('could not publish %s: %s', final_path, exc)
        finally:
            self._discard(temp_path)

    def _discard(self, temp_path):
        """Remove the temporary file if it is still there.

        After a successful rename there is nothing left to remove; after any
        failure there is, and leaving it behind is what filled tmp/ up.
        """
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            return
        except OSError as exc:
            log.error('could not remove the temporary file %s: %s', temp_path, exc)
            return
        log.error('removed the orphaned temporary file %s', temp_path)


class MqttSink(Sink):
    """Publish each reading to every configured broker, one topic per device.

    `servers` is the validated server list from the MQTT configuration file;
    each entry supplies `topic`, `ip_address`, `port`, `username`, `password`
    and `enabled`, plus the optional TLS keys described below. Topics are
    `<server topic>/<Device_Name>` and the payload is the reading as JSON.

    A broker that refuses the connection is logged and skipped, so one dead
    destination cannot cost the others their copy.

    SECURITY -- what this replaces. The old sender passed
    `tls=ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)`. A bare SSLContext is an empty
    one: verify_mode is CERT_NONE, check_hostname is False, and no CA
    certificates are loaded. The traffic was encrypted, but the peer was never
    identified, and since every publish sends the broker username and password
    in the CONNECT packet, anything that could answer on the broker's address
    -- an ARP-spoofing host on the plant LAN, a hijacked DNS record, a
    mistyped address -- could present any certificate at all and collect the
    credentials. `ssl.create_default_context()` loads the system trust store,
    requires a certificate that chains to it (CERT_REQUIRED), and checks that
    the certificate actually names the host that was asked for
    (check_hostname). Per-server escape hatches, in order of preference:

        ca_certs:     file or directory holding a private/self-signed CA to
                      trust instead of the system store
        certfile /
        keyfile:      client certificate authentication
        tls: false    plaintext, for a broker on a trusted LAN
        tls_insecure: keep TLS but verify nothing -- the old behaviour, opted
                      into explicitly, and logged as a warning on every run

    Because the hostname is verified, a broker addressed by bare IP needs an
    IP entry in its certificate's subjectAltName; the usual fix is to put the
    broker's DNS name in `ip_address`, not to reach for tls_insecure.
    """

    def __init__(self, servers, device_serial):
        self.servers = list(servers or [])
        self.device_serial = device_serial

    def emit(self, readings, context):
        payloads = self._payloads(readings)
        if not payloads:
            log.debug('nothing to publish over MQTT')
            return

        # Imported here so a logger installed without MQTT support can still
        # use the other sinks, mirroring how modbus.py imports its transports.
        from paho.mqtt.publish import multiple

        published = 0
        for server in self.servers:
            if not server.get('enabled', True):
                continue
            label = _server_label(server)
            try:
                tls = _tls_context(server, label)
                topic_root = str(server.get('topic', '')).rstrip('/')
                messages = [{'topic': '%s/%s' % (topic_root, device_name),
                             'payload': payload}
                            for device_name, payload in payloads]
                multiple(messages,
                         hostname=server.get('ip_address'),
                         port=int(server.get('port') or (1883 if tls is None else 8883)),
                         client_id=server.get('client_id') or 'solarian-%s' % self.device_serial,
                         keepalive=15,
                         auth=_auth(server),
                         tls=tls)
            except Exception as exc:
                # Never interpolate the server mapping itself: it holds the
                # password.
                log.error('MQTT publish to %s failed: %s', label, exc)
            else:
                published += 1
                log.debug('published %d message(s) to %s', len(payloads), label)
        log.info('MQTT: %d reading(s) to %d of %d server(s)',
                 len(payloads), published, len(self.servers))

    def _payloads(self, readings):
        """Serialise each reading once, not once per server."""
        payloads = []
        for reading in readings:
            device_name = reading.get('Device_Name')
            if not device_name:
                # The topic is the only thing identifying the device on the
                # broker side, so a reading without a name has nowhere to go.
                log.warning('reading without Device_Name not published')
                continue
            payloads.append((device_name, json.dumps(reading, **_JSON)))
        return payloads


def _auth(server):
    """Credentials for paho, or None for an anonymous broker."""
    username = server.get('username')
    if not username:
        return None
    return {'username': username, 'password': server.get('password')}


def _server_label(server):
    """How a broker is named in the log. Never includes the password."""
    return '%s:%s' % (server.get('ip_address'), server.get('port'))


def _tls_context(server, label):
    """The SSLContext for one broker, or None for a plaintext connection.

    See MqttSink's docstring for why this is not the old bare SSLContext.
    """
    if server.get('tls') is False:
        log.debug('MQTT server %s: TLS disabled in configuration', label)
        return None

    ca_certs = server.get('ca_certs')
    if ca_certs and os.path.isdir(ca_certs):
        context = ssl.create_default_context(capath=ca_certs)
    else:
        # cafile=None leaves the system trust store in place.
        context = ssl.create_default_context(cafile=ca_certs)

    certfile = server.get('certfile')
    if certfile:
        context.load_cert_chain(certfile, server.get('keyfile'))

    if server.get('tls_insecure'):
        log.warning('MQTT server %s: tls_insecure is set, so neither the '
                    'broker certificate nor its hostname is verified -- the '
                    'MQTT credentials are exposed to anything that can answer '
                    'on that address', label)
        # Order matters: ssl refuses to drop verification while hostname
        # checking is still enabled.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def _file_stamp(context):
    """The single timestamp both file names are built from.

    The old code called get_timestamp() once for the temporary name and again
    for the final one, so a run crossing a minute boundary between the two
    produced two different names. Computing it once is the fix; taking it from
    the run context rather than the clock also means every sink in a run
    agrees, and leaves the local-versus-UTC choice with the caller. Falling
    back to local time preserves the naming of the existing archive.
    """
    value = (context or {}).get('timestamp')
    if isinstance(value, datetime):
        return value.strftime(FILENAME_STAMP)
    # A POSIX timestamp, as time.time() produces.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value).strftime(FILENAME_STAMP)
    if isinstance(value, str) and value:
        if len(value) == 12 and value.isdigit():
            return value
        try:
            return datetime.fromisoformat(
                value.replace('Z', '+00:00')).strftime(FILENAME_STAMP)
        except ValueError:
            pass
    if value is not None:
        log.warning('unusable timestamp %r in the sink context; '
                    'falling back to the current time', value)
    return datetime.now().strftime(FILENAME_STAMP)
