
"""核心计算层：纯业务逻辑，无外观代码。输入数据→输出指标，不碰 HTML/SVG。
所有"月"口径指标一律基于指定月份（month_key）的交易计算，不混入历史累计。"""
import calendar
import math
from collections import defaultdict
from datetime import date

from . import config


def performance_without_flows(returns):
    """按日期与日收益构建无外部现金流的收益链；TWR与MWR在此条件下相等。"""
    from datetime import timedelta
    if not returns:
        raise ValueError('需要至少一个日收益')
    start = returns[0][0] - timedelta(days=1)
    level = 1.0
    series = [[str(start), 0.0, 0.0]]
    previous = start
    for day, daily in returns:
        if day <= previous or not math.isfinite(daily) or daily <= -1:
            raise ValueError('日期须递增，日收益须为有限且大于-1的数')
        level *= 1 + daily
        total = (level - 1) * 100
        series.append([str(day), total, total])
        previous = day
    days = (previous - start).days
    annual = level ** (365 / days) - 1
    return dict(start=str(start), end=str(previous), days=days, partial=True,
                twr_total=level - 1, twr_annual=annual, mwr_total=level - 1,
                mwr_annual=annual, series=series)


def equity_concentration(positions):
    """按正股/基金总市值计算集中度，返回权重、行业权重与 HHI（0~10000）。"""
    positive = [p for p in positions if p.get("value", 0) > 0]
    total = sum(p["value"] for p in positive)
    if not total:
        return None
    rows = sorted(({**p, "equity_weight": p["value"] / total * 100}
                   for p in positive), key=lambda p: p["value"], reverse=True)
    groups = defaultdict(float)
    for p in rows:
        groups[config.INDUSTRY_GROUPS.get(p["industry"], "其他")] += p["equity_weight"]
    largest = max(groups, key=groups.get)
    return {"total": total, "rows": rows, "groups": dict(groups),
            "largest": rows[0], "top3": sum(p["equity_weight"] for p in rows[:3]),
            "top5": sum(p["equity_weight"] for p in rows[:5]),
            "largest_industry": largest, "industry_weight": groups[largest],
            "hhi": sum(p["equity_weight"] ** 2 for p in rows)}


def equity_drawdown(returns, allocation=None, concentration=None, threshold=-10.0):
    """构建 TWR 回撤并提取超过阈值的完整区间；可用仓位快照生成可核验的原因提示。"""
    if not returns:
        return None
    level = peak = 100.0
    worst = 0.0
    series = []
    for day, daily_return in returns:
        if not math.isfinite(daily_return) or daily_return <= -1:
            return None
        level *= 1 + daily_return
        peak = max(peak, level)
        dd = (level / peak - 1) * 100
        worst = min(worst, dd)
        series.append((str(day), level, dd))
    episodes = []
    active = None
    for idx, (day, level_value, dd) in enumerate(series):
        if dd <= threshold and active is None:
            peak_idx = max(range(idx + 1), key=lambda n: series[n][1])
            active = {"peak": series[peak_idx], "trough": (day, level_value, dd), "end": None}
        elif active is not None:
            if dd < active["trough"][2]:
                active["trough"] = (day, level_value, dd)
            if dd >= 0:
                active["end"] = (day, level_value, dd)
                episodes.append(active)
                active = None
    if active is not None:
        episodes.append(active)
    allocation = allocation or []
    allocation_by_day = {str(row[0]): row for row in allocation}
    for episode in episodes:
        peak_day, trough_day = episode["peak"][0], episode["trough"][0]
        peak_alloc, trough_alloc = allocation_by_day.get(peak_day), allocation_by_day.get(trough_day)
        reasons = []
        if concentration:
            reasons.append(f"组合最大行业为 {concentration['largest_industry']}（{concentration['industry_weight']:.1f}%），集中仓位会放大同一主题的同步波动")
        if peak_alloc and trough_alloc:

            if trough_alloc[2] >= 80:
                reasons.append(f"回撤低点股票占总资产 {trough_alloc[2]:.1f}%，现金缓冲较少")
            if trough_alloc[3] < peak_alloc[3] - 2:
                reasons.append("期权占比在区间内下降，期权负债/平仓波动可能放大净值变化")
            if trough_alloc[1] < 0:
                reasons.append(f"回撤低点现金占比为负（{trough_alloc[1]:.1f}%），存在保证金放大效应")
        episode["reason"] = "；".join(reasons) if reasons else "现有数据只能确认组合层面的回撤，无法把跌幅精确归因到单只证券；需补充逐日持仓/价格贡献数据。"
        episode["recovery"] = None if episode["end"] is None else (episode["end"][0] > episode["trough"][0])
    return {"peak": peak, "level": level, "current": series[-1][2], "worst": worst,
            "recovery": (peak / level - 1) * 100, "series": series,
            "start": series[0][0], "end": series[-1][0], "episodes": episodes,
            "threshold": threshold}


