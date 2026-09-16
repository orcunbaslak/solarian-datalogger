# -*- coding: UTF-8 -*-
"""End-to-end: a full run, from YAML to a gzipped file on disk.

Exercises cli.main() the way cron does, with the Modbus transport faked so no
hardware is needed.
"""

import os
import gzip
import json
import glob

import pytest

import fake_modbus

from solarian import cli


@pytest.fixture(autouse=True)
def transport():
    fake_modbus.install_all()
    fake_modbus.reset()


@pytest.fixture
def site(tmp_path):
    """A small plant: two TCP inverters and one RS-485 meter."""
    for name in ('config', 'data', 'tmp', 'logs'):
        (tmp_path / name).mkdir()
    (tmp_path / 'config' / 'config.yml').write_text("""
devices:
  - name: INVERTER_1
    driver: inv_abb_pvs800
    enabled: yes
    measurement: SPP_1
    slave_id: 1
    ip_address: 10.0.0.9
    port: 502
  - name: INVERTER_2
    driver: inv_abb_pvs980
    enabled: yes
    measurement: SPP_1
    slave_id: 2
    ip_address: 10.0.0.10
    port: 502
  - name: METER_RS485
    driver: ekk_socomec_dirisa10
    enabled: yes
    measurement: SPP_1
    slave_id: 5
    serial_port: /dev/ttyUSB0
    baudrate: 19200
  - name: DISABLED_ONE
    driver: sensor_kippzonen_smp11
    enabled: no
    measurement: SPP_1
    slave_id: 9
    ip_address: 10.0.0.11
""")
    return tmp_path


def run(site, *extra):
    return cli.main([
        '--config', 'config.yml',
        '--config-dir', str(site / 'config'),
        '--data-dir', str(site / 'data'),
        '--temp-dir', str(site / 'tmp'),
        '--log-dir', str(site / 'logs'),
        '--log', 'DEBUG',
    ] + list(extra))


def written_file(site):
    files = glob.glob(str(site / 'data' / '*.json.gz'))
    assert len(files) == 1, 'expected one data file, found %r' % files
    with gzip.open(files[0], 'rt', encoding='utf-8') as fh:
        return files[0], json.load(fh)


def test_a_full_run_writes_one_gzipped_file(site):
    assert run(site) == cli.EXIT_OK

    path, payload = written_file(site)
    assert os.path.basename(path).startswith('solarian_')
    assert os.path.basename(path).endswith('.json.gz')

    names = [reading['Device_Name'] for reading in payload]
    assert names == ['INVERTER_1', 'INVERTER_2', 'METER_RS485']
    assert 'DISABLED_ONE' not in names


def test_readings_carry_real_decoded_values(site):
    run(site)
    _, payload = written_file(site)
    inverter = payload[0]
    assert inverter['Measurement_Suffix'] == 'SPP_1'
    assert inverter['Date'].endswith('Z')
    assert isinstance(inverter['Grid_Voltage'], float)
    assert inverter['Status_Main_Faulted'] in (0.0, 1.0)
    assert len(inverter) == 81


def test_the_temp_directory_is_left_clean(site):
    """A failed rename used to orphan the temp file forever."""
    run(site)
    assert os.listdir(site / 'tmp') == []


def test_write_disabled_is_a_real_dry_run(site):
    assert run(site, '--write-disabled') == cli.EXIT_OK
    assert glob.glob(str(site / 'data' / '*.json.gz')) == []


def test_serial_and_tcp_devices_coexist_in_one_run(site):
    """The old contract could not express a serial device at all."""
    run(site)
    hosts = {m.host for m in fake_modbus.FakeTcpMaster.instances}
    serial_hosts = {m.host for m in fake_modbus.FakeRtuMaster.instances}
    assert hosts == {'10.0.0.9', '10.0.0.10'}
    assert serial_hosts == {'/dev/ttyUSB0'}


