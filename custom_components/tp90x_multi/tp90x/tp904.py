"""TP904 has 2 probes. It's alarm setting mechanism differs from the TP902"""

from .tp90xbase import TP90xBase


class TP904(TP90xBase):
    """ThermoPro TP904 protocol model."""

    NUM_PROBES = 2

    @classmethod
    def model_name(cls):
        """Model Name - TP904"""
        return "TP904"