def equity_rebalance(concentration, targets=None, band=None):
    """比较当前股票内部权重与用户目标；未配置不生成交易建议，偏离按百分点计。"""
    targets = config.EQUITY_TARGETS if targets is None else targets
    band = config.EQUITY_REBALANCE_BAND_PP if band is None else band
    if band < 0:
        raise ValueError("再平衡容忍区间不能为负")
    rows = []
    if not concentration:
        return rows


    all_industries = set(concentration["groups"]) | set(config.EQUITY_TARGETS.get("industry", {}))
    for kind, current in (("symbol", {p["symbol"]: p["equity_weight"] for p in concentration["rows"]}),

                          ("industry", {name: concentration["groups"].get(name, 0.0) for name in sorted(all_industries)})):
        configured = targets.get(kind, {})
        if any(not math.isfinite(v) or not 0 <= v <= 100 for v in configured.values()) or sum(configured.values()) > 100 + 1e-8:
            raise ValueError("目标权重必须在0~100之间，且同一维度合计不能超过100%")
        for name in sorted(set(current) | set(configured)):
            weight, target = current.get(name, 0), configured.get(name)
            delta = weight - target if target is not None else None
            rows.append({"kind": kind, "name": name, "weight": weight, "target": target,
                         "delta": delta, "status": "待设定" if delta is None else
                         ("超配 · 复核" if delta > band else "低配 · 复核" if delta < -band else "区间内")})
    return rows


def equity_fundamental_rows(positions, snapshots, today=None):
    """筛选最新基本面快照，保留空值；历史估值分位仅比较同一来源的正值P/E。"""
    today = today or date.today()
    rows = []
    for p in positions:
        records = sorted((r for r in snapshots if r.get("symbol") == p["symbol"] and
                          r.get("date", "") <= today.isoformat()), key=lambda r: r["date"])
        latest = dict(records[-1]) if records else {"symbol": p["symbol"]}
        if latest.get("free_cash_flow") is not None and latest.get("market_cap", 0):
            latest["fcf_yield"] = latest["free_cash_flow"] / latest["market_cap"] * 100
        industry = p.get("industry", "")
        latest["fund"] = industry in {"科技股ETF", "大盘ETF", "黄金ETF", "科技股封闭式基金"} or latest.get("quote_type") in {"ETF", "MUTUALFUND"}
        latest["stale"] = bool(records) and (today - date.fromisoformat(latest["date"])).days > config.EQUITY_FUNDAMENTALS["stale_days"]
        history = {r["date"]: r["pe"] for r in records if r.get("pe") is not None and
                   r["pe"] > 0 and r.get("source") == latest.get("source")}
        latest["samples"] = len(history)
        latest["pe_percentile"] = (sum(v <= latest["pe"] for v in history.values()) / len(history) * 100
                                  if len(history) >= config.EQUITY_FUNDAMENTALS["history_min_samples"] and latest.get("pe", 0) and latest["pe"] > 0 else None)
        latest["history_start"] = min(history) if history else None
        rows.append(latest)
    return rows


