import math

from reason8.markdown import clock, table


def test_table():
    assert table(["a", "b"], [[1, "x"]]) == ["| a | b |", "| --- | --- |", "| 1 | x |"]


def test_clock():
    assert clock(0) == "0:00"
    assert clock(245 * 30 + 29) == "4:05"
    assert clock(245.5 * 30) == "4:05"
    assert clock(math.inf) == "none"
