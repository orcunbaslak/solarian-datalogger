# -*- coding: UTF-8 -*-
"""A register map that is built from configuration rather than transcribed.

The golden snapshot pins what trk_eset_subarray emits for one configuration.
These tests pin the thing a snapshot cannot reach: that the map is still
correct at the sizes nobody captured, that the options producing it are
checked, and that a map too long to read is rejected before it is ever tried.
"""

import pytest

import fake_modbus
from snapshot import device_for

from solarian import modbus as sol_modbus
from solarian import driver as registry
from solarian.driver import Driver, Block, IntOption, OptionError
from solarian.decode import U16
from solarian.drivers import trk_eset_subarray as eset


# --- the Modbus read ceiling ------------------------------------------------

def test_a_block_longer_than_one_request_is_rejected():
    """125 registers is what FC 0x03 can return; 126 is a map that never reads."""
    with pytest.raises(ValueError) as exc:
        Block('too_long', sol_modbus.HOLDING, 0, 126)
    assert '125' in str(exc.value)


def test_coils_get_their_own_larger_ceiling():
    Block('many_coils', sol_modbus.COILS, 0, 2000)
    with pytest.raises(ValueError) as exc:
        Block('too_many_coils', sol_modbus.COILS, 0, 2001)
    assert '2000' in str(exc.value)


def test_no_shipped_driver_declares_an_unreadable_block():
    """A fleet-wide invariant, not just a property of the new driver."""
    for name in registry.available():
        driver = registry.load(name)
        for block in driver.blocks:
            ceiling = (registry.MAX_BITS_PER_READ
                       if block.function in (sol_modbus.COILS, sol_modbus.DISCRETE)
                       else registry.MAX_REGISTERS_PER_READ)
            assert block.count <= ceiling, '%s/%s' % (name, block.name)


# --- option validation ------------------------------------------------------

def test_a_required_option_must_be_given():
    option = IntOption('tracker_count', 1, 181)
    assert option.required
    with pytest.raises(OptionError):
        option.validate(None)


def test_an_option_with_a_default_is_optional():
    option = IntOption('tracker_count', 1, 181, default=4)
    assert not option.required
    assert option.validate(None) == 4


@pytest.mark.parametrize('bad', [0, 182, -1])
def test_an_out_of_range_option_is_rejected(bad):
    with pytest.raises(OptionError) as exc:
        IntOption('tracker_count', 1, 181).validate(bad)
    assert '1' in str(exc.value) and '181' in str(exc.value)


@pytest.mark.parametrize('bad', ['4', 4.5, True, None])
def test_an_option_that_is_not_a_whole_number_is_rejected(bad):
    """`tracker_count: yes` is a mistake, not the number one."""
    with pytest.raises(OptionError):
        IntOption('tracker_count', 1, 181).validate(bad)


def test_an_option_declared_outside_its_own_range_is_rejected():
    with pytest.raises(ValueError):
        IntOption('n', 1, 10, default=50)


def test_reading_without_a_valid_option_raises_rather_than_guessing():
    with pytest.raises(OptionError) as exc:
        eset.DRIVER.blocks_for({'name': 'T1'})
    assert 'tracker_count' in str(exc.value)


# --- block generation -------------------------------------------------------

def blocks_for(count):
    return eset.DRIVER.blocks_for({'tracker_count': count})


def tracker_blocks(count):
    return [b for b in blocks_for(count) if b.name != 'controller']


@pytest.mark.parametrize('count,expected', [
    (1, 1), (7, 1), (8, 1),      # one block holds eight whole trackers
    (9, 2), (16, 2), (17, 3),    # and the ninth starts another
    (181, 23),                   # 22 full blocks plus a remainder of five
])
def test_trackers_are_packed_eight_to_a_block(count, expected):
    assert len(tracker_blocks(count)) == expected


@pytest.mark.parametrize('count', [1, 8, 9, 24, 180, 181])
def test_no_generated_block_exceeds_one_request(count):
    for block in blocks_for(count):
        assert block.count <= registry.MAX_REGISTERS_PER_READ


@pytest.mark.parametrize('count', [1, 8, 9, 24, 181])
def test_every_block_holds_whole_trackers(count):
    """A tracker split across two requests would misalign every offset after it."""
    for block in tracker_blocks(count):
        assert block.count % eset.REGISTERS_PER_TRACKER == 0


@pytest.mark.parametrize('count', [1, 2, 8, 9, 24, 181])
def test_the_span_read_matches_the_workbook(count):
    """Tracker N lives at 40004 + 15*(N-1); the 181st ends at 42718."""
    blocks = tracker_blocks(count)
    assert blocks[0].address == eset.FIRST_TRACKER_ADDRESS
    last = blocks[-1]
    assert last.address + last.count - 1 == (
        eset.FIRST_TRACKER_ADDRESS + eset.REGISTERS_PER_TRACKER * count - 1)
    if count == 181:
        assert last.address + last.count - 1 == 42718