def fmt(x):
    return f"{x:,.0f}"


def fmt2(x):
    return f"{x:,.2f}"


def fv(p0, p, r, n):
    """复利终值：p0 初始 + p 每期定投 × n 期，r 月利率。r=0 时退化为线性。"""
    if r == 0:
        return p0 + p * n
    f = (1 + r) ** n
    return p0 * f + p * (f - 1) / r


def fire_target_usd(usd_hkd, monthly_cost_hkd=None):
    """FIRE 目标净资产（USD）＝ 月成本 × 12 ÷ SWR ÷ 汇率。
    默认取财富自由阶梯最高一级（FIRE）的月成本，保证「FIRE 目标」与「财富自由阶梯」同一口径，
    因此调整 config.SWR 会同时影响滚雪球、大额支出与阶梯三处。"""
    cost = config.FREEDOM_LADDER[-1][2] if monthly_cost_hkd is None else monthly_cost_hkd
    return cost * 12 / config.SWR / usd_hkd


def fire_year(p0, p, r, target, max_years=60):
    """达到 FIRE 目标（target，USD）所需年数（整数年）。"""
    for y in range(1, max_years + 1):
        if fv(p0, p, r, y * 12) >= target:
            return y
    return None


def cat_agg(txns, month_key=None):
    """按品类聚合消费金额。month_key 为 None 时聚合全部交易。"""
    agg = defaultdict(float)
    for t in txns:
        if month_key and f"{t['year']}-{t['month']:02d}" != month_key:
            continue
        agg[t["cat"]] += t["hkd"]
    return agg


def months_of(txns):
    """全部交易覆盖的月份列表（升序），如 ['2026-07', '2026-08', '2026-09']。"""
    return sorted({f"{t['year']}-{t['month']:02d}" for t in txns})


def latest_month(txns):
    """最新月份（计算月）。无交易时返回 None。"""
    months = months_of(txns)
    return months[-1] if months else None


def month_completeness(month_key, latest_date, today=None, grace_days=config.PARTIAL_MONTH_GRACE_DAYS):
    """判断计算月的数据是否完整，供报告展示提醒。
    输入：month_key（YYYY-MM）、latest_date（数据中最后一笔交易日 YYYY-MM-DD）、
    today（默认取今天）、grace_days（月末宽限天数）。
    返回 (level, note)：
      - in_progress：计算月就是当前月，本月尚未结束，数字为月度至今口径
      - gap：计算月已结束，但最后交易日距该月月末超过 grace_days 天，账单可能未导入齐全
      - complete：数据覆盖完整（note 为空串）
    """
    if not month_key or not latest_date:
        return "complete", ""
    year, month = int(month_key[:4]), int(month_key[5:7])
    today = today or date.today()
    if (year, month) == (today.year, today.month):
        return "in_progress", f"（本月进行中，数据截至 {latest_date}，为「月度至今」口径）"
    if (year, month) > (today.year, today.month):
        return "complete", ""
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    gap = (month_end - date.fromisoformat(latest_date)).days
    if gap > grace_days:
        return "gap", f"（{month_key} 最后交易 {latest_date}，距月末 {gap} 天无账单，可能未导入齐全）"
    return "complete", ""


def _percentile(values, pct):
    """线性插值分位数（pct: 0~1）。values 需已升序排序。"""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    pos = pct * (len(values) - 1)
    low = int(pos)
    high = min(low + 1, len(values) - 1)
    frac = pos - low
    return values[low] * (1 - frac) + values[high] * frac


