"""从固定合成输入生成离线演示；不读取 .env、个人文件或网络。"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from demo import fixtures, pages
from wealth_os import config, core, charts, report


def generate(output_dir=None):
    """返回生成的主报告路径；可指定独立输出目录以便验证。"""
    output = Path(output_dir) if output_dir else ROOT / 'docs'
    output.mkdir(parents=True, exist_ok=True)
    txns = fixtures.transactions()
    stocks, legs, openings = fixtures.portfolio()
    daily_returns, allocation = fixtures.market_path()
    cf = core.compute_cashflow(salary=38000, rent=config.RENT_FIXED, utility=450,
                               txns=txns, opt_usd=config.OPT_TMP_USD, usd_hkd=7.8,
                               invest_usd=config.FIXED_INVEST_USD)
    sim, years = core.simulate_snowball(config.P0_USD, config.INVEST_LEVELS,
                                      config.TWR_ANNUAL, core.fire_target_usd(7.8))
    ladder = core.compute_freedom_ladder(cf['food_total'], 7.8, config.P0_USD,
                                        config.FIXED_INVEST_USD, config.TWR_ANNUAL)
    cash = core.cash_panel(cf, 7.8, bank_balance_hkd=160000, ibkr_cash_usd=20000,
                           bank_balance_date=date(2026, 6, 30), credit_card_debt_hkd=4500,
                           credit_card_debt_date=date(2026, 6, 30))
    cash['ibkr_source'] = '合成现金快照 · 不连接券商'
    concentration = core.equity_concentration(stocks)
    drawdown = core.equity_drawdown(daily_returns, allocation, concentration)
    performance = core.performance_without_flows(daily_returns)
    wf = [dict(label=label, value=value, type=kind) for label, value, kind in [
        ('演示工资', cf['salary'], 'pos'), ('演示期权', cf['opt_hkd'], 'pos'),
        ('定投', -cf['invest_hkd'], 'neg'), ('固定支出', -cf['cash_fix'], 'neg'),
        ('实际消费', -cf['total_spend'], 'neg'), ('结余', cf['cash_surplus'], 'end')]]
    path, _ = report.render_report(
        data={'txns': txns}, cf=cf, sim_series=sim, sim_years=years, freedom_ladder=ladder,
        wf2_svg=charts.svg_waterfall(wf), ladder_svg=charts.svg_ladder(ladder),
        usd_hkd=7.8, fx_time='固定演示值', p0_usd=config.P0_USD,
        fire_target_usd=core.fire_target_usd(7.8), output_path=output / 'index.html',
        cash=cash, alloc_svg=charts.svg_allocation(allocation), alloc_series=allocation,
        stock_positions=stocks, industry_groups=[('ETF与基金', 40, 32000), ('科技平台', 35, 28000)],
        stock_data_desc='全部为合成持仓 · 不是作者真实资产',
        option_positions=legs, option_strategy_rows=core.reconstruct_option_strategies(legs, openings),
        option_positions_desc='虚构合约 DEMO · 无券商连接', option_openings=openings,
        opt_monthly=[dict(month=f'2026-{m:02d}', cash_net=200+m*25, realized=230+m*20,
                          trades=8, closes=4, opens=4, open_cash=320+m*20) for m in range(1, 7)],
        opt_note='虚构月度示例', opt_monthly_desc='合成数据；不代表真实交易业绩',
        twr_annual=performance['twr_annual'], twr_total=performance['twr_total'],
        twr_note='合成收益路径，无外部入出金，TWR 与 MWR 相等',
        mwr=performance, performance_periods={'ALL': performance},
        equity_extra={'concentration': concentration, 'rebalance': [], 'drawdown': drawdown})
    pages.write_workspace(output)
    pages.write_timeline(output, ROOT / 'docs' / 'development-history.json')
    return Path(path)


if __name__ == '__main__':
    print('Generated offline showcase:', generate())
