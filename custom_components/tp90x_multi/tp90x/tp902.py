"""TP902 concrete model implementation.
TP902 has 6 channels and supports backlight control"""

from .tp90xbase import TP90xBase


class TP902(TP90xBase):
    """ThermoPro TP902 protocol model."""

    NUM_PROBES = 6

    @classmethod
    def model_name(cls):
        """Model Name - TP902"""
        return "TP902"