def spend_thresholds(txns, month_key, cfg=None):
    """按你自己的消费分布算两个阈值（不再跟当月收入挂钩）：

    - 单笔免审 = 滚动窗口内单笔消费的 75 分位（限幅）——「日常不用想」的边界。
      可检验：它应该放行大多数笔数，但只占少部分金额。
    - 冷静期阈值 = 滚动窗口内月均消费 × 15%（限幅）——「值得先睡一觉」的边界。

    窗口 = 含计算月在内的最近 cfg["months"] 个月；月均按窗口内实际有数据的月份数算。
    返回两个阈值 + 报告展示需要的元信息（样本、窗口、原始分位/月均、触发率）。
    """
    cfg = cfg or config.MIND_SPEND
    months = int(cfg.get("months", 3))
    window_keys = []
    if month_key:
        y, m = (int(x) for x in month_key.split("-"))
        for i in range(months):
            mm, yy = m - i, y
            while mm <= 0:
                mm += 12
                yy -= 1
            window_keys.append(f"{yy}-{mm:02d}")
    window = [t for t in txns
              if f"{t['year']}-{t['month']:02d}" in window_keys and float(t.get("hkd", 0)) > 0]
    amounts = sorted(float(t["hkd"]) for t in window)
    active_months = len({f"{t['year']}-{t['month']:02d}" for t in window}) or 1
    monthly_avg = sum(amounts) / active_months

    raw_free = _percentile(amounts, cfg.get("free_pct", 0.75))
    raw_cooling = monthly_avg * cfg.get("cooling_pct", 0.15)
    free = min(max(raw_free, cfg.get("free_floor", 0.0)), cfg.get("free_cap", raw_free))
    cooling = min(max(raw_cooling, cfg.get("cooling_floor", 0.0)), cfg.get("cooling_cap", raw_cooling))
    return {
        "free": free,
        "cooling": cooling,
        "raw_free": raw_free,
        "raw_cooling": raw_cooling,
        "months": months,
        "window": window_keys,
        "active_months": active_months,
        "sample": len(amounts),
        "monthly_avg": monthly_avg,
        "free_hits": sum(1 for a in amounts if a <= free),
        "cooling_hits": sum(1 for a in amounts if a >= cooling),
        "month_hits": sum(1 for t in window
                          if f"{t['year']}-{t['month']:02d}" == month_key
                          and float(t["hkd"]) >= cooling),
    }


def utility_budget(bills, month_key):
    """返回分服务的月均预算、实际扣款和押金说明，未来扣款不计入历史计算月。

    电费按最新月账单作预算参考；燃气最近两张净费用 / 四个月（一张则 / 两个月）。
    已确认的 600 押金仅扣指定日期及金额的付款。水费无账单暂计 0；有账单需核对覆盖期。
    """
    eligible = sorted((b for b in bills if month_key and b["date"][:7] <= month_key),
                      key=lambda b: (b["date"], b["desc"]))
    groups = defaultdict(list)
    annotated_bills = []
    for bill in eligible:
        deposit = 0.0
        first = config.GAS_FIRST_PAYMENT
        if bill["kind"] == "gas" and first and bill["date"] == first["date"] and abs(bill["hkd"] - first["amount"]) < .005:
            deposit = first["deposit"]
        if not 0 <= deposit <= bill["hkd"]:
            raise ValueError("燃气押金扣除须在 0 与原付款金额之间")
        item = {**bill, "deposit": deposit, "net": bill["hkd"] - deposit}
        annotated_bills.append(item)
        if item["net"] > 0:
            groups[bill["kind"]].append(item)
    components = []
    for kind, label, period in [("electricity", "电费", 1), ("gas", "燃气费", config.GAS_BILL_MONTHS),
                                ("water", "水费", None), ("internet", "网费", 1)]:
        rows = groups[kind][-config.GAS_AVERAGE_BILLS:] if kind == "gas" else groups[kind][-1:]
        if rows and period:
            monthly = sum(r["net"] for r in rows) / (len(rows) * period)
            status = "最新月账单参考" if kind == "electricity" else "按账单周期折算"
        else:
            monthly = config.INTERNET_FIXED if kind == "internet" else (config.WATER_MONTHLY if kind == "water" else 0.0)
            status = "手动计入（Visa 未接入）" if kind == "internet" else ("覆盖期待核对，暂未计入" if rows else "无有效账单，暂计 0")
        usage_month = None
        if kind == "electricity" and rows:
            y, m = map(int, rows[-1]["date"][:7].split("-"))
            usage_month = f"{y if m > 1 else y - 1}-{m - 1 if m > 1 else 12:02d}"
        components.append({"kind": kind, "label": label, "monthly": round(monthly, 2), "status": status,
                           "rows": rows, "coverage_months": len(rows) * period if period else None,
                           "usage_month": usage_month})
    paid = sum(b["hkd"] for b in eligible if b["date"][:7] == month_key)
    internet_paid = any(b["kind"] == "internet" and b["date"][:7] == month_key for b in eligible)
    return {"monthly": round(sum(c["monthly"] for c in components), 2), "components": components,
            "bills": annotated_bills,
            "cash_monthly": round(paid + (0.0 if internet_paid else config.INTERNET_FIXED), 2)}


