"""用完全虚构的快照驱动原工作台模板，不导入交易后台或个人配置。"""
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from wealth_os import __version__


def snapshot():
    """返回新建的合成状态，覆盖候选、持仓、订单、日历和检查表的数据协议。"""
    at = int(datetime(2026, 6, 30, 18, 0, tzinfo=timezone.utc).timestamp())
    legs = [dict(symbol='DEMO', conid=f'DEMO-{strike}', right='P', strike=strike, expiry='20260717',
                 quantity=quantity, average_price=average, mark_price=mark,
                 cost_basis=cost, market_value=value, unrealized_pnl=value-cost,
                 daily_pnl=daily, quote=dict(bid=mark-.05, ask=mark+.05, delta=delta))
            for strike, quantity, average, mark, cost, value, daily, delta in [
                (90, 2, .60, .40, 120, 80, -10, -.12),
                (95, -2, 1.50, .90, -300, -180, 30, -.21)]]
    metrics = dict(unrealized_pnl=80, unrealized_pct=80/180*100, market_value=-100, daily_pnl=20)
    combo = dict(id='demo-combo', name='Bull Put Spread', groups=2, legs=legs, **metrics)
    group = dict(id='demo-expiry', symbol='DEMO', expiry='2026-07-17',
                 combinations=[combo], legs=legs, **metrics)
    specs = [('gateway', '券商连接与账户', '连接与授权'), ('identity', '账户身份', '连接与授权'),
             ('positions', '持仓核对', '连接与授权'), ('executions', '成交回报', '连接与授权'),
             ('orders', '挂单核对', '连接与授权'), ('lease', '运行权', '连接与授权'),
             ('engine', '运行状态', '连接与授权'), ('inflight', '在途订单', '连接与授权'),
             ('unknown', '未知订单', '连接与授权'), ('old_pool', '已有仓位退出检查', '连接与授权'),
             ('authorization', '新增授权', '连接与授权'), ('summary_hours', '交易时段与市场压力', '关键门槛'),
             ('summary_volatility', 'IVP', '关键门槛'), ('summary_quotes', '行情与盘口', '关键门槛'),
             ('summary_candidate', '候选与费用', '关键门槛'), ('summary_funding', '资金与风险', '资金与额度'),
             ('batch_interval', '批次间隔', '关键门槛')]
    checks = [dict(id=key, label=label, group=group_name,
                   status='pending' if key=='authorization' else 'passed',
                   detail='固定合成检查结果，仅用于界面展示。', at=at) for key, label, group_name in specs]
    order_legs = [dict(leg, filled=leg['quantity'], average_fill_price=leg['average_price']) for leg in legs]
    order = dict(intent='demo-order-01', kind='OPEN', order_id='DEMO-001', created=at-3600,
                 planned=2, filled=2, label='全部成交', fees_ready=True, legs=order_legs,
                 combination=dict(name='Bull Put Spread', symbols=['DEMO']),
                 decision=dict(assessment=dict(eligible=True), margin_admission=dict(ready=True)),
                 trade_details=dict(final=True, last_fill_at=at-1800, combination_price=.90,
                                    gross_cash=180, total_fees=2.4, net_cash=177.6))
    close_order = deepcopy(order)
    close_order.update(intent='demo-order-02', kind='CLOSE', order_id='DEMO-002',
                       created=at-86400, decision=dict(exit=dict(signal='TAKE_PROFIT')),
                       settlement=dict(opening_gross_cash=180, total_roundtrip_fees=4.8,
                                       realized_pnl=75.2, realized_pct=75.2/177.6*100, basis=177.6,
                                       opening_average_prices={'DEMO-90':.6, 'DEMO-95':1.5}))
    for leg in close_order['legs']:
        leg.update(expiry='20260619', filled=-leg['quantity'], average_price=leg['mark_price'])
    close_order['trade_details'] = dict(final=True, last_fill_at=at-86400,
                                      combination_price=-.50, gross_cash=-100,
                                      total_fees=2.4, net_cash=-102.4)
    candidate_legs = deepcopy(legs)
    candidate_legs[0]['quote'].update(bid=.55, ask=.65)
    candidate_legs[1]['quote'].update(bid=1.55, ask=1.65)
    return dict(at=at, mode='MANAGING', authorization_until=None, capital=80080,
                versions=dict(service='showcase-'+__version__, rules='DEMO', finance_document='示例参数', started_at=at-7200),
                rules=dict(initial_capital_usd=80000, margin_target_fraction=.40,
                           scan_seconds=60, candidate_review_seconds=15),
                capital_source=dict(cumulative_pnl=80), allocation=dict(used=1000, target=32032, remaining=31032),
                snapshot=dict(nav=80080, cash=20000, sma=25000, positions=legs),
                connection=dict(status='CONNECTED', attempts=1),
                management=dict(status='MONITORING', label='合成持仓快照',
                                detail='示例快照：行情与持仓已核对；页面不运行后台管理。',
                                last_check_at=at, last_attempt_at=at, snapshot_at=at, pool_count=1),
                verification={key:dict(passed=True) for key in ['identity','positions','orders','executions']},
                pools=[dict(id='demo-pool', view=dict(signal='HOLD'))], position_groups=[group],
                opening_quota=dict(ready=True, ivp=42, periods=dict(day='2026-06-30'),
                                   limits=dict(day=8, week=None, month=None), used=dict(day=2, week=4, month=6),
                                   reserved=0, remaining=6), opening_batch=dict(ready=True),
                margin_admission=dict(ready=True, account_nav_reference=80080, buffer_required=8008,
                                      initial_after=1200, maintenance_after=1000,
                                      equity_after_conservative=80077.6, available_after_conservative=78877.6,
                                      excess_after_conservative=79077.6, sma_current=25000,
                                      sma_after_lower_bound=24800, target=32032),
                checklist=checks, check_summary=checks, reasons=[],
                scan=dict(at=at, checked_at=at, ivp=42,
                          calendar=dict(ready=True, verified_date='2026-06-30', sources=[],
                                        sync=dict(status='SUCCEEDED'), observation=dict(
                                            today='2026-06-30', today_events=[], upcoming=[],
                                            preview_sync=dict(status='SUCCEEDED'), calendar_events=[
                                                dict(date='2026-06-10', kind='CPI'),
                                                dict(date='2026-06-17', kind='FOMC')]))),
                evaluated_candidate=dict(at=at, legs=candidate_legs, assessment=dict(metrics=dict(
                    credit=180, stop_basis_estimate=177.6, roundtrip_fee_estimate=4.8,
                    projected_pool_risk=820, groups=2, dte=17, otm=.05))),
                order_progress=[order, close_order], events=[dict(at=at, kind='DEMO_SNAPSHOT',
                    payload='合成快照已载入，所有操作与记录均为示例。')], alerts=dict(active=[], history=[]))


def write_workspace(output):
    """将携带原CSS与显示逻辑的模板渲染为无网络的静态文件。"""
    folder = Path(__file__).resolve().parent
    template = (folder / 'templates/workspace.html').read_text(encoding='utf-8')
    adapter = (folder / 'workspace_adapter.js').read_text(encoding='utf-8')
    payload = json.dumps(snapshot(), ensure_ascii=False).replace('<', '\\u003c')
    adapter = 'const BASE_SNAPSHOT=' + payload + ';\n' + adapter
    replacements = {'{{ service_version }}': __version__, '{{ health_config | tojson }}':
                    json.dumps(dict(service_stale_seconds=30, fetch_timeout_seconds=10)),
                    '{{ showcase_adapter }}': adapter}
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    if '{{' in template or '{%' in template:
        raise ValueError('工作台仍有未替换的模板参数')
    (output / 'workspace.html').write_text(template, encoding='utf-8')
