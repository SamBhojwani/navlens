"""Unit tests for the coarse category mapping."""
import pytest

from navlens.config import coarse_category


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Open Ended Schemes(Equity Scheme - Large Cap Fund)", "Equity"),
        ("Equity Scheme - ELSS", "Equity"),
        ("Debt Scheme - Banking and PSU Fund", "Debt"),
        ("Debt Scheme - Liquid Fund", "Debt"),
        ("Hybrid Scheme - Balanced Advantage", "Hybrid"),
        ("Other Scheme - Index Funds", "Index/ETF"),
        ("Other Scheme - FoF Overseas", "Fund of Funds"),
        ("Solution Oriented Scheme - Retirement Fund", "Solution Oriented"),
        ("Some Unknown Scheme Type", "Other"),
        ("", "Other"),
    ],
)
def test_coarse_category(text, expected):
    assert coarse_category(text) == expected
