"""展示版的数据隔离、收益口径、脚本语法及离线生成验证。"""
import json
import hashlib
import re
import shutil
import socket
import subprocess
from datetime import date
from pathlib import Path

import pytest

from demo import fixtures
from demo.workspace import snapshot
from scripts.gen_report import generate
from wealth_os import core


def test_no_flow_returns_compound_and_match_mwr():
    """无外部入出金时，两种收益率相同且使用几何复利。"""
    result = core.performance_without_flows([(date(2026, 1, 1), .1), (date(2026, 1, 2), -.1)])
    assert result['twr_total'] == pytest.approx(-.01)
    assert result['twr_total'] == result['mwr_total']
    assert result['twr_annual'] == pytest.approx(.99 ** (365 / 2) - 1)
    assert result['series'][-1][1] == pytest.approx(-1)


@pytest.mark.parametrize('rows', [[], [(date(2026, 1, 1), -1)],
                                 [(date(2026, 1, 1), float('nan'))],
                                 [(date(2026, 1, 2), .1), (date(2026, 1, 1), .1)]])
def test_invalid_return_path_rejected(rows):
    """无效收益与乱序日期不能生成看似正常的收益率。"""
    with pytest.raises(ValueError):
        core.performance_without_flows(rows)


def test_fixture_reproducibility_and_option_netting():
    """虚构输入可复现，组合两腿与净仓数量一致。"""
    assert fixtures.transactions() == fixtures.transactions()
    assert len(core.months_of(fixtures.transactions())) == 6
    _, legs, openings = fixtures.portfolio()
    strategies = core.reconstruct_option_strategies(legs, openings)
    assert len(strategies) == 1 and strategies[0]['verified']
    assert sum(row['pnl'] for row in legs) == 80


def test_generation_ignores_private_environment_and_never_connects(tmp_path, monkeypatch):
    """阻断网络并设置错误个人数据目录，演示生成仍成功。"""
    def blocked(*args, **kwargs):
        raise AssertionError('展示生成不应尝试网络连接')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'getaddrinfo', blocked)
    monkeypatch.setenv('INVESTMENT_DATA_ROOT', str(tmp_path / 'must-not-read'))
    monkeypatch.setenv('IBKR_FLEX_ENABLED', '1')
    monkeypatch.setenv('IBKR_GATEWAY_ENABLED', '1')
    path = generate(tmp_path)
    html = path.read_text(encoding='utf-8')
    for marker in ['id="tab1"', 'id="tab2"', 'id="tab3"', 'id="tab4"', '合成数据演示']:
        assert marker in html
    for unwanted in ['127.0.0.1', 'wealth-report://', 'wealth-options://', 'fetch(',
                     'XMLHttpRequest', 'WebSocket', '<script src=', '<link rel="stylesheet"']:
        assert unwanted not in html
    assert path.stat().st_size > 40000
    assert (tmp_path / 'workspace.html').exists()
    timeline = (tmp_path / 'timeline.html').read_text(encoding='utf-8')
    assert '133' in timeline and '不代表' in timeline
    cfg = json.loads(re.search(r'var CFG = (.*);', html).group(1))
    assert cfg['PERFORMANCE_PERIODS']['ALL']['days'] > 100
    assert 'data-return-chart="ALL"' in html


def test_generated_javascript_syntax(tmp_path):
    """所有内嵌脚本均须能被JavaScript引擎解析。"""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js 未安装')
    generate(tmp_path)
    for page in tmp_path.glob('*.html'):
        for index, script in enumerate(re.findall(r'<script>(.*?)</script>', page.read_text(encoding='utf-8'), re.S)):
            js = tmp_path / f'{page.stem}-{index}.js'
            js.write_text(script, encoding='utf-8')
            result = subprocess.run([node, '--check', str(js)], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr


def test_original_workspace_style_and_sections_preserved(tmp_path):
    """原工作台样式与所有核心区域保留，生成文件没有真实状态/操作接口。"""
    generate(tmp_path)
    root = Path(__file__).resolve().parents[1]
    provenance = json.loads((root/'demo/templates/provenance.json').read_text(encoding='utf-8'))
    html = (tmp_path/'workspace.html').read_text(encoding='utf-8')
    original_css = re.search(r'<style>(.*?)</style>', html, re.S).group(1)
    assert hashlib.sha256(original_css.encode()).hexdigest() == provenance['source_style_sha256']
    for name in ['management-banner', 'calendar-view', 'funds', 'margin-view', 'check-details',
                 'candidate', 'positions', 'order-progress', 'audit-records']:
        assert f'id="{name}"' in html
    for unwanted in ['fetch(', '/api/', 'WebSocket', 'XMLHttpRequest', 'setInterval(', '{{']:
        assert unwanted not in html


def test_workspace_cashflow_and_candidate_consistency():
    """合成现金流与费用可勾稽，候选报价和显示净信用相符。"""
    state = snapshot()
    for order in state['order_progress']:
        trade = order['trade_details']
        assert trade['net_cash'] == pytest.approx(trade['gross_cash']-trade['total_fees'])
    close = state['order_progress'][1]
    assert close['settlement']['realized_pnl'] == pytest.approx(180-100-4.8)
    candidate = state['evaluated_candidate']
    long, short = candidate['legs']
    credit = (short['quote']['bid']-long['quote']['ask'])*100*2
    assert credit == pytest.approx(candidate['assessment']['metrics']['credit'])