def compute_cashflow(salary, rent, utility, txns, opt_usd, usd_hkd, invest_usd=config.FIXED_INVEST_USD,
                     month_key=None, fixed_cash=None):
    """
    输入：工资、固定支出、消费明细、期权收入(USD)、汇率、定投(USD)、计算月
    输出：所有核心指标字典。
    口径：month_key 为 None 时取最新月份；月度指标（消费、必要消费、可支配、
    结余、蓄水池）一律只使用该月的交易，杜绝"单月收入 × 累计支出"混算。
    """
    if month_key is None:
        month_key = latest_month(txns)
    month_txns = [t for t in txns if f"{t['year']}-{t['month']:02d}" == month_key] if month_key else []
    latest_date = max((t["date"] for t in txns), default=None)

    opt_hkd = opt_usd * usd_hkd
    invest_hkd = invest_usd * usd_hkd
    salary_remaining = salary - invest_hkd
    fix = rent + utility

    agg = cat_agg(month_txns)
    food_total = agg.get("饮食", 0)
    transport = agg.get("交通", 0)
    essential_base = food_total + transport + utility
    total_spend = sum(t["hkd"] for t in month_txns)


    discretionary = salary_remaining + opt_hkd - rent - essential_base
    mindless_monthly = max(discretionary, 0)

    thr = spend_thresholds(txns, month_key)
    mindless_per_trip = thr["free"]
    mindless_cooling = thr["cooling"]


    actual_discretionary = sum(agg.get(cat, 0) for cat in config.NONESSENTIAL_CATS)
    nonessential_by_cat = {cat: agg.get(cat, 0) for cat in config.NONESSENTIAL_CATS}


    month_surplus = salary_remaining + opt_hkd - fix - total_spend
    cash_fix = fix if fixed_cash is None else fixed_cash
    cash_surplus = salary_remaining + opt_hkd - cash_fix - total_spend

    return {
        "month_key": month_key, "latest_date": latest_date,
        "month_txns_count": len(month_txns),
        "salary": salary, "fix": fix, "rent": rent, "utility": utility, "opt_hkd": opt_hkd, "opt_usd": opt_usd,
        "invest_hkd": invest_hkd, "invest_usd": invest_usd,
        "salary_remaining": salary_remaining,
        "food_total": food_total, "transport": transport,
        "essential_base": essential_base, "total_spend": total_spend,
        "discretionary": discretionary, "mindless_monthly": mindless_monthly,
        "mindless_per_trip": mindless_per_trip, "mindless_cooling": mindless_cooling,
        "spend_thresholds": thr,
        "actual_discretionary": actual_discretionary,
        "nonessential_by_cat": nonessential_by_cat,
        "month_surplus": month_surplus,
        "cash_fix": cash_fix, "cash_surplus": cash_surplus,
        "agg": agg,
    }


