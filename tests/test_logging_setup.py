# -*- coding: UTF-8 -*-
"""Logging: secrets must never reach the log file or Graylog.

The previous MQTT module logged every broker's password in cleartext at DEBUG
level, which put it in logs/ on the Pi and, with --graylog, shipped it across
the network. These tests pin the redaction that replaced it.
"""

import logging
import logging.handlers

import pytest

from solarian import logging_setup


def record(msg, *args):
    return logging.LogRecord('solarian.test', logging.DEBUG, __file__, 1,
                             msg, args, None)


def rendered(rec):
    logging_setup.RedactingFilter().filter(rec)
    return rec.getMessage()


def test_a_password_passed_as_an_argument_is_redacted():
    out = rendered(record('connecting user=%s password=%s', 'solarian', 'hunter2'))
    assert 'hunter2' not in out
    assert '***' in out


def test_a_password_inside_a_dict_argument_is_redacted():
    """paho's auth dict was logged wholesale by the old code."""
    out = rendered(record('auth=%s', {'username': 'solarian', 'password': 'hunter2'}))
    assert 'hunter2' not in out
    assert 'solarian' in out


def test_a_password_embedded_in_the_message_is_redacted():
    out = rendered(record('server config password=hunter2 enabled=yes'))
    assert 'hunter2' not in out


@pytest.mark.parametrize('key', ['password', 'passwd', 'secret', 'token',
                                 'auth', 'api_key', 'apikey'])
def test_every_secret_key_name_is_covered(key):
    out = rendered(record('%s=topsecretvalue' % key))
    assert 'topsecretvalue' not in out, key


def test_ordinary_messages_are_left_alone():
    out = rendered(record('read %d registers from %s', 27, '10.0.0.9'))
    assert out == 'read 27 registers from 10.0.0.9'


def test_the_old_mqtt_log_line_would_now_be_safe():
    """Reproduces communication/mqtt.py:49 verbatim in shape."""
    out = rendered(record(
        '{} <--> {} <--> {} <--> {} <--> {} <--> {}'.format(
            'SolarianMQTT', '10.0.0.1', 1234, 'osman', 'password=osmanmustprevail', True)))
    assert 'osmanmustprevail' not in out


def test_configure_attaches_rotation_not_an_unbounded_file(tmp_path):
    """logs/ used to grow forever on an SD card with cron running every minute."""
    log = logging_setup.configure(level='DEBUG', log_dir=str(tmp_path),
                                  config_name='t_rot')
    handlers = [h for h in log.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert handlers, 'expected a RotatingFileHandler'
    assert handlers[0].maxBytes > 0
    assert handlers[0].backupCount > 0


def test_configure_is_idempotent(tmp_path):
    """Cron reruns and tests both call this; handlers must not accumulate."""
    first = logging_setup.configure(level='INFO', log_dir=str(tmp_path),
                                    config_name='t_idem')
    count = len(first.handlers)
    second = logging_setup.configure(level='INFO', log_dir=str(tmp_path),
                                     config_name='t_idem')
    assert second is first
    assert len(second.handlers) == count


def test_redaction_is_attached_to_handlers_not_just_the_logger(tmp_path):
    """A logger-level filter would miss records from solarian.modbus etc.

    Child loggers propagate records to the parent's handlers without
    re-running the parent logger's own filters, so the filter has to sit on
    each handler or child-module secrets would leak straight through.
    """
    log = logging_setup.configure(level='DEBUG', log_dir=str(tmp_path),
                                  config_name='t_filter')
    # pytest injects its own capture handler into the logger; only assert on
    # the handlers configure() installed.
    installed = [h for h in log.handlers
                 if 'LogCapture' not in type(h).__name__]
    assert installed, 'configure() installed no handlers'
    for handler in installed:
        assert any(isinstance(f, logging_setup.RedactingFilter)
                   for f in handler.filters), handler


def test_a_child_logger_secret_is_redacted_on_disk(tmp_path):
    """End to end: what actually lands in the file."""
    logging_setup.configure(level='DEBUG', log_dir=str(tmp_path),
                            config_name='t_child')
    logging.getLogger('solarian.modbus').debug('auth password=%s', 'hunter2')
    logging.shutdown()

    written = ''.join(p.read_text() for p in tmp_path.glob('*.log'))
    assert 'hunter2' not in written
    assert written.strip(), 'nothing was written'


def test_an_invalid_level_is_rejected(tmp_path):
    with pytest.raises((ValueError, AttributeError, TypeError)):
        logging_setup.configure(level='LOUD', log_dir=str(tmp_path),
                                config_name='t_bad')
