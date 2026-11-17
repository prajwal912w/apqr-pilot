from decimal import Decimal
from analysis import check_spec
from analysis import compute_stats

def test_pass_within_limits():
    assert check_spec(Decimal("99.5"), Decimal("98"), Decimal("102")) == "PASS"

def test_oos_below_lsl():
    assert check_spec(Decimal("97"), Decimal("98"), Decimal("102")) == "OOS"

def test_oos_above_usl():
    assert check_spec(Decimal("103"), Decimal("98"), Decimal("102")) == "OOS"

def test_one_sided_usl_only():
    assert check_spec(Decimal("50"), None, Decimal("102")) == "PASS"
    assert check_spec(Decimal("103"), None, Decimal("102")) == "OOS"

def test_exactly_on_limit_passes():
    assert check_spec(Decimal("98"), Decimal("98"), Decimal("102")) == "PASS"

def test_stats_basic():
    values = [Decimal("98"), Decimal("99"), Decimal("100"), Decimal("101"), Decimal("102")]
    stats = compute_stats(values, Decimal("95"), Decimal("105"))
    assert stats["count"] == 5
    assert stats["mean"] == 100.0
    assert stats["min"] == 98.0
    assert stats["max"] == 102.0
    assert stats["cpk"] is not None

def test_stats_one_sided():
    values = [Decimal("1"), Decimal("2"), Decimal("3")]
    stats = compute_stats(values, None, Decimal("10"))
    assert stats["cpk"] is not None
