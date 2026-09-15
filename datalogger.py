#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
#
#    Solarian Datalogger - A datalogging software for solar systems
#    Copyright (C) 2020 Orçun Başlak
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Entry point. The program itself lives in the `solarian` package.

Kept as datalogger.py so existing crontabs, systemd units and the documented
`python3 datalogger.py` invocation continue to work unchanged.
"""

import os
import sys

# Allow running from any working directory, which is how cron invokes this.
# The previous version called os.chdir() to achieve the same thing; adjusting
# sys.path instead avoids changing global process state that everything else
# then depends on.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solarian.cli import main

if __name__ == '__main__':
    sys.exit(main())
