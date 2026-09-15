<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![GPLv3 License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

<!-- PROJECT LOGO -->
<br />
<p align="center">
  <a href="https://github.com/orcunbaslak/solarian-datalogger">
    <img src="https://github.com/orcunbaslak/solarian-datalogger/blob/master/images/solarian_logo.png?raw=true" alt="Logo" width="411" height="162">
  </a>

  <h3 align="center">Solarian Datalogger</h3>

  <p align="center">
    A datalogger for solar plants. Describe your devices in YAML, describe each
    device's register map in a driver, and the logger polls them over Modbus and
    records the readings.
    <br />
    <br />
    <a href="https://github.com/orcunbaslak/solarian-datalogger/issues">Report Bug</a>
    ·
    <a href="https://github.com/orcunbaslak/solarian-datalogger/issues">Request Feature</a>
  </p>
</p>

## Table of Contents

* [About the Project](#about-the-project)
* [How it fits together](#how-it-fits-together)
* [Getting Started](#getting-started)
* [Configuration](#configuration)
* [Usage](#usage)
* [Writing a driver](#writing-a-driver)
* [Testing](#testing)
* [Contributing](#contributing)
* [License](#license)
* [Similar Projects](#similar-projects)
* [Contact](#contact)

<!-- ABOUT THE PROJECT -->
## About The Project

There are many causes for people to write code. As an engineering company owner, I was
frustrated to see how incompetent datalogging companies doing business around. Data losses,
buggy software and other issues led me to write a minimalist piece of software for solar
systems just to get the basic data from inverters, sensors and string combiners into our
InfluxDB server.

Here's why:
* As engineers, our time is money. Bad data makes us invest more time in it.
* Good data yields good engineering analysis. You deserve **precise** and **accurate** results.
* Why spend time fixing someone else's inaccurate data instead of enjoying the sun outside
  with your family?

### Built With

* [Python 3](https://www.python.org/) (developed and tested on 3.13)
* [modbus-tk](https://github.com/ljean/modbus-tk) — TCP and RTU transport
* [PyYAML](https://github.com/yaml/pyyaml) — configuration
* [Paho MQTT](https://github.com/eclipse/paho.mqtt.python) — publishing

## How it fits together

```
config.yml ──► config.py ──► runner.py ──► driver.py ──► modbus.py ──► device
  devices      validates     polls in      resolves      transport,
                             parallel      the driver    retries
                                 │
                                 ▼
                             sinks.py ──► gzipped JSON file
                                      ──► MQTT
                                      ──► stdout
```

| Module | Responsibility |
|---|---|
| `solarian/config.py` | Load and **validate** YAML. A typo fails at startup, loudly. |
| `solarian/driver.py` | The driver contract: `Driver`, `Block`, and the registry. |
| `solarian/decode.py` | Register field types: `U16`, `I16`, `U32`, `I32`, `Bitfield`. |
| `solarian/modbus.py` | TCP/RTU transport, connection lifetime, retries and backoff. |
| `solarian/runner.py` | Polls devices concurrently; isolates one device's failure. |
| `solarian/sinks.py` | Where readings go: file, MQTT, console. |
| `solarian/host.py` | Health metrics for the logger machine itself. |
| `solarian/cli.py` | Argument parsing and wiring. |

A driver declares **what** registers a device exposes. Connecting, retrying, timing out
and reporting failure are the framework's job, in one place, configurable per device.

<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

```sh
sudo apt update
sudo apt-get -y install git python3-venv python3-dev gcc
```

### Installation

```sh
git clone https://github.com/orcunbaslak/solarian-datalogger /home/pi/solarian-datalogger
cd /home/pi/solarian-datalogger
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then create your configuration from the samples:

```sh
cp config/sample-config.yml  config/config.yml     # required
cp config/sample-mqtt.yml    config/mqtt.yml       # optional, for --mqtt
cp config/sample-graylog.yml config/graylog.yml    # optional, for --graylog
```

All three real config files are gitignored, so credentials and site addresses stay
off the repository.

Check your configuration before wiring up cron:

```sh
.venv/bin/python datalogger.py --check-config
```

## Configuration

Every device needs `name`, `driver`, `enabled`, `measurement` and `slave_id`, plus either
a TCP address or a serial port. Unknown keys are rejected rather than ignored, so a
mistyped `measurment:` stops the run instead of silently dropping the device.

```yaml
devices:
  - name: INVERTER_1
    driver: inv_abb_pvs980
    enabled: yes
    measurement: SPP_1
    slave_id: 1
    ip_address: 192.168.1.2
    port: 502

  # Modbus RTU: declaring serial_port selects the serial transport.
  - name: METER_RS485
    driver: ekk_socomec_dirisa10
    enabled: yes
    measurement: SPP_1
    slave_id: 5
    serial_port: /dev/ttyUSB0
    baudrate: 19200
```

Any device may override the transport tuning. Settings resolve in the order
**device → driver → framework default**:

```yaml
    timeout: 8.0        # seconds per request
    retries: 5          # attempts per register block
    backoff: 1.0        # first retry delay; doubles, with jitter
    max_backoff: 10.0
```

## Usage

```sh
.venv/bin/python datalogger.py --config config.yml --mqtt --pi-analytics
```

```
  --config CONFIG      device inventory in config/. Default: config.yml
  --log LEVEL          DEBUG, INFO, WARNING, ERROR, CRITICAL. Default: WARNING
  --verbose            also print readings to stdout
  --pi-analytics       include this machine's CPU, memory and disk figures
  --write-disabled     do not write the data file (dry run)
  --mqtt               publish over MQTT; needs config/mqtt.yml
  --graylog            send logs to Graylog; needs config/graylog.yml
  --workers N          devices polled in parallel. Default: 4
  --device-timeout S   give up on a stuck device after S seconds
  --check-config       validate configuration and exit
  --list-drivers       list available drivers and exit
  --register-map NAME  print a driver's register map as JSON and exit
```

Devices sharing one `serial_port` are automatically serialised against each other —
an RS-485 bus is a single pair of wires and its transactions must not interleave —
while TCP devices poll in parallel. `--workers 1` forces strictly sequential polling
for the whole fleet if you want it.

Exit codes: `0` all devices read, `1` some device failed, `2` configuration rejected,
`130` interrupted.

A typical crontab entry:

```cron
* * * * * /home/pi/solarian-datalogger/.venv/bin/python /home/pi/solarian-datalogger/datalogger.py --mqtt --pi-analytics
```

## Writing a driver

A driver is a register map, not a procedure. Drop a file in `solarian/drivers/` and
reference it by filename in `config.yml`.

```python
from solarian.decode import U16, I16, U32, Bitfield
from solarian.driver import Driver, Block
from solarian.modbus import HOLDING

DRIVER = Driver(
    name='MY_INVERTER',
    version='0.1',
    defaults={'retries': 5},          # optional; devices can still override
    blocks=[
        Block('main', HOLDING, 42496, 7, [
            I16(2, 'Active_Power', unit='kW'),
            U16(4, 'Grid_Voltage', divide=10, unit='V'),
            U32(5, 6, 'Total_kWh', decimals=1, unit='kWh'),
            Bitfield(1, 'Status_', {0: 'Ready', 1: 'Faulted'}),
        ]),
    ],
)
```

Field offsets are positions within the block. Available types: `U16`, `I16`, `U32`,
`I32`, `Bitfield`, `Raw`, `Computed`.

**Scaling is an integer divisor, never a float factor.** Write `divide=10`, not
`scale=0.1`. The two disagree for 22,943 of the 65,536 possible uint16 values, so a
float factor would silently shift about a third of your readings.

Out-of-range offsets are rejected when the module is imported, not at 3am when the
device is finally read.

For a genuine device quirk that a register map cannot express — a sensor that reports
negative irradiation at night, say — use the escape hatch:

```python
def _clamp(values, blocks, device):
    if values['Irradiation'] < 0:
        values['Irradiation'] = 0.0

DRIVER = Driver(..., postprocess=_clamp)
```

Inspect any driver's map without hardware:

```sh
.venv/bin/python datalogger.py --register-map inv_abb_pvs800
```

Modules written against the old `get_data(ip_address, port, slave_id, device_name,
measurement_suffix)` contract still load through a compatibility adapter, but they
cannot be given a serial port or per-device timeouts — which is why the contract
changed.

## Testing

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Drivers are covered by a golden snapshot, `tests/golden_drivers.json`, captured from
the original hand-written drivers. It pins 392 decoded values across all 10 devices
against a deterministic fake transport, so if a divisor, a register address or a bit
index ever moves, the test names the field that changed. No hardware required.

<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn,
inspire, and create. Any contributions you make are **greatly appreciated**.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/NewInverter`)
3. Commit your Changes (`git commit -m 'Add a new inverter driver'`)
4. Run the tests (`.venv/bin/python -m pytest`)
5. Push to the Branch (`git push origin feature/NewInverter`)
6. Open a Pull Request

<!-- LICENSE -->
## License

Distributed under the GNU GPL v3 License. See `LICENSE` for more information.

<!-- SIMILAR PROJECTS -->
## Similar Projects

* [Solariot](https://github.com/meltaxa/solariot)
* [Modbus-logger](https://github.com/GuillermoElectrico/modbus-logger)
* [PVStats](https://github.com/ptarcher/pvstats)
* [Modbus4MQTT](https://github.com/tjhowse/modbus4mqtt)
* [Energy-Meter-Logger](https://github.com/samuelphy/energy-meter-logger)

<!-- CONTACT -->
## Contact

Orçun Başlak - [@orcunbaslak](https://twitter.com/orcunbaslak) - [website](https://orcun.baslak.com/) - orcun.baslak@solarian.com.tr

Solarian Enerji - [@solarianenerji](https://twitter.com/solarianenerji) - [website](https://www.solarian.com.tr/en/) - info@solarian.com.tr

Project Link: [https://github.com/orcunbaslak/solarian-datalogger](https://github.com/orcunbaslak/solarian-datalogger)

<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/orcunbaslak/solarian-datalogger.svg?style=flat-square
[contributors-url]: https://github.com/orcunbaslak/solarian-datalogger/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/orcunbaslak/solarian-datalogger.svg?style=flat-square
[forks-url]: https://github.com/orcunbaslak/solarian-datalogger/network/members
[stars-shield]: https://img.shields.io/github/stars/orcunbaslak/solarian-datalogger.svg?style=flat-square
[stars-url]: https://github.com/orcunbaslak/solarian-datalogger/stargazers
[issues-shield]: https://img.shields.io/github/issues/orcunbaslak/solarian-datalogger.svg?style=flat-square
[issues-url]: https://github.com/orcunbaslak/solarian-datalogger/issues
[license-shield]: https://img.shields.io/github/license/orcunbaslak/solarian-datalogger.svg?style=flat-square
[license-url]: https://github.com/orcunbaslak/solarian-datalogger/blob/master/LICENSE
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=flat-square&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/orcunbaslak
