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


# --- validate_row: csv cleaning and rejection ---

def make_row(**kw):
    base = {"product": "Paracetamol Tablets 500 mg", "batch_no": "PCT2601",
            "parameter": "Assay", "unit": "%", "result": "99.5",
            "lsl": "95", "usl": "105", "mfg_date": "2026-01-05"}
    base.update(kw)
    return base

def test_valid_row_passes():
    from analysis import validate_row
    errors, cleaned = validate_row(make_row())
    assert errors == []
    assert cleaned["result"] == 99.5
    assert cleaned["batch_no"] == "PCT2601"

def test_whitespace_only_batch_rejected():
    from analysis import validate_row
    errors, _ = validate_row(make_row(batch_no="   "))
    assert any("batch_no" in e for e in errors)

def test_missing_cells_do_not_crash():
    from analysis import validate_row
    # DictReader gives None for missing cells in short rows
    errors, cleaned = validate_row(make_row(lsl=None, usl=None))
    assert any("no specification limit" in e for e in errors)
    assert cleaned["lsl"] is None and cleaned["usl"] is None

def test_missing_usl_cell_is_one_sided_not_a_crash():
    from analysis import validate_row
    errors, cleaned = validate_row(make_row(usl=None))
    assert errors == []
    assert cleaned["usl"] is None and cleaned["lsl"] == 95.0

def test_nan_and_inf_rejected():
    from analysis import validate_row
    errors, _ = validate_row(make_row(result="nan"))
    assert any("finite" in e for e in errors)
    errors, _ = validate_row(make_row(result="inf"))
    assert any("finite" in e for e in errors)

def test_lsl_above_usl_rejected():
    from analysis import validate_row
    errors, _ = validate_row(make_row(lsl="105", usl="95"))
    assert any("greater" in e for e in errors)

def test_bad_date_rejected():
    from analysis import validate_row
    errors, _ = validate_row(make_row(mfg_date="05-01-2026"))
    assert any("mfg_date" in e for e in errors)


# --- parameter_stats: one source of truth for cpk ---

def test_spec_change_makes_cpk_not_comparable():
    from analysis import parameter_stats
    values = [98, 100, 102, 100]
    limits = [(95, 105), (95, 105), (90, 110), (90, 110)]
    stats = parameter_stats(values, limits)
    assert stats["spec_changed"] is True
    assert stats["cpk"] is None  # not comparable, not silently first/last

def test_stable_spec_keeps_cpk():
    from analysis import parameter_stats
    values = [98, 100, 102, 100]
    stats = parameter_stats(values, [(95, 105)] * 4)
    assert stats["spec_changed"] is False
    assert stats["cpk"] is not None

def test_one_sided_spec_in_parameter_stats():
    from analysis import parameter_stats
    stats = parameter_stats([0.2, 0.3, 0.25, 0.28], [(None, 1.0)] * 4)
    assert stats["cpk"] is not None
    assert stats["lsl"] is None and stats["usl"] == 1.0
