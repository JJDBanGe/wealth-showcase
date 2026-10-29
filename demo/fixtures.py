"""固定种子生成虚构交易及组合；金额不是从真实账本扰动而来。"""
from datetime import date, timedelta
from random import Random


def transactions():
    """返回六个月的虚构消费，含不同金额层级和退款。"""
    rng = Random(4817)
    rows = []
    categories = [('饮食', 'DEMO CAFE', 35, 180), ('交通', 'DEMO TRANSIT', 8, 60),
                  ('购物', 'DEMO STORE', 80, 1100), ('娱乐休闲', 'DEMO CINEMA', 70, 230),
                  ('旅行住宿', 'DEMO HOTEL', 400, 1800), ('教育', 'DEMO COURSE', 100, 400)]
    for month in range(1, 7):
        for day in range(1, 29):
            for index in (0, 1, rng.randrange(2, 6)):
                category, merchant, low, high = categories[index]
                amount = round(rng.uniform(low, high), 2)
                if index >= 2 and day % 5 != 0:
                    continue
                rows.append(dict(date=f'2026-{month:02d}-{day:02d}', year=2026, month=month,
                                 desc=merchant, cat=category, src='SYNTHETIC', hkd=amount))
        rows.append(dict(date=f'2026-{month:02d}-28', year=2026, month=month,
                         desc='DEMO STORE REFUND', cat='购物', src='SYNTHETIC', hkd=-120.0))
    return rows


def portfolio():
    """返回虚构股票、期权净腿及对应历史组合；合约不是交易建议。"""
    stocks = [dict(symbol=symbol, industry=industry, weight=value / 80000 * 100,
                   value=value, pnl=pnl, return_pct=pnl / (value - pnl) * 100)
              for symbol, industry, value, pnl in [
                  ('SPYM', '大盘ETF', 24000, 1600), ('MSFT', '软件与云计算', 16000, 900),
                  ('AAPL', '消费科技', 12000, -350), ('GLDM', '黄金ETF', 8000, 300)]]
    legs = [dict(underlying='DEMO', symbol=f'DEMO-P-{strike}', expiry='20260717',
                 right='P', strike=strike, quantity=qty, cost=cost, value=value, pnl=value-cost)
            for strike, qty, cost, value in [(90, 2, 120, 80), (95, -2, -300, -180)]]
    opening = dict(month='2026-06', underlying='DEMO', quantity=2, strategy='Bull Put Spread',
                   strikes='SELL P 95 / BUY P 90', otm_text='虚构行情 +5.0%', expiry='20260717',
                   date='2026-06-12', legs=[dict(type='P', strike=strike, side=side, qty=2)
                                            for strike, side in [(90, 'BUY'), (95, 'SELL')]])
    return stocks, legs, [opening]


def market_path():
    """返回确定性的虚构日收益及仓位占比，供真实计算层处理。"""
    rng = Random(912)
    returns, allocation = [], []
    for i in range(181):
        day = date(2026, 1, 1) + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        daily = round(rng.uniform(-0.018, 0.021), 6)
        cash = 25 + 4 * (i % 30) / 30
        returns.append((day, daily))
        allocation.append((day, cash, 100 - cash, 0.0))
    return returns, allocation
