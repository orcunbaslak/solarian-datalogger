# -*- coding: UTF-8 -*-
"""Configuration validation.

The original loader accepted almost anything and let the consequences surface
later as a device that quietly never appeared in the data. These tests pin down
that bad configuration is now rejected at startup, with a message that names
the file and the offending device.
"""

import textwrap

import pytest

from solarian.config import (ConfigError, load_devices, load_mqtt, load_graylog,
                             ALLOWED_DEVICE_KEYS)

VALID = """
devices:
  - name: INVERTER_1
    driver: inv_abb_pvs800
    enabled: yes
    measurement: SPP_1
    slave_id: 1
    ip_address: 192.168.1.2
    port: 502
"""


def write(tmp_path, text, name='config.yml'):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    return str(path)


def test_a_valid_config_loads(tmp_path):
    devices = load_devices(write(tmp_path, VALID))
    assert len(devices) == 1
    assert devices[0]['name'] == 'INVERTER_1'
    assert devices[0]['enabled'] is True
    assert devices[0]['slave_id'] == 1


def test_port_defaults_to_502_for_tcp_devices(tmp_path):
    devices = load_devices(write(tmp_path, """
        devices:
          - {name: A, driver: d, enabled: yes, measurement: M, slave_id: 1,
             ip_address: 10.0.0.1}
    """))
    assert devices[0]['port'] == 502


def test_a_mistyped_key_is_rejected(tmp_path):
    """`measurment` used to be silently ignored, dropping the field."""
    with pytest.raises(ConfigError) as exc:
        load_devices(write(tmp_path, """
            devices:
              - {name: A, driver: d, enabled: yes, measurment: M, slave_id: 1,
                 ip_address: 10.0.0.1}
        """))
    assert 'measurment' in str(exc.value)


def test_missing_required_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_devices(write(tmp_path, """
            devices:
              - {name: A, driver: d, enabled: yes, measurement: M,
                 ip_address: 10.0.0.1}
        """))
    assert 'slave_id' in str(exc.value)


def test_duplicate_device_names_are_rejected(tmp_path):
    """Two devices sharing a name overwrite each other downstream."""
    with pytest.raises(ConfigError) as exc:
        load_devices(write(tmp_path, """
            devices:
              - {name: A, driver: d, enabled: yes, measurement: M, slave_id: 1,
                 ip_address: 10.0.0.1}
              - {name: A, driver: d, enabled: yes, measurement: M, slave_id: 2,
                 ip_address: 10.0.0.2}
        """))
    assert 'A' in str(exc.value)


def test_a_device_with_no_transport_is_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_devices(write(tmp_path, """
            devices:
              - {name: A, driver: d, enabled: yes, measurement: M, slave_id: 1}
        """))


def test_a_serial_device_needs_no_ip_address(tmp_path):
    devices = load_devices(write(tmp_path, """
        devices:
          - {name: A, driver: d, enabled: yes, measurement: M, slave_id: 1,
             serial_port: /dev/ttyUSB0, baudrate: 19200}
    """))
    assert devices[0]['serial_port'] == '/dev/ttyUSB0'
    assert devices[0]['baudrate'] == 19200


@pytest.mark.parametrize('key,bad', [
    ('slave_id', 'banana'),
    ('port', 'banana'),
    ('retries', -1),
])
def test_wrongly_typed_values_are_rejected(tmp_path, key, bad):
    with pytest.raises(ConfigError) as exc:
        load_devices(write(tmp_path, """
            devices:
              - name: A
                driver: d
                enabled: yes
                measurement: M
                slave_id: 1
                ip_address: 10.0.0.1
                %s: %s
        """ % (key, bad)))
    assert key in str(exc.value)


def test_a_missing_file_is_a_config_error_not_a_traceback(tmp_path):
    with pytest.raises(ConfigError):
        load_devices(str(tmp_path / 'nope.yml'))


def test_malformed_yaml_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_devices(write(tmp_path, 'devices: [oh: no: yes\n'))


def test_allowed_device_keys_covers_the_documented_sample():
    """The sample config must not use a key the validator rejects."""
    devices = load_devices('config/sample-config.yml')
    for device in devices:
        assert set(device) <= set(ALLOWED_DEVICE_KEYS), set(device) - set(ALLOWED_DEVICE_KEYS)


def test_mqtt_config_requires_its_fields(tmp_path):
    with pytest.raises(ConfigError):
        load_mqtt(write(tmp_path, """
            servers:
              - {topic: T, ip_address: h, enabled: yes}
        """, 'mqtt.yml'))


def test_valid_mqtt_config_loads(tmp_path):
    servers = load_mqtt(write(tmp_path, """
        servers:
          - {topic: T, ip_address: broker.example.com, port: 8883,
             username: u, password: p, enabled: yes}
    """, 'mqtt.yml'))
    assert servers[0]['port'] == 8883


def test_graylog_config_loads(tmp_path):
    settings = load_graylog(write(tmp_path, """
        server:
          - {server_address: logs.example.com, port: 12205}
    """, 'graylog.yml'))
    assert settings['server_address'] == 'logs.example.com'
    assert settings['port'] == 12205
