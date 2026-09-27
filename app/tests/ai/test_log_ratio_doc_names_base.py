# -*- coding: utf-8 -*-
"""The tool description names the logarithm base used by log_ratio."""

from __future__ import annotations

import math
import re

from candyconc.candyconc_copilot.prompts import TOOLS_DOC
from candyconc.core.significance import log_ratio_ci


def test_die_doku_nennt_log2_und_die_rechnung_ist_log2():
    treffer = re.search(r"EFFEKTSTÄRKE: log_ratio \((log\w*),", TOOLS_DOC)
    assert treffer and treffer.group(1) == "log2", "keyness nennt die Basis von log_ratio nicht"
    tief, hoch = log_ratio_ci(1000, 100, 1_000_000, 1_000_000)
    punkt = math.log2(1000.5 / 100.5)
    assert tief < punkt < hoch
    assert abs(punkt - math.log(1000.5 / 100.5)) > 1, "die Probe muss die Basen trennen"