def cash_panel(cf, usd_hkd, bank_balance_hkd=None, ibkr_cash_usd=None,
               emergency_months=None, bank_balance_date=None,
               credit_card_debt_hkd=None, credit_card_debt_date=None):
    """方案 A 的锚点：**可花现金** = 真实现金 − 应急金（不用卖股票就能花的上限）。

    - 净现金 = 银行储蓄余额 + IBKR 现金 − 未偿还信用卡欠款（同日期快照，不扣已还款）
    - 未提供欠款时，cash_hkd / spendable_hkd 仅为未扣欠款的上限，credit_debt_missing=True
    - 应急金 = emergency_months × 月必要支出（房租 + 必要消费：饮食 + 交通 + 水电）
    - IBKR 现金为负（用保证金）时按 0 计入可用现金，但要单独标出来
    返回 dict；没有现金流水的项目按 None 记录，报告里显示「—」。
    """
    months = config.EMERGENCY_MONTHS if emergency_months is None else emergency_months
    if credit_card_debt_hkd is not None and (not math.isfinite(credit_card_debt_hkd) or credit_card_debt_hkd < 0):
        raise ValueError("信用卡欠款须为非负有限金额")
    essential = (cf.get("rent", 0.0) or 0.0) + (cf.get("essential_base", 0.0) or 0.0)
    bank_hkd = bank_balance_hkd or 0.0
    ibkr_hkd = (ibkr_cash_usd or 0.0) * usd_hkd
    gross_cash_hkd = bank_hkd + ibkr_hkd
    cash_hkd = gross_cash_hkd - (credit_card_debt_hkd or 0.0)
    emergency = essential * months
    spendable = cash_hkd - emergency
    return {
        "bank_hkd": bank_balance_hkd,
        "bank_date": bank_balance_date,
        "ibkr_usd": ibkr_cash_usd,
        "ibkr_hkd": ibkr_hkd,
        "cash_hkd": cash_hkd,
        "gross_cash_hkd": gross_cash_hkd,
        "credit_card_debt_hkd": credit_card_debt_hkd,
        "credit_card_debt_date": credit_card_debt_date,
        "credit_debt_missing": credit_card_debt_hkd is None,
        "credit_date_mismatch": (bank_balance_date is not None and credit_card_debt_date is not None
                                 and bank_balance_date.strftime("%Y-%m-%d") != credit_card_debt_date.strftime("%Y-%m-%d")),
        "essential_monthly": essential,
        "emergency_months": months,
        "emergency_hkd": emergency,
        "spendable_hkd": spendable,
        "months_cover": (cash_hkd / essential) if essential > 0 else None,
    }


def simulate_snowball(p0_usd, levels, rate_annual, target, years=10):
    """多档定投 × N 年的资产模拟。target = FIRE 目标（USD）。返回 [{label, p, data, fire}]。"""
    r = (1 + rate_annual) ** (1 / 12) - 1
    sim_years = list(range(0, years + 1))
    results = []
    for label, p in levels:
        data = [fv(p0_usd, p, r, y * 12) for y in sim_years]
        fy = fire_year(p0_usd, p, r, target)
        results.append({"label": label, "p": p, "data": data, "fire": fy})
    return results, sim_years


def compute_freedom_ladder(food_month, usd_hkd, p0_usd, monthly_invest, rate_annual):
    """每级自由的目标资产、当前状态、达成年限。"""
    r = (1 + rate_annual) ** (1 / 12) - 1
    items = []
    for name, icon, cost_hkd in config.FREEDOM_LADDER:
        target_usd = cost_hkd * 12 / config.SWR / usd_hkd
        reached = p0_usd >= target_usd
        years_needed = None
        if not reached:
            for y in range(1, 61):
                if fv(p0_usd, monthly_invest, r, y * 12) >= target_usd:
                    years_needed = y
                    break
        items.append({
            "name": name, "icon": icon, "cost_hkd": cost_hkd,
            "target_usd": target_usd, "reached": reached,
            "years_needed": years_needed,

            "progress": min(p0_usd / target_usd, 1.0) if target_usd else 0.0,
        })
    return items


