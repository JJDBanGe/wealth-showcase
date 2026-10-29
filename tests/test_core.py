from datetime import date
from wealth_os import config, core

def _txn(year, month, day, cat, hkd):
    return {"date": f"{year}-{month:02d}-{day:02d}", "year": year,
            "month": month, "cat": cat, "hkd": hkd}

def test_fv_basic():
    r = 0.01
    n = 100
    expected = 100000 * (1 + r) ** n
    assert abs(core.fv(100000, 0, r, n) - expected) < 1

def test_fv_with_periodic_invest():
    r = 0.01
    n = 12
    f = (1 + r) ** n
    expected = 1000 * f + 100 * (f - 1) / r
    assert abs(core.fv(1000, 100, r, n) - expected) < 1e-6

def test_fv_zero_rate():
    assert core.fv(1000, 100, 0, 12) == 1000 + 100 * 12

def test_fire_target_from_swr():
    """FIRE 目标由 SWR 推导（月成本 × 12 ÷ SWR ÷ 汇率），默认取阶梯最高一级的月成本。"""
    cost = config.FREEDOM_LADDER[-1][2]
    assert abs(core.fire_target_usd(7.8) - cost * 12 / config.SWR / 7.8) < 1
    assert abs(core.fire_target_usd(7.8, monthly_cost_hkd=26000) - 26000 * 12 / config.SWR / 7.8) < 1
    # SWR 变小 → 目标变大（口径联动）
    assert core.fire_target_usd(7.8, 26000) > 26000 * 12 / 0.04 / 7.8

def test_compute_cashflow_month_scope():
    txns = [
        _txn(2026, 7, 5, "饮食", 1000),
        _txn(2026, 8, 5, "饮食", 2000),
        _txn(2026, 8, 6, "交通", 300),
        _txn(2026, 9, 5, "饮食", 500),
    ]
    cf = core.compute_cashflow(salary=30000, rent=7000, utility=0, txns=txns,
                               opt_usd=2000, usd_hkd=7.8, month_key="2026-08")
    assert cf["total_spend"] == 2300          # 只含 8 月
    assert cf["essential_base"] == 2300
    assert cf["month_key"] == "2026-08"

def test_compute_cashflow_default_latest_month():
    txns = [
        _txn(2026, 7, 5, "饮食", 1000),
        _txn(2026, 9, 5, "饮食", 500),
    ]
    cf = core.compute_cashflow(salary=30000, rent=7000, utility=0, txns=txns,
                               opt_usd=2000, usd_hkd=7.8)
    assert cf["month_key"] == "2026-09"
    assert cf["total_spend"] == 500
    assert cf["latest_date"] == "2026-09-05"

def test_cash_panel_spendable_and_months():
    """可花现金 = 银行余额 + IBKR 现金 − 应急金；应急金 = EMERGENCY_MONTHS ×（房租 + 必要消费）。"""
    txns = [_txn(2026, 9, 5, "饮食", 500), _txn(2026, 9, 6, "交通", 100)]
    cf = core.compute_cashflow(salary=30000, rent=7000, utility=0, txns=txns,
                               opt_usd=2000, usd_hkd=7.8, month_key="2026-09")
    panel = core.cash_panel(cf, usd_hkd=7.8, bank_balance_hkd=50000,
                            ibkr_cash_usd=5000, bank_balance_date=None)
    essential = cf["rent"] + cf["essential_base"]            # 7000 + (500 饮食 + 100 交通)
    assert abs(panel["essential_monthly"] - essential) < 1e-6
    assert abs(panel["emergency_hkd"] - essential * config.EMERGENCY_MONTHS) < 1e-6
    assert abs(panel["cash_hkd"] - (50000 + 5000 * 7.8)) < 1e-6
    assert abs(panel["spendable_hkd"] - (panel["cash_hkd"] - panel["emergency_hkd"])) < 1e-6
    assert abs(panel["months_cover"] - panel["cash_hkd"] / essential) < 1e-6

def test_cash_panel_handles_missing_sources():
    """没接 IBKR Flex（现金为 None）时按 0 算，不报错；这时可花现金通常为负（应急金还没存够）。"""
    txns = [_txn(2026, 9, 5, "饮食", 500)]
    cf = core.compute_cashflow(salary=30000, rent=7000, utility=0, txns=txns,
                               opt_usd=0, usd_hkd=7.8, month_key="2026-09")
    panel = core.cash_panel(cf, usd_hkd=7.8, bank_balance_hkd=None, ibkr_cash_usd=None)
    assert panel["bank_hkd"] is None and panel["ibkr_usd"] is None
    assert panel["cash_hkd"] == 0.0 and panel["spendable_hkd"] < 0