def test_an_unreachable_device_does_not_stop_the_others(site, monkeypatch):
    """One dead inverter must not cost the plant a whole reading cycle."""
    original = fake_modbus.FakeTcpMaster.execute

    def flaky(self, slave_id, function, address, count, *a, **kw):
        if self.host == '10.0.0.10':
            raise IOError('simulated timeout')
        return original(self, slave_id, function, address, count)

    monkeypatch.setattr(fake_modbus.FakeTcpMaster, 'execute', flaky)
    monkeypatch.setattr('solarian.modbus.Session._backoff_delay', lambda *a: 0)

    assert run(site) == cli.EXIT_PARTIAL

    _, payload = written_file(site)
    names = [r['Device_Name'] for r in payload]
    assert names == ['INVERTER_1', 'METER_RS485']


def test_a_parametric_driver_runs_end_to_end(tmp_path):
    """A driver whose map is built from configuration, through the real path.

    Its own site rather than the shared one: this is about a device whose
    register map is a function of tracker_count, not about how it sits
    alongside four others.
    """
    for name in ('config', 'data', 'tmp', 'logs'):
        (tmp_path / name).mkdir()
    (tmp_path / 'config' / 'config.yml').write_text("""
devices:
  - name: TRACKERS_1
    driver: trk_eset_subarray
    enabled: yes
    measurement: SPP_1
    slave_id: 1
    ip_address: 10.0.0.9
    tracker_count: 10
""")
    assert run(tmp_path) == cli.EXIT_OK

    _, payload = written_file(tmp_path)
    reading, = payload
    assert reading['Device_Name'] == 'TRACKERS_1'
    assert reading['Trackers_Polled'] == 10.0
    assert 'T010_Target_Tilt_Angle' in reading
    assert 'T011_Target_Tilt_Angle' not in reading

    # Ten trackers is two blocks -- eight, then two -- plus the header.
    calls = [(c[2], c[3]) for c in fake_modbus.last_master().calls]
    assert calls == [(30000, 16), (40004, 120), (40124, 30)]


def test_a_parametric_driver_without_its_option_is_rejected(tmp_path):
    """Missing tracker_count must stop the run, not poll an assumed size."""
    for name in ('config', 'data', 'tmp', 'logs'):
        (tmp_path / name).mkdir()
    (tmp_path / 'config' / 'config.yml').write_text("""
devices:
  - name: TRACKERS_1
    driver: trk_eset_subarray
    enabled: yes
    measurement: SPP_1
    slave_id: 1
    ip_address: 10.0.0.9
""")
    assert run(tmp_path) == cli.EXIT_CONFIG
    assert glob.glob(str(tmp_path / 'data' / '*.json.gz')) == []


def test_a_rejected_config_exits_with_the_config_code(site):
    (site / 'config' / 'config.yml').write_text(
        'devices:\n  - {name: A, driver: inv_abb_pvs800, enabled: yes, measurment: M,\n'
        '     slave_id: 1, ip_address: 1.2.3.4}\n')
    assert run(site) == cli.EXIT_CONFIG
    assert glob.glob(str(site / 'data' / '*.json.gz')) == []


def test_check_config_validates_without_polling(site, capsys):
    assert run(site, '--check-config') == cli.EXIT_OK
    assert '4 device(s), 3 enabled' in capsys.readouterr().out
    assert fake_modbus.FakeTcpMaster.instances == []


def test_list_drivers_and_register_map(site, capsys):
    assert cli.main(['--list-drivers']) == cli.EXIT_OK
    assert 'inv_abb_pvs800' in capsys.readouterr().out

    assert cli.main(['--register-map', 'inv_abb_pvs800']) == cli.EXIT_OK
    dumped = json.loads(capsys.readouterr().out)
    assert dumped['driver'] == 'ABB_PVS800_TCP'
    assert [b['name'] for b in dumped['blocks']] == ['main', 'measurements', 'status']


def test_host_metrics_are_appended_when_requested(site):
    run(site, '--pi-analytics')
    _, payload = written_file(site)
    assert payload[-1]['Device_Name'] == 'SOLARIAN_DATALOGGER'
    assert 'DISK_Percent' in payload[-1]
