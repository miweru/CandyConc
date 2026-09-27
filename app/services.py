"""Compatibility stub importing :mod:`candyconc.services`."""
import importlib
import sys

module = importlib.import_module("candyconc.services")
sys.modules[__name__] = module
