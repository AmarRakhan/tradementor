"""Pure partial-position close calculations for safe simulation tests."""

from __future__ import annotations


ALLOWED_CLOSE_PERCENTAGES = (25, 50, 75, 100)


def close_size(position_size: float, percentage: int) -> float:
    if percentage not in ALLOWED_CLOSE_PERCENTAGES:
        raise ValueError("sluitpercentage moet 25, 50, 75 of 100 zijn")
    size = abs(float(position_size))
    if size <= 0:
        raise ValueError("positieomvang ontbreekt")
    return size if percentage == 100 else size * percentage / 100.0