def compute_cat_ranges(txns, agg_all):
    """品类动态区间：数据不足6个月用±25%，满6个月用均值±1σ。"""
    months = months_of(txns)
    ranges = []
    for cat in config.CATS:
        actual = agg_all.get(cat, 0)
        if actual == 0:
            continue
        if len(months) < 6:
            lo, hi = actual * 0.75, actual * 1.25
        else:
            monthly_vals = [cat_agg(txns, m).get(cat, 0) for m in months]
            mean = sum(monthly_vals) / len(monthly_vals)
            std = (sum((v - mean) ** 2 for v in monthly_vals) / len(monthly_vals)) ** 0.5
            lo, hi = mean - std, mean + std
        ranges.append((cat, actual, lo, hi))
    return ranges


def gateway_holdings(snapshot, security_type):
    """将完整 Gateway 快照换算为报告持仓；缺少净值时返回 None 供 Flex 回退。"""
    positions = snapshot.get("positions")
    nav = snapshot.get("nav_usd")
    if positions is None or nav is None or nav <= 0:
        return None
    rows = []
    for position in positions:
        if position["type"] != security_type:
            continue

        if security_type == "STK" and position["value"] <= 0:
            continue
        cost = position["cost"]
        rows.append(dict(position, underlying=position["symbol"], weight=position["value"] / nav * 100,
                         return_pct=position["pnl"] / abs(cost) * 100 if cost else 0,
                         industry=config.STOCK_INDUSTRIES.get(position["symbol"], "待分类")))
    return sorted(rows, key=lambda row: abs(row["value"]), reverse=True)


def option_holding_rows(positions):
    """为已统一美元口径的期权持仓计算成本收益率；None 仍表示数据缺失。"""
    if positions is None:
        return None
    return [dict(row, return_pct=row["pnl"] / abs(row["cost"]) * 100 if row["cost"] else 0)
            for row in positions if row["quantity"] != 0]


def group_option_holdings(positions):
    """只读按标的/到期/币种/规格分组净持仓；不猜分历史策略，所有合约恰好出现一次。"""
    buckets=defaultdict(list)
    for index,row in enumerate(positions or []):
        underlying=row.get('underlying') or row.get('symbol','')
        complete=bool(row.get('expiry') and row.get('right') in ('P','C') and row.get('strike') is not None)
        key=(underlying,row.get('expiry',''),row.get('currency',''),str(row.get('multiplier','')),row.get('trading_class',''),None if complete else index)
        buckets[key].append(dict(row))
    groups=[]
    for key,legs in sorted(buckets.items(),key=lambda item:str(item[0])):
        legs.sort(key=lambda row:(row.get('right',''),row.get('strike') or 0,row.get('description','')))
        quantities=[row.get('quantity') for row in legs]
        equal=all(isinstance(q,(int,float)) and math.isfinite(q) and q and float(q).is_integer() for q in quantities) and len({abs(q) for q in quantities})==1
        puts=sorted((row for row in legs if row.get('right')=='P'),key=lambda row:row['strike'])
        calls=sorted((row for row in legs if row.get('right')=='C'),key=lambda row:row['strike'])
        name='单腿持仓' if len(legs)==1 else '组合净持仓'
        if equal and len(legs)==2:
            pair=puts if len(puts)==2 else calls if len(calls)==2 else []
            if pair and pair[0]['strike']<pair[1]['strike'] and pair[0]['quantity']==-pair[1]['quantity']:
                name=('Bull Put Spread' if pair[0]['quantity']>0 else 'Bear Put Spread') if puts else ('Bull Call Spread' if pair[0]['quantity']>0 else 'Bear Call Spread')
        if equal and len(legs)==4 and len(puts)==len(calls)==2 and puts[0]['strike']<puts[1]['strike']<calls[0]['strike']<calls[1]['strike'] and puts[0]['quantity']>0>puts[1]['quantity'] and calls[0]['quantity']<0<calls[1]['quantity']:
            name='Iron Condor'
        group={'symbol':key[0],'expiry':key[1],'name':name,'legs':legs,'groups':abs(quantities[0]) if equal and name not in ('单腿持仓','组合净持仓') else None}
        for field in ('cost','value','pnl'):
            values=[row.get(field) for row in legs]
            group[field]=sum(values) if all(isinstance(v,(int,float)) and math.isfinite(v) for v in values) else None
        group['return_pct']=group['pnl']/abs(group['cost'])*100 if group['pnl'] is not None and group['cost'] else None
        groups.append(group)
    return groups