def test_the_blocks_are_contiguous():
    """A gap would mean a tracker nobody reads."""
    blocks = tracker_blocks(181)
    for earlier, later in zip(blocks, blocks[1:]):
        assert earlier.address + earlier.count == later.address


@pytest.mark.parametrize('count', [1, 24, 181])
def test_every_tracker_is_emitted_exactly_once(count):
    emitted = [n for b in blocks_for(count) for n in b.emitted_names()]
    assert len(emitted) == len(set(emitted))
    for number in range(1, count + 1):
        tag = eset.tracker_tag(number)
        assert tag + 'Target_Inclination' in emitted
        assert tag + 'Target_Tilt_Angle' in emitted
        assert tag + 'Fault' in emitted


def test_field_names_are_zero_padded_so_series_sort():
    assert eset.tracker_tag(1) == 'T001_'
    assert eset.tracker_tag(181) == 'T181_'
    tags = sorted({'T001_', 'T010_', 'T100_'})
    assert tags == ['T001_', 'T010_', 'T100_']


def test_the_declared_maximum_matches_the_workbook():
    option, = eset.DRIVER.options
    assert (option.minimum, option.maximum) == (1, 181)
    assert option.required


# --- caching ----------------------------------------------------------------

def test_a_map_is_built_once_per_configuration():
    driver = registry.load('trk_eset_subarray')
    first = driver.blocks_for({'tracker_count': 12})
    again = driver.blocks_for({'tracker_count': 12})
    assert first is again


def test_the_map_depends_on_the_options_and_nothing_else():
    """Two devices differing only in slave_id must share one map, not poison it."""
    driver = registry.load('trk_eset_subarray')
    a = driver.blocks_for({'tracker_count': 6, 'slave_id': 1, 'name': 'A'})
    b = driver.blocks_for({'tracker_count': 6, 'slave_id': 9, 'name': 'B'})
    assert a is b
    assert driver.blocks_for({'tracker_count': 7}) is not a


# --- introspection ----------------------------------------------------------

def test_the_driver_reports_itself_as_parametric():
    assert eset.DRIVER.parametric
    assert not registry.load('inv_abb_pvs800').parametric


def test_register_map_says_which_configuration_it_describes():
    sample = eset.DRIVER.register_map()
    assert sample['describes'] == {'tracker_count': eset.TRACKERS_PER_BLOCK}
    assert [o['name'] for o in sample['options']] == ['tracker_count']

    asked = eset.DRIVER.register_map({'tracker_count': 24})
    assert asked['describes'] == {'tracker_count': 24}
    assert len(asked['blocks']) == 4        # one controller block plus three


# --- end to end against the fake transport ----------------------------------

def test_a_larger_site_reads_the_blocks_it_declares():
    fake_modbus.install_all()
    fake_modbus.reset()
    device = dict(device_for('trk_eset_subarray'), tracker_count=24)
    values = registry.load('trk_eset_subarray').read(device)

    calls = fake_modbus.last_master().calls
    assert [(c[2], c[3]) for c in calls] == [
        (30000, 16), (40004, 120), (40124, 120), (40244, 120)]
    assert values['Trackers_Polled'] == 24.0
    assert 'T024_Fault' in values
    assert 'T025_Fault' not in values


def test_the_fault_total_counts_faulted_trackers():
    """Trackers_Faulted is the series you watch; the per-tracker codes explain it."""
    values = {'T001_Fault': 0, 'T002_Fault': 3, 'T003_Fault': 0, 'Working_Mode': 7}
    eset.summarise(values, {}, {})
    assert values['Trackers_Polled'] == 3.0
    assert values['Trackers_Faulted'] == 1.0


# --- the contract still holds for fixed drivers -----------------------------

def test_a_fixed_driver_is_unaffected():
    driver = Driver('D', '1', [Block('b', sol_modbus.HOLDING, 0, 2, [U16(0, 'V')])])
    assert not driver.parametric
    assert driver.options == ()
    assert driver.blocks_for({'anything': 1}) is driver.blocks


def test_a_generated_map_is_validated_like_a_declared_one():
    """The duplicate-name check must not be lost by moving map building later."""
    def build(options):
        return [Block('b', sol_modbus.HOLDING, 0, 4,
                      [U16(0, 'Power'), U16(1, 'Power')])]

    with pytest.raises(ValueError) as exc:
        Driver('D', '1', build, options=[IntOption('n', 1, 4, default=1)])
    assert 'Power' in str(exc.value)
