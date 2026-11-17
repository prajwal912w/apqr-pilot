from analysis import check_spec, compute_stats


# --- check_spec: pass/oos against limits ---

def test_two_sided_pass_and_oos():
    assert check_spec(100, 95, 105) == "PASS"
    assert check_spec(94.9, 95, 105) == "OOS"
    assert check_spec(105.1, 95, 105) == "OOS"

def test_values_on_the_limits_pass():
    # limits are inclusive
    assert check_spec(95, 95, 105) == "PASS"
    assert check_spec(105, 95, 105) == "PASS"

def test_upper_only_limit():
    assert check_spec(0.9, None, 1.0) == "PASS"
    assert check_spec(1.1, None, 1.0) == "OOS"

def test_lower_only_limit():
    assert check_spec(96, 95, None) == "PASS"
    assert check_spec(94, 95, None) == "OOS"


# --- compute_stats: cpk and edge cases ---

def test_cpk_two_sided_hand_calculated():
    # mean=100, sd=2, usl=105, lsl=95
    # cpu = (105-100)/(3*2) = 0.83 ; cpl = (100-95)/(3*2) = 0.83
    values = [98, 100, 102, 100, 100]
    stats = compute_stats(values, 95, 105)
    assert stats["mean"] == 100.0
    assert stats["cpk"] == round(min((105-100)/(3*stats["std"]), (100-95)/(3*stats["std"])), 2)

def test_cpk_upper_only():
    from statistics import mean, stdev
    values = [0.2, 0.3, 0.25, 0.28, 0.22]
    stats = compute_stats(values, None, 1.0)
    expected = round((1.0 - mean(values)) / (3 * stdev(values)), 2)
    assert stats["cpk"] == expected

def test_cpk_lower_only():
    from statistics import mean, stdev
    values = [96, 97, 98, 99, 100]
    stats = compute_stats(values, 95, None)
    expected = round((mean(values) - 95) / (3 * stdev(values)), 2)
    assert stats["cpk"] == expected

def test_single_result_does_not_crash():
    stats = compute_stats([99.5], 95, 105)
    assert stats["count"] == 1
    assert stats["cpk"] is None  # no spread, so no meaningful cpk

def test_identical_values_give_no_cpk():
    stats = compute_stats([100, 100, 100, 100], 95, 105)
    assert stats["std"] == 0.0
    assert stats["cpk"] is None  # zero sd would divide by zero

def test_stats_fields():
    stats = compute_stats([96.86, 100.44, 103.97], 95, 105)
    assert stats["count"] == 3
    assert stats["min"] == 96.86
    assert stats["max"] == 103.97