def reconstruct_option_strategies(positions, openings):
    """用真实历史委托模板解释当前净仓；仅全量逐腿数量相符时保留原策略结构，不任意配腿。"""
    strategies=[]
    for bucket in group_option_holdings(positions):
        legs=bucket['legs']
        candidates=[row for row in openings or [] if row.get('underlying')==bucket['symbol'] and row.get('expiry')==bucket['expiry'] and row.get('strategy') in ('Bull Put Spread','Iron Condor') and row.get('legs')]
        actual=defaultdict(float)
        for leg in legs:
            actual[(leg.get('right'),leg.get('strike'))]+=leg['quantity']
        expected=defaultdict(float)
        compatible=True
        reference=legs[0]
        for row in candidates:
            for leg in row['legs']:
                for field in ('currency','trading_class'):
                    if leg.get(field) and reference.get(field) and leg[field]!=reference[field]:
                        compatible=False
                if leg.get('multiplier') and reference.get('multiplier') and float(leg['multiplier'])!=float(reference['multiplier']):
                    compatible=False
                expected[(leg['type'],leg['strike'])]+=leg['qty']*(1 if leg['side']=='BUY' else -1)
        actual={key:qty for key,qty in actual.items() if qty}
        expected={key:qty for key,qty in expected.items() if qty}
        if candidates and compatible and expected==actual:
            merged={}
            for row in candidates:
                identity=(row['strategy'],tuple(sorted((leg['type'],leg['strike'],leg['side']) for leg in row['legs'])))
                target=merged.setdefault(identity,{'symbol':bucket['symbol'],'expiry':bucket['expiry'],'name':row['strategy'],'quantity':0,'legs':[dict(leg) for leg in row['legs']],'verified':True})
                target['quantity']+=row['quantity']
            directions=defaultdict(set)
            for target in merged.values():
                for leg in target['legs']:
                    directions[(leg['type'],leg['strike'])].add(leg['side'])
            for target in merged.values():
                for leg in target['legs']:
                    leg['qty']=target['quantity']

                    leg['offset']=len(directions[(leg['type'],leg['strike'])])>1
                    if leg['offset']:
                        leg['offset_key']=[bucket['symbol'],bucket['expiry'],reference.get('currency'),reference.get('multiplier'),reference.get('trading_class'),leg['type'],leg['strike']]
                target['has_offset']=any(leg['offset'] for leg in target['legs'])
            strategies.extend(merged.values())
        else:
            named=bucket['name'] not in ('组合净持仓',)
            strategies.append({'symbol':bucket['symbol'],'expiry':bucket['expiry'],'name':bucket['name'] if named else '策略组合待核验','quantity':bucket['groups'],
                'legs':[dict(type=leg.get('right'),strike=leg.get('strike'),side='BUY' if leg['quantity']>0 else 'SELL',qty=abs(leg['quantity'])) for leg in legs], 'verified':False})
    return strategies