def test_cash_panel_deducts_outstanding_credit_card_debt():
    """债务按未偿还余额扣一次，同时影响可花金额与必要支出覆盖月数。"""
    cf = {"rent": 7000, "essential_base": 3000}
    from datetime import date
    day = date(2026, 9, 30)
    panel = core.cash_panel(cf, 7.8, bank_balance_hkd=50000, ibkr_cash_usd=5000,
                            bank_balance_date=day, credit_card_debt_hkd=10000,
                            credit_card_debt_date=day)
    assert panel["gross_cash_hkd"] == 89000
    assert panel["cash_hkd"] == 79000
    assert panel["spendable_hkd"] == 79000 - config.EMERGENCY_MONTHS * 10000
    assert panel["months_cover"] == 7.9
    assert not panel["credit_debt_missing"] and not panel["credit_date_mismatch"]
    zero = core.cash_panel(cf, 7.8, bank_balance_hkd=50000, credit_card_debt_hkd=0)
    unknown = core.cash_panel(cf, 7.8, bank_balance_hkd=50000)
    assert zero["cash_hkd"] == unknown["cash_hkd"]
    assert not zero["credit_debt_missing"] and unknown["credit_debt_missing"]

def test_cash_panel_credit_card_snapshot_date_mismatch():
    """不同日期的快照必须标记，不能默认为余额已经核对。"""
    from datetime import date
    panel = core.cash_panel({}, 7.8, bank_balance_hkd=50000,
                            bank_balance_date=date(2026, 9, 30), credit_card_debt_hkd=10000,
                            credit_card_debt_date=date(2026, 10, 13))
    assert panel["credit_date_mismatch"]

def test_months_of():
    txns = [_txn(2026, 7, 5, "饮食", 1), _txn(2026, 9, 5, "饮食", 1)]
    assert core.months_of(txns) == ["2026-07", "2026-09"]
    assert core.latest_month(txns) == "2026-09"
    assert core.latest_month([]) is None

def test_cat_agg_month_filter():
    txns = [_txn(2026, 7, 5, "饮食", 100), _txn(2026, 8, 5, "饮食", 200)]
    assert core.cat_agg(txns, "2026-07")["饮食"] == 100
    assert core.cat_agg(txns)["饮食"] == 300

def test_month_completeness_in_progress():
    """计算月就是当前月：标为月度至今（边界：最后交易日 = 今天）。"""
    level, note = core.month_completeness("2026-09", "2026-09-25", today=date(2026, 9, 25))
    assert level == "in_progress"
    assert "月度至今" in note and "2026-09-25" in note

def test_month_completeness_past_month_with_gap():
    """计算月已结束且月末缺口超过宽限天数：提示可能未导入齐全。"""
    level, note = core.month_completeness("2026-08", "2026-08-20", today=date(2026, 9, 25))
    assert level == "gap"
    assert "2026-08" in note and "2026-08-20" in note

def test_month_completeness_past_month_complete():
    """计算月已结束：月末最后一天、或缺口在宽限天数内，都算完整。"""
    assert core.month_completeness("2026-08", "2026-08-31", today=date(2026, 9, 25)) == ("complete", "")
    assert core.month_completeness("2026-08", "2026-08-29", today=date(2026, 9, 25)) == ("complete", "")
    assert core.month_completeness("2026-02", "2026-02-26", today=date(2026, 9, 25)) == ("complete", "")

def test_month_completeness_empty():
    """无数据时不提示。"""
    assert core.month_completeness(None, None) == ("complete", "")

def test_spend_thresholds_by_distribution():
    """单笔免审 = 窗口内单笔消费的 75 分位；冷静期 = 窗口内月均消费 × 15%；都在限幅内。"""
    txns = []
    # 3 个月，每月 4 笔：50 / 100 / 200 / 400 → 月均消费 750，单笔 P75 = 250
    for m in (7, 8, 9):
        for amt in (50, 100, 200, 400):
            txns.append({"date": f"2026-{m:02d}-05", "year": 2026, "month": m,
                         "desc": "x", "cat": "饮食", "src": "t", "hkd": float(amt)})
    thr = core.spend_thresholds(txns, "2026-09")
    assert thr["sample"] == 12
    assert abs(thr["monthly_avg"] - 750.0) < 1e-9
    # 原始 P75 = 250 → 被 free_cap(200) 截断
    assert abs(thr["raw_free"] - 250.0) < 1e-9
    assert thr["free"] == config.MIND_SPEND["free_cap"]
    # 原始冷静期 = 750 × 15% = 112.5 → 被 cooling_floor(300) 抬到 300
    assert abs(thr["raw_cooling"] - 112.5) < 1e-9
    assert thr["cooling"] == config.MIND_SPEND["cooling_floor"]
    assert thr["cooling_hits"] == 3          # 每月那笔 400 ≥ 300
    assert thr["month_hits"] == 1

def test_spend_thresholds_window_and_floor():
    """只统计窗口内的月份；数据很少时用下限定幅，避免阈值小得没意义。"""
    txns = [{"date": "2026-05-05", "year": 2026, "month": 5, "desc": "x",
             "cat": "饮食", "src": "t", "hkd": 1000.0},          # 窗口外，不该算进来
            {"date": "2026-09-05", "year": 2026, "month": 9, "desc": "x",
             "cat": "饮食", "src": "t", "hkd": 20.0}]
    thr = core.spend_thresholds(txns, "2026-09")
    assert thr["sample"] == 1 and thr["window"] == ["2026-09", "2026-08", "2026-07"]
    assert thr["free"] == config.MIND_SPEND["free_floor"]      # 20 → 抬到下限 50
    assert thr["cooling"] == config.MIND_SPEND["cooling_floor"]
