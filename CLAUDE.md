# Solarian Datalogger

A one-shot Modbus poller for solar plants, run from cron on a Raspberry Pi. It
reads a YAML device inventory, polls each device over Modbus TCP or RTU, and
writes the readings to a gzipped JSON file, MQTT, or stdout.

**Python 3.13 or newer**, enforced by `requires-python`. The venv is `.venv/`.

## Commands

```sh
.venv/bin/python -m pytest                          # 188 tests, no hardware needed
.venv/bin/pip install -e ".[dev]"                   # dev install
.venv/bin/python datalogger.py --check-config       # validate config and exit
.venv/bin/python datalogger.py --list-drivers       # every shipped driver
.venv/bin/python datalogger.py --register-map NAME  # a driver's map as JSON
```

`gtimeout`, not `timeout` (macOS).

## Layout

| Module | Responsibility |
|---|---|
| `solarian/config.py` | Load and **validate** YAML. A typo fails at startup, loudly. |
| `solarian/driver.py` | The driver contract: `Driver`, `Block`, `IntOption`, the registry. |
| `solarian/decode.py` | Field types: `U16`, `I16`, `U32`, `I32`, `Bitfield`, `Raw`, `Computed`. |
| `solarian/modbus.py` | TCP/RTU transport, connection lifetime, retries, backoff, bus locks. |
| `solarian/runner.py` | Polls devices concurrently; isolates one device's failure. |
| `solarian/sinks.py` | Where readings go: file, MQTT, console. |
| `solarian/host.py` | Health metrics for the logger machine itself. |
| `solarian/cli.py` | Argument parsing and wiring. |
| `solarian/drivers/` | One module per device; the name here is the `driver:` key in YAML. |

## The invariants that matter

These are load-bearing. Breaking one loses data silently, which is the failure
mode this codebase is organised against — a datalogger's symptom of a bug is a
gap in a report weeks later, not a crash.

**Scaling is an integer divisor, never a float factor.** Write `divide=10`, not
`scale=0.1`. The two disagree for 22,943 of the 65,536 uint16 values, so a float
factor would shift about a third of all readings.

**A driver is a declaration, not a procedure.** It says *which* registers exist
and how to read them. Connecting, retrying, timing out and reporting failure are
the framework's job, in one place, configurable per device. Never open a socket
or sleep inside a driver.

**Unknown config keys are rejected, not ignored.** `measurment:` must fail the
run. The allow-list is `ALLOWED_DEVICE_KEYS` plus the device's driver's declared
options — do not widen it to let something through.

**A device is sampled completely or reported as failed.** `Driver.read` raises
rather than returning partial values; `Result.ok` depends on it.

**No two fields may emit the same name.** Emitting is a dict assignment, so a
duplicate overwrites an earlier series with no error anywhere. `Driver` checks
this across all blocks at import time, including generated maps.

**A block cannot exceed one Modbus request** — 125 registers for `HOLDING` and
`INPUT`, 2000 bits for `COILS` and `DISCRETE`. Enforced in `Block._check()`.

## Writing a driver

Drop a module in `solarian/drivers/`. Open with the GPL header, then a docstring
carrying the **full register map as a table** with addresses, types, divisors and
units, plus anything about the device that a future reader would otherwise have
to rediscover. Follow `sensor_lufft_ws600.py` for a short one,
`trk_eset_subarray.py` for a generated one.

```python
DRIVER = Driver(
    name='MY_INVERTER', version='0.1',
    defaults={'retries': 5},                 # devices can still override
    blocks=[Block('main', HOLDING, 42496, 7, [I16(2, 'Active_Power', unit='kW')])],
)
```

Offsets are positions within the block, not absolute addresses. Read a wide
sparse span and emit only the documented registers rather than inventing names
for the gaps — reading extra registers is free, guessing at them is not.

For a map whose size depends on the installation, declare `options` and pass a
callable for `blocks`; it receives the validated options **and nothing else**,
which is what makes the result safe to cache. An `IntOption` with no `default`
is required.

Use `postprocess(values, blocks, device)` only for quirks a map cannot express.

### Adding a driver to the tests

`test_every_shipped_driver_is_covered` fails until you do all of this:

1. Add the module name to `DRIVERS` in `tests/snapshot.py`.
2. If it is serial, add settings to `SERIAL_DEVICES`; if parametric, add its
   options to `DRIVER_OPTIONS`.
3. Capture and merge its golden entry:
   ```sh
   .venv/bin/python tests/snapshot.py --only my_driver /tmp/new.json
   # then merge /tmp/new.json into tests/golden_drivers.json
   ```

`tests/golden_drivers.json` pins 411 decoded values across 11 devices against a
deterministic fake transport. **Never regenerate the whole file to make a test
pass** — a diff there means a divisor, address or bit index moved, and the test
is telling you which field. Regenerate only the driver you deliberately changed.

## Style

Comments explain *why*, and frequently name the specific bug or measurement that
motivated the code ("measured: four 1s devices took 4.02s with it, 1.01s
without"). Match that. Prose over bullet lists in docstrings. `%`-formatting, not
f-strings, throughout. No emoji.

When a device document is ambiguous, say so in the driver docstring and keep the
vendor's own field names rather than encoding a guess.

## Open hardware questions

`trk_eset_subarray` was transcribed from a workbook, not verified against a
controller. Two things need a real device:

- **`Target_Inclination` (+12) vs `Target_Tilt_Angle` (+13).** Both are labelled
  "Target" and the map exposes no measured position. Either +12 is the actual
  angle and its label is a translation artifact, or the two are the axes of a
  dual-axis tracker. One day of automatic-mode data decides it: an angle that
  lags its neighbour is a measurement; two that move independently are two axes.
- **Address convention.** Addresses are sent literally (30000, 40004) because the
  workbook documents function code 0x03 for both ranges, which rules out Modicon
  3x/4x numbering. Confirm on first poll.
