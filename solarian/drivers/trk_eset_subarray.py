# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2026 Orçun Başlak
#    Licensed under the GNU GPL v3 or later. See LICENSE.

"""Eset tracker sub-array controller, Modbus TCP.

One Modbus slave fronting up to 181 tracker nodes. The controller answers for
itself in a short header block and then repeats an identical fifteen-register
slot per tracker, so how many registers this driver reads is a property of the
installation, not of the protocol -- hence `tracker_count` below.

Transcribed from the vendor's "Tracker Node modbus list" workbook, whose AI
sheet gives 2731 rows: a 16-register header at 30000 and trackers 1..181 at
40004 + 15*(N-1), the last ending at 42718. The per-tracker template was
checked against all 181 repetitions with no deviation, so it is declared once
and generated, rather than transcribed 181 times by hand.

  HEADER  30000 +16 (holding)
    +0   full sub-array working mode          uint16   code
    +1   starting address                     uint16   code
    +2   end address                          uint16   code
    +3   sub-array address                    uint16   code
    +4   communication address                uint16   code
    +5..+11  system time Y/M/D/h/m/s, zone    uint16
    +12  longitude                            int16    0.01   deg
    +13  latitude                             int16    0.01   deg
    +14  wind speed                           uint16   0.01   m/s
    +15  wind direction                       uint16   1      deg

  PER TRACKER  40004 + 15*(N-1) +15 (holding)
    +0   installation longitude               int16    0.01   deg
    +1   installation latitude                int16    0.01   deg
    +2   working mode                         uint16   code
    +3   wind speed                           uint16   0.01   m/s
    +4   wind direction                       uint16   1      deg
    +5   time zone                            int16
    +6..+11  system time Y/M/D/h/m/s          uint16
    +12  "Target Inclination"                 int16    0.01   deg
    +13  "Target Tilt Angle"                  int16    0.01   deg
    +14  fault                                uint16   code

Everything is function code 0x03 and a single 16-bit register; the workbook's
endianness column reads NA throughout because nothing spans two registers.

Three things about this map are worth knowing before trusting the output.

**The addresses are literal.** Both ranges are documented as function code
0x03, which rules out Modicon 3x/4x numbering -- a 3xxxx register in that
convention is read with 0x04, not 0x03. So 30000 and 40004 are sent as given.

**+12 and +13 are both labelled "Target".** Neither is documented as a measured
position, and this map exposes no other angle, so what is logged here may be
what the controller intends rather than where the tracker is. The vendor builds
single- and dual-axis trackers on one register template, so the two are
plausibly two axes; the alternative reading is that +12 is the actual angle and
its label is a translation artifact. The AO sheet writes only +13 ("Target
Corner", manual mode only), which argues for the second reading. Until hardware
settles it, both fields carry the workbook's own words and invent nothing. One
day of automatic-mode data decides it: an angle that lags its neighbour is a
measurement, and two that move independently are two axes.

**Fault is a code, not a bitfield.** The workbook defines no bit meanings for
it anywhere, so it is emitted whole rather than expanded into invented flags.
The one legend the workbook does carry is for working mode: 0 maintenance,
1 automatic, 2 manual, 3 wind shelter, 4 snow removal, 5 rain, 6 stop,
7 levelling.

Of the fifteen registers per tracker, three are emitted. The rest are either
static installation data (coordinates, time zone) or a clock, and republishing
them every minute per tracker costs series without carrying information. They
are still read -- they sit inside the block sweep and cost nothing -- so adding
one is a single line here, per-tracker working mode most likely of all.
"""

import re

from solarian.decode import I16, U16, Raw
from solarian.driver import Driver, Block, IntOption
from solarian.modbus import HOLDING

# The controller's own block, and the repeating slot after it.
HEADER_ADDRESS = 30000
HEADER_COUNT = 16
FIRST_TRACKER_ADDRESS = 40004
REGISTERS_PER_TRACKER = 15
MAX_TRACKERS = 181

# One Modbus request returns at most 125 registers, and a tracker split across
# two requests would be a slot whose offsets no longer line up with the
# template. Eight whole trackers is 120 registers: the most that fits.
TRACKERS_PER_BLOCK = 125 // REGISTERS_PER_TRACKER

_FAULT_FIELD = re.compile(r'^T\d{3}_Fault$')


def tracker_tag(number):
    """Field-name prefix for one tracker, zero-padded so series sort in order."""
    return 'T%03d_' % number


def build_blocks(options):
    """The register map for a controller fronting `tracker_count` trackers."""
    count = options['tracker_count']

    blocks = [Block('controller', HOLDING, HEADER_ADDRESS, HEADER_COUNT, [
        Raw(0, 'Working_Mode'),
        # The controller's own view of which trackers it owns. Static, but two
        # registers already on the wire: logging them turns a mismatched
        # tracker_count from a silent short read into a visible disagreement.
        Raw(1, 'Start_Address'),
        Raw(2, 'End_Address'),
        U16(14, 'Wind_Speed', divide=100, unit='m/s'),
        U16(15, 'Wind_Direction', unit='deg'),
    ])]

    for first in range(1, count + 1, TRACKERS_PER_BLOCK):
        last = min(first + TRACKERS_PER_BLOCK - 1, count)
        fields = []
        for number in range(first, last + 1):
            base = REGISTERS_PER_TRACKER * (number - first)
            tag = tracker_tag(number)
            fields.extend([
                I16(base + 12, tag + 'Target_Inclination', divide=100, unit='deg'),
                I16(base + 13, tag + 'Target_Tilt_Angle', divide=100, unit='deg'),
                Raw(base + 14, tag + 'Fault'),
            ])
        blocks.append(Block(
            'trackers_%03d_%03d' % (first, last), HOLDING,
            FIRST_TRACKER_ADDRESS + REGISTERS_PER_TRACKER * (first - 1),
            REGISTERS_PER_TRACKER * (last - first + 1), fields))

    return blocks


def summarise(values, blocks, device):
    """Fleet totals, so a site with 181 trackers has something to alarm on.

    Per-tracker fault codes are what you need once you know something is wrong;
    they are not what you watch. These two series are.
    """
    faults = [value for name, value in values.items() if _FAULT_FIELD.match(name)]
    values['Trackers_Polled'] = float(len(faults))
    values['Trackers_Faulted'] = float(sum(1 for value in faults if value))


DRIVER = Driver(
    name='ESET_TRACKER_SUBARRAY',
    version='0.1',
    description='Eset tracker sub-array controller over Modbus TCP',
    options=[
        IntOption('tracker_count', 1, MAX_TRACKERS, example=TRACKERS_PER_BLOCK,
                  help='trackers this controller fronts, 1..%d. Required: the '
                       'controller answers for exactly as many as it was '
                       'installed with, and reading past the last one fails '
                       'the whole device.' % MAX_TRACKERS),
    ],
    blocks=build_blocks,
    postprocess=summarise,
)
