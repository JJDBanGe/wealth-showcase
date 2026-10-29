
"""报告层：纯外观渲染。CSS/HTML/JS 都在这里，改样式只动这个文件。
不做业务计算：只接收 core 层算好的数据 + charts 层生成的 SVG，组装成 HTML。
JS 交互所需的参数（定投档、收益率、FIRE 目标等）全部由 render_report 从 config 注入，
禁止在 JS 中硬编码业务参数，避免与 config.py 双源失同步。"""
import json
from html import escape
from pathlib import Path
import os
import tempfile
from .core import fmt, fmt2, month_completeness, group_option_holdings, reconstruct_option_strategies
from . import config, charts


def build_report_controls():
    """输出离线演示标识与开发时间线入口。"""
    return '<div class="info-note"><b>FICTIONAL DATA · 合成数据演示</b> ｜ <a href="timeline.html">查看真实开发时间线</a></div>'


def build_report_controls_js():
    """演示报告不连接本地报告服务。"""
    return ''


def build_report_service_js():
    """演示报告不提供服务更新动作。"""
    return ''


def build_workspace_entry_js():
    """演示工作台使用相对静态链接。"""
    return ''


def build_opening_strikes_html(row):
    """按Put/Call分行展示历史委托行权价，卖腿在前、买腿在后；仅格式化已有腿。"""
    legs=row.get('legs')
    if not legs:
        return escape(row.get('strikes','未提供'))
    groups=[]
    for kind,label in [('P','Put'),('C','Call')]:
        selected=sorted((leg for leg in legs if leg.get('type')==kind),key=lambda leg:(leg.get('side')!='SELL',leg.get('strike',0)))
        if selected:
            values=' / '.join(('SELL ' if leg.get('side')=='SELL' else 'BUY ')+f'{leg["strike"]:.2f}' for leg in selected)
            groups.append('<div class="opening-strike-row"><span>'+label+'</span><b>'+escape(values)+'</b></div>')
    return ''.join(groups)


def build_equity_analysis_html(extra, drawdown_only=False):
    """展示已经计算好的长线指标；缺失、ETF口径、历史范围均明确标注。"""
    def text(value):
        return escape(str(value))

    def number(value, suffix='', signed=False):
        return '—' if value is None else format(value, '+.1f' if signed else '.1f') + suffix

    def section(title, content, desc=''):
        return f'<div class="section"><div class="section-header"><div class="section-title">{title}</div><div class="section-desc">{desc}</div></div><div class="chart-card">{content}</div></div>'

    def kpis(items):
        return '<div class="kpis">' + ''.join(f'<div class="kpi"><div class="k1">{name}</div><div class="k2">{value}</div></div>' for name, value in items) + '</div>'

    def table(headers, rows):
        return '<div style="overflow-x:auto"><table class="holdings-table"><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{v}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'

    c, dd = extra.get('concentration'), extra.get('drawdown')
    if c:
        concentration = kpis([
            ('最大持仓 · ' + text(c['largest']['symbol']), number(c['largest']['equity_weight'], '%')),
            ('Top 3 / Top 5', number(c['top3'], '%') + ' / ' + number(c['top5'], '%')),
            ('最大行业 · ' + text(c['largest_industry']), number(c['industry_weight'], '%')),
            ('集中度 HHI · 0~10000', f"{c['hhi']:.0f}")])
        concentration += '<div class="info-note">以上以股票/基金总市值为分母，和正股明细的 %netliq 不同。HHI 越高越集中；ETF/基金没有穿透到底层成分，行业分散度可能高估。</div>'
    else:
        concentration = '<div class="info-note">暂无正股持仓数据。</div>'
    html = section('持仓集中度', concentration)
    if dd:
        risk = kpis([('当前回撤', number(dd['current'], '%')), ('最大回撤', number(dd['worst'], '%')),
                     ('恢复至高点需上涨', number(dd['recovery'], '%')), ('最高 TWR 指数 · 起点100', number(dd['peak']))])
        risk += charts.svg_equity_drawdown(dd['series'])
        if dd.get('episodes'):
            episode_rows = []
            for ep in dd['episodes']:
                peak_day, trough_day = ep['peak'][0], ep['trough'][0]
                end_day = ep['end'][0] if ep.get('end') else '尚未恢复'
                episode_rows.append([text(peak_day), text(trough_day), text(end_day), number(ep['trough'][2], '%'), text(ep['reason'])])
            risk += '<h4>超过 10% 的完整回撤区间</h4>' + table(['高点', '低点', '恢复日期', '最大回撤', '数据支持的原因'], episode_rows)
        else:
            risk += '<div class="info-note">导入区间内没有超过 10% 的完整回撤。</div>'
        risk += f'<div class="info-note">{text(dd["start"])} ~ {text(dd["end"])} · 账户 TWR（含现金、股票、期权）逐日链式收益，剔除出入金影响。历史最高值是收益指数，不是美元净资产；最大回撤只覆盖已导入区间，不代表未来跌幅上限。</div>'
    else:
        risk = '<div class="info-note">缺少有效逐日净值/出入金数据，无法计算回撤。</div>'
    if drawdown_only:
        return section('回撤与风险', risk)
    rb = extra.get('rebalance', [])
    rows = [(text(r['name']), number(r['weight'], '%'), number(r['target'], '%'),
             '—' if r['target'] is None else number(max(0, r['target'] - config.EQUITY_REBALANCE_BAND_PP), '%') + ' ~ ' + number(min(100, r['target'] + config.EQUITY_REBALANCE_BAND_PP), '%'),
             number(r['delta'], ' pp', True), text(r['status'])) for r in rb]

    rebalance = ''
    for kind, title in [('industry', '行业目标'), ('symbol', '个股目标')]:
        filtered = [row for row, original in zip(rows, rb) if original['kind'] == kind]
        if filtered:
            rebalance += f'<details class="holdings-details" {"open" if kind == "industry" else ""}><summary>{title}</summary>' + table(['标的/行业', '当前', '目标', '容忍区间', '偏离', '状态'], filtered) + '</details>'
    rebalance += f'<div class="info-note">目标以股票/基金总市值为分母，默认容忍 ±{config.EQUITY_REBALANCE_BAND_PP:g} 个百分点。未设目标显示“待设定”；超配/低配仅提醒复核。目标可在 config.py 的 EQUITY_TARGETS 按 symbol / industry 设置；未满100%的配置属于部分目标。</div>'
    html += section('目标权重与再平衡', rebalance)
    fundamental_rows = []
    for r in extra.get('fundamentals', []):
        fund = r.get('fund')
        metrics = ['earnings_growth', 'revenue_growth', 'roe', 'gross_margin', 'pe', 'forward_pe', 'fcf_yield']
        cells = ['不适用' if fund else ('N/M' if key in {'pe', 'forward_pe'} and r.get(key) is not None and r[key] <= 0 else number(r.get(key), '' if key in {'pe', 'forward_pe'} else '%')) for key in metrics]
        percentile = '不适用' if fund else (number(r['pe_percentile'], '%') + f"<br><small>{text(r['history_start'])}起 · {r['samples']}个日期</small>" if r.get('pe_percentile') is not None else f"样本不足 · {r.get('samples', 0)}个日期")
        source = text(r.get('source', '缺少数据')) + '<br><small>' + text(r.get('date', '—')) + (' · 已过期' if r.get('stale') else '') + '</small>'
        fundamental_rows.append([text(r['symbol']) + ('<br><small>ETF/基金</small>' if fund else ''), *cells, percentile, source])
    fundamentals = table(['标的', '盈利同比增长', '营收同比增长', 'ROE', '毛利率', 'P/E', 'Forward P/E', 'FCF Yield', 'P/E历史分位', '来源/快照日期'], fundamental_rows) if fundamental_rows else '<div class="info-note">暂无基本面数据。</div>'
    fundamentals += '<div class="info-note">演示版未接入基本面数据。缺失值保持缺失，不用示例值冒充真实估值。</div>'
    for note in extra.get('fundamental_notes', []):
        fundamentals += f'<div class="info-note">{text(note)}</div>'
    html += section('持仓质量与估值', fundamentals)
    return html


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#F5F7FA;color:#1E293B;font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.container{max-width:1000px;margin:0 auto;padding:24px 20px 48px}
.report-header{margin-bottom:16px;padding-bottom:16px;border-bottom:2px solid #1E293B}
.report-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:12px;font-size:12px}
.report-actions [role="button"],.report-actions button{display:inline-block;padding:7px 12px;border:1px solid #CBD5E1;border-radius:6px;background:#FFF;color:#1E293B;cursor:pointer;text-decoration:none;font:inherit;line-height:1.4}
.report-actions [aria-disabled="true"],.report-actions button:disabled{opacity:.6;cursor:default}
.report-title{font-size:22px;font-weight:700;color:#0F172A;margin-bottom:4px}
.report-subtitle{font-size:12px;color:#64748B}
.tab-data-note{padding:12px 0;font-size:12px;color:#64748B;margin-bottom:8px}
.tab-intro{display:flex;flex-direction:column;justify-content:center;gap:8px;margin:16px 0 20px;padding:14px 16px;min-height:52px;background:#EEF2F6;border:1px solid #E2E8F0;border-radius:8px;color:#64748B;font-size:12px;line-height:1.75}
.tab-intro .tab-data-note{padding:0;margin:0;font:inherit;color:inherit;overflow-wrap:anywhere}
.workspace-entry{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px}
.workspace-entry a{display:inline-flex;align-items:center;justify-content:center;padding:6px 12px;border:1px solid #CBD5E1;border-radius:6px;background:#FFF;color:#1D4ED8;font-weight:600;text-decoration:none;white-space:nowrap}
.workspace-entry a:hover{background:#EFF6FF;border-color:#93C5FD}
.workspace-entry a:focus-visible{outline:2px solid #2563EB;outline-offset:3px}
.workspace-entry [role="status"]{flex:1 1 240px;overflow-wrap:anywhere}
.tab-bar{display:flex;gap:8px;flex-wrap:wrap;position:sticky;top:0;z-index:30;background:#F5F7FA;padding:10px 0 16px;border-bottom:1px solid #E2E8F0}
.tab-btn{padding:9px 22px;border:1px solid #E2E8F0;background:#FFF;border-radius:8px;font-size:14px;font-weight:600;color:#475569;cursor:pointer}
.tab-btn.active{background:#0F172A;color:#FFF;border-color:#0F172A}
.metrics-bar{display:flex;flex-wrap:wrap;background:#FFF;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:16px}
.metric{flex:1;min-width:140px;padding:13px 16px;border-right:1px solid #F1F5F9}
.metric:last-child{border-right:none}
.metric-label{font-size:11px;color:#94A3B8;letter-spacing:0.04em;margin-bottom:4px}
.metric-value{font-size:17px;font-weight:700;color:#0F172A;font-variant-numeric:tabular-nums}
.metric-value.pos{color:#7A9A3F}.metric-value.neg{color:#C75B5B}
.section{margin-bottom:26px}
.section-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;flex-wrap:wrap;gap:4px}
.sticky-head{position:sticky;top:0;z-index:12;margin-bottom:0;padding:6px 0 8px;background:#F5F7FA}
/* 吸顶时补一条分隔线：明细卡片自己的上边框已经随卡片顶边滚出视口，用阴影在标题行下方补回来（阴影不占布局） */
.sticky-head.is-stuck{box-shadow:0 1px 0 0 #E2E8F0}
.filter-header{display:block;text-align:center;min-height:52px;padding-top:1px}
.filter-header .section-title,.filter-header .section-desc{display:block;width:100%;text-align:center}
.filter-header .section-desc{margin-top:4px}
.section-title{font-size:16px;font-weight:700;color:#0F172A}
.section-desc{font-size:12px;color:#94A3B8}
.industry-layout{display:grid;grid-template-columns:minmax(390px,1.15fr) minmax(300px,1fr);align-items:center;gap:24px;padding:8px 6px 14px}
.industry-notes{display:flex;flex-direction:column;gap:9px}
.industry-note{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:9px 11px;background:#F8FAFC;border-radius:7px;border-left:3px solid #CBD5E1}
.industry-note b{font-size:13px;color:#334155}.industry-note span{font-size:13px;font-weight:700;color:#0F172A}.industry-note small{grid-column:1/-1;color:#64748B;font-size:11.5px;line-height:1.5}
.industry-note b{color:var(--tag-color)}
.industry-tag{display:inline-block;padding:2px 7px;border-radius:10px;background:color-mix(in srgb,var(--tag-color) 13%,white);color:var(--tag-color);font-weight:600;font-size:11px}
.industry-filter{display:flex;align-items:center;gap:8px;margin:4px 0 10px;color:#64748B;font-size:12px}.industry-filter select{min-width:150px}
.holdings-details{margin-top:6px;border-top:1px solid #E2E8F0;padding-top:10px}.holdings-details summary{cursor:pointer;color:#64748B;font-size:12px;font-weight:600}
.holdings-table th,.holdings-table td{text-align:center!important}
.option-position-group{border:1px solid #e2e8f0;border-radius:10px;background:white;padding:18px;margin:14px 0}.option-position-group h3{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px 14px;margin:0 0 14px;font-size:15px;color:#334155}.option-position-group h3 small{font-size:12px;color:#64748b;font-weight:400}.option-position-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:16px}.option-position-metrics>div{padding:12px;background:#f8fafc;border-radius:7px;min-width:0}.option-position-metrics small{display:block;color:#64748b;font-size:11px;margin-bottom:6px}.option-position-metrics b{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums}.option-position-legs{overflow-x:auto}.option-position-legs table{min-width:920px;width:100%;table-layout:fixed}.option-position-legs td:first-child,.option-position-legs th:first-child{white-space:normal;overflow-wrap:anywhere}.option-position-legs th{position:static}.option-strategy-table .option-col-symbol,.option-strategy-table .option-col-quantity{width:6%}.option-strategy-table .option-col-strategy{width:28%}.option-strategy-table .option-col-expiry{width:12%}.option-strategy-table .option-col-put,.option-strategy-table .option-col-call{width:24%}.option-offset-stage{position:relative;min-width:920px}.option-offset-links{position:absolute;left:0;top:0;pointer-events:none;overflow:visible}.option-offset-links path{fill:none;stroke:#829ab6;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.option-offset-links circle{fill:#829ab6}.option-offset-links g{opacity:.6}.has-active-offset .option-offset-links g{opacity:.12}.has-active-offset .option-offset-links g.is-active-offset{opacity:1}.option-offset-links g.is-active-offset path{stroke:#315f99}.option-offset-links g.is-active-offset circle{fill:#315f99}.option-offset-anchor.is-active-offset{background:#edf3fc;border-radius:3px;box-shadow:0 0 0 3px #edf3fc}.option-offset-anchor[data-option-offset-key]{cursor:help}.option-offset-anchor{display:inline-block;position:relative;white-space:nowrap;vertical-align:baseline}.option-offset-badge,.option-offset-leg{position:absolute;left:100%;top:50%;transform:translateY(-50%);margin-left:6px;white-space:nowrap;line-height:1.4;font-size:10px;font-weight:500;color:#86570b}.option-strategy-cell{position:relative}.option-strategy-cell>.option-offset-anchor{position:static;width:112px;text-align:center}.option-strategy-cell .option-offset-badge{left:calc(75% + 28px);margin-left:0;transform:translate(-50%,-50%)}.option-offset-badge{padding:2px 5px;border-radius:4px;background:#fff4db}.option-pnl-positive{color:#25613a}.option-pnl-negative{color:#a52626}@media(max-width:650px){.option-position-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.option-position-group{padding:13px}}
.table-sort{border:0;background:transparent;color:inherit;font:inherit;font-weight:inherit;padding:0;cursor:pointer}.table-sort:hover{color:#4A90D9}
.option-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:14px}
.option-kpi{padding:14px 16px;border:1px solid #E2E8F0;border-radius:8px;background:linear-gradient(135deg,#F8FAFC,#FFF)}
.option-kpi span,.option-kpi small{display:block;color:#64748B;font-size:11px}.option-kpi b{display:block;margin:4px 0;font-size:22px;color:#0F172A;font-variant-numeric:tabular-nums}
@media(max-width:600px){.option-summary{grid-template-columns:1fr}}
@media(max-width:700px){.industry-layout{grid-template-columns:1fr;gap:8px}}
.chart-card{background:#FFF;border:1px solid #E2E8F0;border-radius:8px;padding:14px;margin-bottom:14px}
.chart-body{min-height:220px}
.chart-title{font-size:13px;font-weight:700;color:#0F172A;margin-bottom:4px}
.donut-wrap{display:flex;align-items:center;gap:14px;min-height:190px}
.donut-fig{flex:0 1 190px;min-width:0}
.donut-legend{flex:1 1 auto;display:flex;justify-content:center;min-width:0}
.donut-legend-inner{display:flex;flex-direction:column;gap:8px}
.donut-legend-row{display:flex;align-items:center;gap:7px;font-size:13px;color:#475569;white-space:nowrap}
.donut-swatch{width:10px;height:10px;border-radius:2px;flex:0 0 auto}
.pie-tip{display:none;position:absolute;pointer-events:none;z-index:20;background:rgba(15,23,42,.94);color:#fff;padding:7px 11px;border-radius:6px;font-size:12px;line-height:1.6;white-space:nowrap}
table{width:100%;border-collapse:collapse;table-layout:fixed;font-variant-numeric:tabular-nums;margin:8px 0;border-left:1px solid #F1F5F9;border-right:1px solid #F1F5F9}
.col-date{width:15%}.col-desc{width:29%}.col-cat{width:12%}.col-source{width:17%}.col-amount{width:14%}.col-nature{width:13%}
thead th{font-size:12px;font-weight:700;color:#475569;text-align:right;padding:10px 12px;background:#F8FAFC;white-space:nowrap;position:sticky;z-index:10;box-shadow:inset 0 -1px 0 #E2E8F0}
thead th:nth-child(1),thead th:nth-child(2){text-align:center}
thead th:nth-child(n+3){text-align:center}
tbody td{font-size:13px;color:#1E293B;text-align:right;padding:8px 12px;border-bottom:1px solid #F1F5F9;white-space:nowrap}
tbody td:first-child{text-align:left}
tbody td.desc{text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#475569}
tbody td:nth-child(3){text-align:center}   /* 品类：标签短，按列居中，和居中的列标题对齐 */
tbody td:nth-child(4){text-align:left}     /* 来源：文本较长，保持左对齐 */
tbody td:nth-child(6){text-align:center}
tbody td+td{border-left:1px solid #F1F5F9}
thead th+th{box-shadow:inset 1px 0 0 #F1F5F9,inset 0 -1px 0 #E2E8F0}
thead th:nth-child(3),tbody td:nth-child(3){min-width:90px}
thead th:nth-child(4),tbody td:nth-child(4){min-width:150px}
thead th:nth-child(5),tbody td:nth-child(5){min-width:110px}
thead th:nth-child(6),tbody td:nth-child(6){min-width:100px}
tr.total td{background:#EFF6FF!important;font-weight:700}
.opening-strike-row{display:flex;align-items:baseline;gap:10px;white-space:nowrap;margin:3px 0}.opening-strike-row>span{flex:none;width:32px;color:#64748b;font-size:11px}.opening-strike-row>b{font-weight:500;font-variant-numeric:tabular-nums}
.option-monthly-table th,.option-monthly-table td,.option-openings-table th,.option-openings-table td{text-align:center}
.option-monthly-table th{white-space:normal}
.returns-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:12px}
.return-panel{min-width:0;background:#FFF;border:1px solid #E2E8F0;border-radius:6px;padding:18px 20px}
.return-method{display:flex;align-items:center;gap:10px;margin-bottom:18px}
.return-method strong{font-size:15px;color:#2476B5}
.return-panel.mwr .return-method strong{color:#297D68}
.return-method span{font-size:12px;color:#64748B}
.return-values{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:16px}
.return-value+ .return-value{border-left:1px solid #E2E8F0;padding-left:16px}
.return-value dt{font-size:11px;color:#64748B;margin-bottom:6px}
.return-value dd{font-size:28px;font-weight:650;line-height:1.25;font-variant-numeric:tabular-nums;color:#0F172A;white-space:nowrap}
.return-value.annual dd{font-size:23px;padding-top:5px}
.return-panel.twr .return-value dd{color:#2476B5}.return-panel.mwr .return-value dd{color:#297D68}
.return-caption{font-size:11px;color:#94A3B8;margin-top:14px}
.return-notes{font-size:12px;color:#64748B;margin-top:12px}
.return-notes summary{cursor:pointer;width:fit-content}
.return-notes p{margin-top:8px;line-height:1.7}
.return-chart-header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:18px 0 10px;flex-wrap:wrap}
.return-chart-controls{display:flex;gap:10px;flex-wrap:wrap}
.return-periods{display:flex;padding:3px;gap:3px;background:#E9EDF2;border-radius:6px}
.return-periods button{border:0;background:transparent;color:#64748B;padding:6px 12px;font-size:12px;font-weight:600;border-radius:4px;cursor:pointer}
.return-periods button[aria-pressed="true"]{background:#FFF;color:#0F172A;box-shadow:0 1px 3px #CBD5E1}
.return-periods button:disabled{opacity:.4;cursor:default}
.return-chart-legend{display:flex;gap:18px;font-size:12px;color:#64748B}
.return-chart-legend span{display:flex;align-items:center;gap:6px}
.return-chart-legend i{width:18px;height:3px;background:#2476B5}
.return-chart-legend .mwr-line{background:#297D68}
.return-chart-legend [hidden],.return-chart [data-return-series][hidden]{display:none}
.return-chart-panel{position:relative;background:#FFF;border:1px solid #E2E8F0;border-radius:6px;padding:12px 4px 4px}
.return-chart-panel[hidden]{display:none}
.return-chart{display:block;width:100%;height:auto}
.return-chart-tooltip{position:absolute;display:none;pointer-events:none;background:#0F172A;color:#FFF;font-size:12px;padding:8px 10px;border-radius:4px;white-space:nowrap;z-index:15}
@media(max-width:640px){.returns-grid{grid-template-columns:minmax(0,1fr)}.return-panel{padding:16px 18px}.return-chart text{font-size:20px}}
.option-sticky thead th{position:sticky;z-index:10;background:#F8FAFC;box-shadow:inset 0 -1px 0 #E2E8F0}
.option-sticky thead th{text-align:center!important}
.option-table-card{padding:0;overflow:visible;margin-top:0;border-top:0;border-radius:0 0 8px 8px}
.option-table-card .option-note{padding:12px 14px;margin:0}
.option-table-card>table{margin:0;width:100%}
.option-opening-head{position:sticky;z-index:12;top:0;margin:0;padding:10px 0;border-top:2px solid #94A3B8;background:#F5F7FA}
.option-opening-head .section-title{line-height:26px}
.option-openings-table th:nth-child(4),.option-openings-table td:nth-child(4),.option-openings-table th:nth-child(5),.option-openings-table td:nth-child(5),.option-openings-table th:nth-child(6),.option-openings-table td:nth-child(6){text-align:left;white-space:normal;overflow-wrap:anywhere}
.pos{color:#7A9A3F;font-weight:600}.neg{color:#C75B5B;font-weight:600}.muted{color:#94A3B8}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600}
.tag-real{background:#E8F5E9;color:#2E7D32}.tag-tmp{background:#FDECEC;color:#C75B5B}
.info-note{background:#F8FAFC;border-left:3px solid #94A3B8;padding:11px 16px;font-size:12px;color:#64748B;line-height:1.7;margin:10px 0;border-radius:0 4px 4px 0}
.info-note b{color:#475569}
/* Tab2 顶部的「三块怎么用」引导条 */
.usage-guide{background:linear-gradient(135deg,#EFF6FF,#F0FDF4);border:1px solid #DBEAFE;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:12.5px;color:#475569;line-height:1.75}
.usage-guide .ug-title{font-size:13px;font-weight:700;color:#0F172A;margin-bottom:6px}
.usage-guide .ug-step{margin-top:2px}
.usage-guide .ug-num{display:inline-block;min-width:18px;height:18px;line-height:18px;text-align:center;border-radius:9px;background:#4A90D9;color:#FFF;font-size:11px;font-weight:700;margin-right:6px}
.usage-guide .ug-num.n2{background:#7A9A3F}
.usage-guide .ug-num.n3{background:#C9A227}
.usage-guide b{color:#0F172A}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.rate-toolbar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 18px;align-items:center;margin-bottom:16px}
.rate-source{display:flex;align-items:center;gap:10px;min-width:0}
.rate-source{grid-column:1/-1}.rate-toolbar.twr-mode .rate-source{grid-column:auto}
.rate-source label,.rate-input label{font-size:13px;color:#475569;white-space:nowrap}
.rate-source select{flex:1;min-width:0;width:100%;text-overflow:ellipsis}
.rate-input{display:flex;align-items:center;gap:8px;white-space:nowrap}
.rate-input[hidden],#twrStatus[hidden]{display:none}
.rate-input input{width:80px;height:36px;padding:7px 10px;border:1px solid #CBD5E1;border-radius:6px;font-size:13px}
.rate-input span{font-size:13px;color:#64748B}
.rate-meta{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:4px 16px;font-size:11px;color:#94A3B8;min-width:0;overflow-wrap:anywhere}
@media(max-width:640px){.rate-toolbar{grid-template-columns:minmax(0,1fr)}.rate-input{justify-content:flex-start}}
.sticky-bar{position:sticky;top:0;z-index:11;margin-bottom:0;padding-top:24px;padding-bottom:24px;background:#FFF}
/* 明细区吸顶不压缩：把三处「吸顶后会消失的间距」挪进吸顶块自己的 padding ——
   ① 卡片顶部内边距 14px + 原 4px，并与下方间距取平均 → 工具栏 padding-top:24px（#txnTableCard 顶部内边距置 0）
   ② 工具栏原 margin-bottom 10px + 原 padding-bottom 12px + 表格上边距 8px，并与上方间距取平均 → 工具栏 padding-bottom:24px（#txnTable 上边距置 0）
   ③ 明细标题行高取整 26px，避免 floor() 使相邻吸顶块重叠 0.6px */
#txnTableCard{padding-top:0}
#txnTable{margin-top:0}
#txnHead .section-title{line-height:26px}
.month-range{font-size:13px;color:#475569;font-weight:600;white-space:nowrap}
.search-box{height:40px;padding:7px 12px;border:1px solid #CBD5E1;border-radius:6px;font-family:inherit;font-size:13px;line-height:1.2;min-width:220px}
.col-filter{display:inline-block}
.col-filter-btn{display:inline-flex;align-items:center;padding:3px 2px;border:0;background:transparent;color:#475569;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap;font-family:inherit;max-width:100%;overflow:hidden}
.col-filter-btn .cf-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.col-filter-btn:hover{color:#0F172A}
.col-filter-btn.active{color:#0F172A}
.col-filter-btn .caret{color:#94A3B8;font-weight:400;margin-left:2px}
.col-filter-menu{display:none;position:absolute;z-index:30;top:100%;left:50%;transform:translateX(-50%);min-width:120px;max-height:280px;overflow:auto;padding:6px;background:#FFF;border:1px solid #CBD5E1;border-radius:6px;box-shadow:0 8px 24px rgba(15,23,42,.15);text-align:left}
.col-filter-menu.open{display:block}
.col-filter-option{display:block;width:100%;padding:5px 8px;border:0;background:transparent;text-align:left;cursor:pointer;font-size:12px;color:#475569;font-family:inherit}
.col-filter-option:hover{background:#F8FAFC}
.col-filter-option.chosen{font-weight:700;color:#0F172A}
.search-box:focus{outline:none;border-color:#0F172A}
select{padding:7px 10px;border:1px solid #CBD5E1;border-radius:6px;font-size:13px;background:#FFF}
.month-menu{display:none;position:absolute;z-index:30;top:100%;left:0;min-width:190px;max-height:280px;overflow:auto;padding:6px;background:#FFF;border:1px solid #CBD5E1;border-radius:6px;box-shadow:0 8px 24px rgba(15,23,42,.15);text-align:left}
.month-menu.open{display:block}
.month-option{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:4px;color:#334155;font-size:13px;white-space:nowrap;cursor:pointer}
.month-option:hover{background:#F8FAFC}
.month-option.all{border-bottom:1px solid #E2E8F0;margin-bottom:4px;padding-bottom:8px;font-weight:700}
.month-option input{width:15px;height:15px;accent-color:#0F172A}
.month-option .month-only{margin-left:auto;padding:2px 6px;border:1px solid #CBD5E1;border-radius:4px;background:#FFF;color:#64748B;font-size:11px;cursor:pointer}
.month-option .month-only:hover{border-color:#0F172A;color:#0F172A}
.empty-cell{padding:0;text-align:center;vertical-align:top;color:#94A3B8;font-size:13px}
.empty-note{display:block;padding:40px 12px}
/* 财富自由阶梯表格：定义列允许换行、列宽按内容分配（全局 table 是 fixed 布局会截断长定义）；
   数值列内容居中，与居中的列标题对齐；等级列不换行 */
.ladder-table{table-layout:auto}
.ladder-table td{white-space:normal;text-align:center}
.ladder-table td:nth-child(1){white-space:nowrap}
/* 数值列需要覆盖全局 tbody td:nth-child(3)/(4) 的 text-align:left */
.ladder-table td:nth-child(3),.ladder-table td:nth-child(4),.ladder-table td:nth-child(5){text-align:center}
.ladder-table th:nth-child(1),.ladder-table td:nth-child(1){width:17%}
.ladder-table th:nth-child(2),.ladder-table td:nth-child(2){width:28%}
.ladder-table th:nth-child(3),.ladder-table td:nth-child(3){width:18%}
.ladder-table th:nth-child(4),.ladder-table td:nth-child(4){width:20%}
.ladder-table th:nth-child(5),.ladder-table td:nth-child(5){width:17%}
/* 关闭滚动锚定：表格行数变化时不希望浏览器自作主张调整滚动位置 */
#txnTable,#txnTable tbody{overflow-anchor:none}
.cat-tag{display:inline-block;padding:1px 8px;border-radius:8px;font-size:11px}
.nature-tag{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap}
.nature-real{background:#E8F5E9;color:#2E7D32}.nature-fixed{background:#FFF4E5;color:#A15C00}
.fixed-cat{background:#6B7280;color:#fff}
.kpis{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.kpi{flex:1 1 140px;background:#F4F8EF;border-radius:8px;padding:10px 14px}
.kpi .k1{font-size:11px;color:#6B7280}
.kpi .k2{font-size:17px;font-weight:700;color:#1E293B}
.src-note{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.src-item{flex:1 1 200px;background:#FFF;border:1px solid #E2E8F0;border-radius:8px;padding:10px 14px}
.src-item .s1{font-size:11px;color:#6B7280}
.footnote{margin-top:28px;padding-top:14px;border-top:1px solid #E2E8F0;font-size:11px;color:#94A3B8;line-height:1.8}
"""


LADDER_DEFS = {
    "奶茶自由": "随时买奶茶/咖啡不看价格",
    "iPhone自由": "每年换新 iPhone 不犹豫",
    "享受型食物自由": "自助餐/寿司/日料随便吃",
    "娱乐自由": "演唱会/电影/游戏/订阅不看价",
    "交通自由": "打车不看价格，地铁公交随便坐",
    "旅行自由": "每年 1-2 次境外旅游不心疼",
    "房租自由": "香港优质地段租房不看价",
    "FIRE": "被动收入覆盖全部生活支出（按设定 SWR）",
}


def build_js(txns, js_cfg, cat_colors):
    """js_cfg 由 render_report 从 config 注入：P0/FIRE_USD/USD_HKD/LEVELS/RATES/RATE_LABELS/
    MONTHLY_INVEST/BIG_SPEND。fv/fireYear 公式与 core.py 保持一致，改动需同步。
    滚雪球曲线纵轴上限由 niceMax() 按曲线最高点现算（不注入固定值）。"""
    txn_json = json.dumps([{"d": t["date"], "desc": t["desc"], "cat": t["cat"],
                            "src": t["src"], "amt": round(t["hkd"], 2),
                            "fixed": bool(t.get("fixed", False))} for t in txns],
                          ensure_ascii=False)
    cat_color_js = json.dumps(cat_colors, ensure_ascii=False)
    cfg_json = json.dumps(js_cfg, ensure_ascii=False)
    return f"""
(function(){{
  function $(id){{ return document.getElementById(id); }}
  var TXNS = {txn_json};
  var CATCOLOR = {cat_color_js};
  var CFG = {cfg_json};
  var P0 = CFG.P0, FIRE_USD = CFG.FIRE_USD, USD_HKD = CFG.USD_HKD;
  var LEVELS = CFG.LEVELS, RATES = CFG.RATES, RATE_LABELS = CFG.RATE_LABELS;
  var MONTHLY_INVEST = CFG.MONTHLY_INVEST, BS = CFG.BIG_SPEND;
  var TWR_MANUAL = false;
  var CASH = CFG.CASH || {{spendable:0, cash:0, emergency:0, essential:0, months:null}};
  var SCOLORS = ['#4A90D9', '#C9A227', '#7A9A3F'];
  function esc(s){{ return String(s).replace(/[&<>\"]/g, function(ch){{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[ch]; }}); }}
  // ===== 月份多选（全部 / 任意组合），驱动明细、饼图/柱状图、顶部指标联动 =====
  var MONTHS = [];
  TXNS.forEach(function(t){{ var m = t.d.slice(0,7); if (MONTHS.indexOf(m) < 0) MONTHS.push(m); }});
  MONTHS.sort();
  var SEL = {{}};  // month -> bool
  MONTHS.forEach(function(m){{ SEL[m] = true; }});
  function fmtHKD(v){{ return Math.round(v).toLocaleString(undefined,{{maximumFractionDigits:0}}); }}
  function selectedMonths(){{ var arr = []; MONTHS.forEach(function(m){{ if (SEL[m]) arr.push(m); }}); return arr; }}
  function filterTxns(){{ return TXNS.filter(function(t){{ return !t.fixed && !!SEL[t.d.slice(0,7)]; }}); }}
  function filterTableTxns(){{ return TXNS.filter(function(t){{
    if (!SEL[t.d.slice(0,7)]) return false;
    if (FVALS.cat !== 'all' && t.cat !== FVALS.cat) return false;
    if (FVALS.src !== 'all' && t.src !== FVALS.src) return false;
    if (FVALS.nature === 'fixed' && !t.fixed) return false;
    if (FVALS.nature === 'real' && t.fixed) return false;
    var range = FVALS.amount;
    if (range === '0-100' && (t.amt < 0 || t.amt >= 100)) return false;
    if (range === '100-1000' && (t.amt < 100 || t.amt >= 1000)) return false;
    if (range === '1000+' && t.amt < 1000) return false;
    return true;
  }}); }}
  // ===== 列头筛选下拉：下拉直接挂在列标题上（品类 / 来源 / 金额 / 性质），「全部」是菜单首项 =====
  var FVALS = {{cat: 'all', src: 'all', amount: 'all', nature: 'all'}};
  var COLFILTERS = [
    {{key: 'cat', dim: '品类', btn: 'btnCat', menu: 'menuCat'}},
    {{key: 'src', dim: '来源', btn: 'btnSource', menu: 'menuSource'}},
    {{key: 'amount', dim: '金额', btn: 'btnAmount', menu: 'menuAmount'}},
    {{key: 'nature', dim: '性质', btn: 'btnNature', menu: 'menuNature'}}
  ];
    var AMOUNT_OPTS = [['all', '全部'], ['0-100', '0~100'], ['100-1000', '100~1000'], ['1000+', '1000+']];
  var NATURE_OPTS = [['all', '全部'], ['real', '实际消费'], ['fixed', '固定支出']];
  var CFOPTS = {{}};
  function cfLabel(cf) {{
    var val = FVALS[cf.key];
    if (val === 'all') return cf.dim;
    var opts = CFOPTS[cf.key] || [];
    for (var i = 0; i < opts.length; i++) {{ if (opts[i][0] === val) return cf.dim + '：' + opts[i][1]; }}
    return cf.dim + '：' + val;
  }}
  function renderColFilter(cf) {{
    var btn = $(cf.btn), menu = $(cf.menu);
    if (btn) {{
      btn.innerHTML = '<span class="cf-label">' + esc(cfLabel(cf)) + '</span><span class="caret">▾</span>';
      btn.className = 'col-filter-btn' + (FVALS[cf.key] !== 'all' ? ' active' : '');
    }}
    if (!menu) return;
    menu.innerHTML = (CFOPTS[cf.key] || []).map(function(o){{
      var val = o[0], label = o[1], isTag = o[2];
      var inner = isTag
        ? '<span class="cat-tag" style="background:' + (CATCOLOR[val] || '#94A3B8') + ';color:#fff">' + esc(label) + '</span>'
        : esc(label);
      return '<button type="button" class="col-filter-option' + (FVALS[cf.key] === val ? ' chosen' : '')
        + '" data-key="' + cf.key + '" data-val="' + esc(val) + '">' + inner + '</button>';
    }}).join('');
  }}
  function closeColMenus() {{ COLFILTERS.forEach(function(cf) {{ var m = $(cf.menu); if (m) m.classList.remove('open'); }}); }}
  function closeMonthMenu() {{ if ($('monthMenu')) {{ $('monthMenu').classList.remove('open'); $('monthToggle').classList.remove('active'); }} }}
  function toggleColMenu(cf) {{
    var menu = $(cf.menu); if (!menu) return;
    var willOpen = !menu.classList.contains('open');
    closeColMenus();
    if (willOpen) menu.classList.add('open');
  }}
  function chooseColOption(e) {{
    var el = e.target.closest ? e.target.closest('[data-val]') : null;
    if (!el) return;
    var key = el.getAttribute('data-key');
    FVALS[key] = el.getAttribute('data-val');
    COLFILTERS.forEach(function(cf) {{ if (cf.key === key) renderColFilter(cf); }});
    closeColMenus(); renderTable();
  }}
  function populateTableFilters() {{
    var cats = [], sources = [];
    TXNS.forEach(function(t){{ if (cats.indexOf(t.cat) < 0) cats.push(t.cat); if (sources.indexOf(t.src) < 0) sources.push(t.src); }});
    cats.sort(); sources.sort();
    CFOPTS.cat = [['all', '全部']].concat(cats.map(function(x){{ return [x, x, 1]; }}));
    CFOPTS.src = [['all', '全部']].concat(sources.map(function(x){{ return [x, x, 0]; }}));
    CFOPTS.amount = AMOUNT_OPTS;
    CFOPTS.nature = NATURE_OPTS;
    COLFILTERS.forEach(renderColFilter);
  }}
  function monthParts(m){{ var p = m.split('-'); return [parseInt(p[0],10), parseInt(p[1],10)]; }}
  function monthText(m){{ var p = monthParts(m); return p[0] + '年' + p[1] + '月'; }}
  function monthIndex(m){{ var p = monthParts(m); return p[0] * 12 + p[1]; }}
  function selectedMonthLabel(){{
    var sel = selectedMonths(); if (!sel.length) return '未选择月份';
    var groups = [], group = [sel[0]];
    for (var i=1; i<sel.length; i++){{
      if (monthIndex(sel[i]) === monthIndex(sel[i-1]) + 1) group.push(sel[i]);
      else {{ groups.push(group); group = [sel[i]]; }}
    }}
    groups.push(group);
    return groups.map(function(g){{
      if (g.length === 1) return monthText(g[0]);
      var a = monthParts(g[0]), b = monthParts(g[g.length-1]);
      return a[0] === b[0] ? a[0] + '年' + a[1] + '~' + b[1] + '月' : monthText(g[0]) + '~' + monthText(g[g.length-1]);
    }}).join('、');
  }}
  function rangeLabel(){{ return selectedMonthLabel(); }}
  // 饼图/柱状图：JS 版与旧 charts.svg_donut / charts.svg_bars 视觉一致（viewBox 420，消费类统一）
  // 饼图：甜甜圈固定靠左，图例放在右侧，用 flex 保证图例块在剩余区域内水平+垂直居中
  var DONUT = {{size: 190, cx: 95, cy: 95, r: 68, stroke: 34}};
  function svgDonut(items) {{
    var total = 0; items.forEach(function(it){{ total += it[1]; }});
    var cx = DONUT.cx, cy = DONUT.cy, r = DONUT.r, stroke = DONUT.stroke;
    var C = 2*Math.PI*r, acc = 0, segs = '';
    items.forEach(function(it, i){{
      var frac = total ? it[1]/total : 0, dash = frac*C, gap = C-dash, rot = acc/C*360-90;
      segs += '<circle class="pie-seg" data-i="'+i+'" cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+it[2]+'" stroke-width="'+stroke+'" stroke-dasharray="'+dash.toFixed(2)+' '+gap.toFixed(2)+'" transform="rotate('+rot.toFixed(2)+' '+cx+' '+cy+')" style="cursor:pointer"/>';
      acc += frac*C;
    }});
    var rows = items.map(function(it){{
      var pct = total ? (it[1]/total*100).toFixed(1) : '0.0';
      return '<div class="donut-legend-row"><span class="donut-swatch" style="background:'+it[2]+'"></span>'
        + esc(it[0])+' '+fmtHKD(it[1])+' ('+pct+'%)</div>';
    }}).join('');
    var svg = '<svg viewBox="0 0 '+DONUT.size+' '+DONUT.size+'" style="width:100%;height:auto;display:block">'+segs+
      '<text x="'+cx+'" y="'+(cy-2)+'" text-anchor="middle" font-size="14" font-weight="700" fill="#0F172A">'+fmtHKD(total)+'</text>'+
      '<text x="'+cx+'" y="'+(cy+14)+'" text-anchor="middle" font-size="11" fill="#94A3B8">HKD 合计</text></svg>';
    return '<div class="donut-wrap"><div class="donut-fig">'+svg+'</div>'
      + '<div class="donut-legend"><div class="donut-legend-inner">'+rows+'</div></div></div>';
  }}
  // 饼图悬停提示：品类 / 金额 / 占比（跟随鼠标，悬停扇区加粗，右侧自动避开边界）
  function pieTipElement(container) {{
    var tip = container.querySelector ? container.querySelector('#pieTip') : null;
    if (!tip) {{
      tip = document.createElement('div');
      tip.id = 'pieTip'; tip.className = 'pie-tip';
      container.style.position = 'relative';
      container.appendChild(tip);
    }}
    return tip;
  }}
  function bindPieTooltip(items) {{
    var pieEl = $('pieChart'); if (!pieEl) return;
    var total = 0; items.forEach(function(it){{ total += it[1]; }});
    var tip = pieTipElement(pieEl);
    var segs = pieEl.querySelectorAll ? pieEl.querySelectorAll('.pie-seg') : [];
    for (var i = 0; i < segs.length; i++) {{
      (function(seg, item) {{
        function show(e) {{
          var rect = pieEl.getBoundingClientRect();
          var pct = total ? (item[1]/total*100).toFixed(1) : '0.0';
          tip.innerHTML = '<span style="color:'+item[2]+'">●</span> <b>'+esc(item[0])+'</b><br>'
            + fmtHKD(item[1]) + ' HKD · 占比 ' + pct + '%';
          tip.style.display = 'block';
          var x = e.clientX - rect.left + 12, y = e.clientY - rect.top + 12;
          if (x + 150 > rect.width) x = Math.max(0, e.clientX - rect.left - 150);
          tip.style.left = x + 'px'; tip.style.top = y + 'px';
          seg.setAttribute('stroke-width', DONUT.stroke + 6);
        }}
        function hide() {{ tip.style.display = 'none'; seg.setAttribute('stroke-width', DONUT.stroke); }}
        seg.addEventListener('mousemove', show);
        seg.addEventListener('mouseleave', hide);
      }})(segs[i], items[i]);
    }}
  }}
  function bindIndustryPie() {{
    var box=$('industryChart'); if(!box || !CFG.INDUSTRY_ITEMS) return;
    var tip=box.querySelector('#industryTip');
    if(!tip){{ tip=document.createElement('div'); tip.id='industryTip'; tip.className='pie-tip'; box.style.position='relative'; box.appendChild(tip); }}
    var segs=box.querySelectorAll('.industry-pie-seg'), items=CFG.INDUSTRY_ITEMS;
    for(var i=0;i<segs.length;i++) (function(seg,item){{
      function show(e){{ var rect=box.getBoundingClientRect(); tip.innerHTML='<span style="color:'+item[2]+'">●</span> <b>'+esc(item[0])+'</b><br>$'+Math.round(item[1]).toLocaleString()+' USD · 占股票 '+item[3].toFixed(1)+'%'; tip.style.display='block'; tip.style.left=Math.min(e.clientX-rect.left+12,rect.width-180)+'px'; tip.style.top=(e.clientY-rect.top+12)+'px'; seg.setAttribute('stroke-width','48'); }}
      function hide(){{tip.style.display='none';seg.setAttribute('stroke-width','42');}}
      seg.addEventListener('mousemove',show); seg.addEventListener('mouseleave',hide);
      seg.addEventListener('click',function(){{ var sel=$('industryFilter'); if(sel){{ var next=sel.value===item[0]?'all':item[0]; sel.value=next; renderIndustryHoldings(next); var d=box.closest ? box.closest('.section') : null; var details=d ? d.querySelector('.holdings-details') : null; if(details) details.open=true; }} }});
    }})(segs[i],items[i]);
  }}
  function bindAllocationCrosshair() {{
    var box=$('allocChart'); if(!box || !CFG.ALLOC_SERIES || !CFG.ALLOC_SERIES.length) return;
    var svg=box.querySelector('svg'), hits=box.querySelectorAll('.alloc-hit'), group=box.querySelector('#allocCrosshair'); if(!svg||!group) return;
    var tip=box.querySelector('#allocTip');
    if(!tip){{ tip=document.createElement('div'); tip.id='allocTip'; tip.className='pie-tip'; box.style.position='relative'; box.appendChild(tip); }}
    for(var i=0;i<hits.length;i++) (function(hit){{
      function show(e){{ var idx=parseInt(hit.getAttribute('data-i')), row=CFG.ALLOC_SERIES[idx], rect=svg.getBoundingClientRect(), sx=rect.width/760, sy=rect.height/340, x=(parseFloat(hit.getAttribute('x'))+parseFloat(hit.getAttribute('width'))/2)*sx;
        group.style.display='block'; $('allocV').setAttribute('x1',x/sx); $('allocV').setAttribute('x2',x/sx);
        [['allocDotCash','data-cash-y'],['allocDotStock','data-stock-y'],['allocDotOpt','data-opt-y']].forEach(function(pair){{ var d=$(pair[0]); d.setAttribute('cx',x/sx); d.setAttribute('cy',hit.getAttribute(pair[1])); }});
        tip.innerHTML='<b>'+row[0]+'</b><br><span style="color:#4A90D9">● 现金 '+row[1].toFixed(1)+'%</span><br><span style="color:#7A9A3F">● 股票 '+row[2].toFixed(1)+'%</span><br><span style="color:#C9A227">● 期权 '+row[3].toFixed(1)+'%</span>'; tip.style.display='block'; tip.style.left=Math.min(e.clientX-rect.left+12,rect.width-170)+'px'; tip.style.top=(e.clientY-rect.top+12)+'px'; }}
      function hide(){{group.style.display='none';tip.style.display='none';}}
      hit.addEventListener('mousemove',show); hit.addEventListener('mouseleave',hide);
    }})(hits[i]);
  }}
  var industryReturnSort = 0; // 0=默认持仓顺序，1=升序，-1=降序
  function renderIndustryHoldings(filter) {{
    var box=$('industryHoldings'); if(!box || !CFG.HOLDINGS) return;
    var rows=CFG.HOLDINGS.filter(function(h){{ return filter==='all' || h[1]===filter; }});
    if(industryReturnSort) rows.sort(function(a,b){{ return industryReturnSort * (a[6]-b[6]); }});
    var arrow=industryReturnSort===1?' ↑':(industryReturnSort===-1?' ↓':'');
    var html='<table class="holdings-table"><thead><tr><th>标的</th><th>行业</th><th>占净流动资产（%netliq）</th><th>市值</th><th>收益</th><th><button type="button" id="sortIndustryReturn" class="table-sort">收益率'+arrow+'</button></th></tr></thead><tbody>';
    rows.forEach(function(h){{ var c=h[6]>=0?'#2E7D32':'#C75B5B'; html+='<tr><td>'+esc(h[0])+'</td><td><span class="industry-tag" style="--tag-color:'+h[5]+'">'+esc(h[1])+'</span></td><td>'+h[2].toFixed(1)+'%</td><td>$'+Math.round(h[3]).toLocaleString()+'</td><td style="color:'+c+'">$'+Math.round(h[4]).toLocaleString()+'</td><td style="color:'+c+'">'+(h[6]>=0?'+':'')+h[6].toFixed(1)+'%</td></tr>'; }});
    html+='</tbody></table>'; box.innerHTML=html;
    var sortBtn=$('sortIndustryReturn'); if(sortBtn) sortBtn.addEventListener('click',function(){{ industryReturnSort=industryReturnSort===0?1:(industryReturnSort===1?-1:0); renderIndustryHoldings(filter); }});
  }}
  function svgBars(items) {{
    var width=420, height=220, pad_l=75, pad_r=55, pad_t=10, pad_b=10;
    var vmax = 1; items.forEach(function(it){{ vmax = Math.max(vmax, Math.abs(it[1])); }});
    var plot_w = width-pad_l-pad_r, row_h = (height-pad_t-pad_b)/items.length, out='';
    items.forEach(function(it, i){{
      var y = pad_t + row_h*i + row_h*0.25, bar_h = row_h*0.5, bar_w = plot_w*(it[1]/vmax);
      out += '<g><text x="'+(pad_l-8)+'" y="'+(y+bar_h*0.72).toFixed(1)+'" text-anchor="end" font-size="13" fill="#1E293B" font-weight="600">'+esc(it[0])+'</text>';
      out += '<rect x="'+pad_l+'" y="'+y.toFixed(1)+'" width="'+bar_w.toFixed(1)+'" height="'+bar_h.toFixed(1)+'" rx="3" fill="'+it[2]+'"/>';
      out += '<text x="'+(pad_l+bar_w+6).toFixed(1)+'" y="'+(y+bar_h*0.72).toFixed(1)+'" font-size="13" fill="'+it[2]+'" font-weight="700">'+fmtHKD(it[1])+'</text></g>';
    }});
    return '<svg viewBox="0 0 '+width+' '+height+'" style="width:100%;height:auto;display:block">'+out+'</svg>';
  }}
  function renderCharts() {{
    var list = filterTxns();
    var agg = {{}};
    CFG.CATS.forEach(function(c){{ agg[c] = 0; }});
    list.forEach(function(t){{ agg[t.cat] += t.amt; }});
    var items = [];
    CFG.CATS.forEach(function(c){{ if (agg[c] > 0) items.push([c, agg[c], CATCOLOR[c]]); }});
    var pieEl = $('pieChart'), barEl = $('barsChart');
    if (!pieEl || !barEl) return;
    if (!items.length) {{
      // 空状态按柱状图的实际高度（viewBox 420×220 等比缩放）撑满，保证筛选前后高度一致、页面不跳动
      var emptyH = Math.max(220, (barEl.clientWidth || 420) * 220 / 420).toFixed(1);
      var note = '<div style="min-height:' + emptyH + 'px;display:flex;align-items:center;justify-content:center;text-align:center;color:#94A3B8;font-size:13px">所选月份无消费记录</div>';
      pieEl.innerHTML = note; barEl.innerHTML = note; return;
    }}
    pieEl.innerHTML = svgDonut(items);
    bindPieTooltip(items);
    barEl.innerHTML = svgBars(items.slice().sort(function(a,b){{ return b[1]-a[1]; }}));
  }}
  function renderMetrics() {{
    var list = filterTxns();
    var total = 0; list.forEach(function(t){{ total += t.amt; }});
    var nMonths = Math.max(selectedMonths().length, 1);
    var days = CFG.DAYS_PER_MONTH * nMonths;
    var rl = rangeLabel();
    $('mSpend').textContent = fmtHKD(total);
    $('mSpendRange').textContent = 'HKD（' + rl + '）';
    $('mCount').textContent = list.length;
    $('mCountRange').textContent = '笔（' + rl + '）';
    $('mDaily').textContent = fmtHKD(total / days);
    if ($('secTitle')) $('secTitle').textContent = '品类消费（' + rl + '）';
    if ($('fnRange')) $('fnRange').textContent = rl;
    if ($('tab1DataRange')) $('tab1DataRange').textContent = '消费统计范围：' + rl;
  }}
  function renderMonthSelect() {{
    var sel = selectedMonths();
    var all = sel.length === MONTHS.length;
    // 未选择月份时把状态直接写在吸顶工具栏上，滚到表格任何位置都能看到
    var range = sel.length ? '月份：' + selectedMonthLabel() : '未选择月份（不展示明细）';
    var btn = $('monthToggle');
    if (btn) {{
      btn.title = range;
      btn.classList.toggle('active', !all);
    }}
    if ($('monthRange')) $('monthRange').textContent = range;
    var html = '<label class="month-option all"><input type="checkbox" data-m="__all__"' + (all ? ' checked' : '') + '>全选</label>';
    MONTHS.forEach(function(m){{ html += '<label class="month-option"><input type="checkbox" data-m="' + m + '"' + (SEL[m] ? ' checked' : '') + '>' + m + '<button type="button" class="month-only" data-only="' + m + '">仅此月</button></label>'; }});
    $('monthMenu').innerHTML = html;
  }}
  function onMonthOnlyClick(e) {{
    var btn = e.target.closest ? e.target.closest('[data-only]') : null;
    if (!btn) return;
    e.preventDefault(); e.stopPropagation();
    var only = btn.getAttribute('data-only');
    MONTHS.forEach(function(x){{ SEL[x] = x === only; }});
    renderMonthSelect(); renderTable(); renderCharts(); renderMetrics();
  }}
  function onMonthChange(e) {{
    var input = e.target;
    if (!input || input.tagName.toLowerCase() !== 'input') return;
    var m = input.getAttribute('data-m');
    if (m === '__all__') MONTHS.forEach(function(x){{ SEL[x] = input.checked; }});
    else SEL[m] = input.checked;
    renderMonthSelect(); renderTable(); renderCharts(); renderMetrics();
  }}
  function toggleMonthMenu() {{
    var menu = $('monthMenu'), btn = $('monthToggle'), open = !menu.classList.contains('open');
    menu.classList.toggle('open', open); btn.classList.toggle('active', open);
  }}
  // 明细区吸顶：区域标题 / 工具栏 / 列标题依次堆叠固定在页面顶端（类似 Excel 冻结窗格）
  function layoutStickyHead() {{
    var head = $('txnHead'), bar = $('txnBar'), table = $('txnTable');
    var top = 0;
    // 用 floor 让相邻吸顶块互相重叠 0~1px：高度常带小数（如 39.6px），
    // 若向上取整会在两层之间留下亚像素缝隙，滚动时行内容会从缝里透出来。
    // 先从吸顶标签栏的高度开始，三层吸顶才不会被标签栏盖住。
    var tabBar = $('tabBar');
    if (tabBar) {{ top += Math.floor(tabBar.getBoundingClientRect().height); }}
    if (head) {{ head.style.top = top + 'px'; top += Math.floor(head.getBoundingClientRect().height); }}
    if (bar) {{ bar.style.top = top + 'px'; top += Math.floor(bar.getBoundingClientRect().height); }}
    if (table && table.querySelectorAll) {{
      var ths = table.querySelectorAll('thead th');
      for (var i = 0; i < ths.length; i++) ths[i].style.top = top + 'px';
    }}
    updateStuckState();
    layoutOptionStickyTables();
  }}
  // 两张期权表分别计算偏移，只有开仓表需要为自己的吸顶标题留位置。
  function layoutOptionStickyTables() {{
    var tabBar = $('tabBar'), top = tabBar ? Math.floor(tabBar.getBoundingClientRect().height) : 0;
    var head = $('optionOpeningsHead');
    if (head) head.style.top = top + 'px';
    var tables = document.querySelectorAll ? document.querySelectorAll('.option-sticky') : [];
    for (var i = 0; i < tables.length; i++) {{
      var tableTop = top;
      if (head && tables[i].classList.contains('option-openings-table')) {{
        tableTop += Math.floor(head.getBoundingClientRect().height);
      }}
      var ths = tables[i].querySelectorAll('thead th');
      for (var j = 0; j < ths.length; j++) ths[j].style.top = tableTop + 'px';
    }}
  }}
  // 吸顶状态标记：滚动时给已吸顶的层加 .is-stuck（标题行据此补一条被滚走的分隔线）。
  // 只切 class、不读改布局尺寸，所以不会和 sticky 位置互相影响。
  function updateStuckState() {{
    var pairs = [['txnHead', 'is-stuck'], ['txnBar', 'is-stuck']];
    for (var i = 0; i < pairs.length; i++) {{
      var el = $(pairs[i][0]);
      if (!el || !el.classList || el.offsetParent === null) continue;   // 隐藏（另一个 Tab）时跳过
      var lim = parseFloat(el.style.top) || 0;
      el.classList.toggle(pairs[i][1], el.getBoundingClientRect().top <= lim + 0.5);
    }}
  }}
  function renderTable(){{
    var table = $('txnTable');
    // 渲染前后布局会变（行数增减），浏览器可能自动调整滚动位置造成视觉跳动，
    // 因此记住渲染前的滚动位置，渲染完成后再恢复。
    var keepScroll = window.scrollY;
    if (selectedMonths().length === 0) {{
      // 空状态：在表格里放一行提示，并用 height 保住表格原有高度。
      // 这样页面高度不变（滚动位置不会被浏览器强行改动），表头吸顶也不会失效
      // （表格塌成一行时 sticky 表头会跟着滚走，月份下拉会一起跑掉）。
      var keepH = Math.round(table.getBoundingClientRect().height);
      $('tblCount').textContent = '0 笔'; $('tblTotal').textContent = '0 HKD';
      $('txnBody').innerHTML = '<tr><td colspan="6" class="empty-cell"><span class="empty-note">未选择月份，不展示消费明细</span></td></tr>';
      table.style.height = keepH > 0 ? keepH + 'px' : '';
      restoreScroll(keepScroll);
      return;
    }}
    table.style.height = '';
    var kw = ($('searchInput').value||'').trim().toLowerCase();
    var list = filterTableTxns().filter(function(t){{
      if (!kw) return true;
      return (t.desc+' '+t.cat+' '+t.src).toLowerCase().indexOf(kw) >= 0;
    }});
    var total = 0;
    list.forEach(function(t){{ if (!t.fixed) total += t.amt; }});
    $('tblCount').textContent = list.length + ' 笔';
    $('tblTotal').textContent = total.toLocaleString(undefined,{{maximumFractionDigits:0}}) + ' HKD';
    var body = $('txnBody');
    body.innerHTML = list.map(function(t){{
      var nature = t.fixed ? '<span class="nature-tag nature-fixed">固定支出</span>' : '<span class="nature-tag nature-real">实际消费</span>';
      var category = t.fixed ? '<span class="cat-tag fixed-cat">固定支出</span>' : '<span class="cat-tag" style="background:'+(CATCOLOR[t.cat] || '#94A3B8')+';color:#fff">'+esc(t.cat)+'</span>';
      return '<tr><td>'+t.d+'</td><td class="desc">'+esc(t.desc)+'</td><td>'+category+'</td><td>'+esc(t.src)+'</td><td class="amt">'+t.amt.toLocaleString(undefined,{{minimumFractionDigits:2}})+'</td><td>'+nature+'</td></tr>';
    }}).join('') || '<tr><td colspan="6" style="text-align:center;color:#94A3B8">无匹配记录</td></tr>';
    layoutStickyHead();
    restoreScroll(keepScroll);
  }}
  function restoreScroll(y) {{ if (window.scrollTo && window.scrollY !== y) window.scrollTo(0, y); }}
  function switchTab(tab){{
    ['1', '2', '3', '4'].forEach(function(t){{
      var pane = $('tab' + t), btn = $('btn' + t);
      if (pane) pane.style.display = (t === tab) ? 'block' : 'none';
      if (btn) btn.className = 'tab-btn' + (t === tab ? ' active' : '');
    }});
    // 标签栏吸顶，所以切换后不必滚回页首；只有当新 Tab 的内容被压在标签栏上方（已滚过）时才对齐到内容开头
    var pane = $('tab' + tab), bar = $('tabBar');
    if (pane && bar && window.scrollTo) {{
      var bH = bar.offsetHeight, rect = pane.getBoundingClientRect();
      if (rect.top < bH - 2) {{
        window.scrollTo(0, Math.max(0, rect.top + (window.scrollY || window.pageYOffset || 0) - bH));
      }}
    }}
    layoutStickyHead();
  }}
  // 复利公式与 core.fv / core.fire_year 保持一致（修改需两边同步）
  function fv(p0, p, r, n) {{ if (r === 0) return p0 + p * n; var f = Math.pow(1+r, n); return p0 * f + p * (f-1)/r; }}
  function fireYear(p, r) {{ for (var y=1; y<=60; y++) {{ if (fv(P0, p, r, y*12) >= FIRE_USD) return y; }} return null; }}
  // 纵轴上限：按曲线最高点取「好看的整数」（写死的话，收益率一变曲线就冲出图顶）
  function niceMax(v) {{
    if (!(v > 0)) return 1000;
    var step = Math.pow(10, Math.floor(Math.log(v)/Math.LN10));
    var m = v/step;
    var nice = m<=1?1:m<=1.2?1.2:m<=1.5?1.5:m<=2?2:m<=2.5?2.5:m<=3?3:m<=4?4:m<=5?5:m<=6?6:m<=8?8:10;
    return nice*step;
  }}
  // 刻度条数：在 6/5/4/8 格里挑一个「步长是整数」的，标签才好看（如 250k、500k）
  function niceTicks(vmax) {{
    var cands=[6,5,4,8];
    for (var ci=0; ci<cands.length; ci++) {{
      var step=vmax/cands[ci], e=Math.pow(10,Math.floor(Math.log(step)/Math.LN10)), m=step/e;
      if (Math.abs(m-1)<1e-9||Math.abs(m-2)<1e-9||Math.abs(m-2.5)<1e-9||Math.abs(m-5)<1e-9) return cands[ci];
    }}
    return 8;
  }}
  function fmtAxis(v) {{
    if (v >= 1e6) return (v/1e6).toFixed(2).replace(/\\.?0+$/, '')+'M';   // 1.25M 而不是 1.3M
    return Math.round(v/1000)+'k';
  }}
  // 达到 FIRE 的年份（小数）：第几个月首次达标，10 年内没到返回 null
  function crossYear(p, r) {{
    for (var m=1; m<=120; m++) {{
      var cur=fv(P0,p,r,m);
      if (cur >= FIRE_USD) {{
        var prev=fv(P0,p,r,m-1);
        return (m-1+(FIRE_USD-prev)/(cur-prev))/12;
      }}
    }}
    return null;
  }}
  function svgLine(series, labels, vmax, height, width) {{
    height = height||320; width = width||680;
    var pad_l=74, pad_r=60, pad_t=30, pad_b=30;
    var plot_w=width-pad_l-pad_r, plot_h=height-pad_t-pad_b, n=labels.length;
    function X(i){{ return pad_l + (plot_w*i/(n-1)); }}
    function Y(v){{ return pad_t + plot_h*(1-v/vmax); }}
    var out='';
    out+='<text x="'+(width-10)+'" y="18" text-anchor="end" font-size="12" fill="#94A3B8" font-weight="600">单位：USD</text>';
    var ticks=niceTicks(vmax);
    for (var t=0;t<=ticks;t++){{ var v=vmax*t/ticks, gy=Y(v); out+='<line x1="'+pad_l+'" y1="'+gy.toFixed(1)+'" x2="'+(width-pad_r)+'" y2="'+gy.toFixed(1)+'" stroke="#EDF0F4"/><text x="'+(pad_l-8)+'" y="'+(gy+4).toFixed(1)+'" text-anchor="end" font-size="11" fill="#94A3B8">'+fmtAxis(v)+'</text>'; }}
    labels.forEach(function(lb,i){{ out+='<text x="'+X(i).toFixed(1)+'" y="'+(height-pad_b+16)+'" text-anchor="middle" font-size="12" fill="#94A3B8">'+lb+'年</text>'; }});
    // 先画 FIRE 目标虚线，再画各档曲线（曲线只画到达到目标那一刻，不会冲出图顶）
    series.filter(function(s){{return s.dashed;}}).concat(series.filter(function(s){{return !s.dashed;}}))
      .forEach(function(sr){{
        var pts=(sr.pts||[]).map(function(pt){{return X(pt.y).toFixed(1)+','+Y(pt.v).toFixed(1);}}).join(' ');
        var dash=sr.dashed?' stroke-dasharray="6 5"':'';
        out+='<polyline points="'+pts+'" fill="none" stroke="'+sr.color+'" stroke-width="2.2"'+dash+'/>';
      }});
    // 达标点：曲线落在 FIRE 线上的那个圆点
    series.forEach(function(sr){{
      if (sr.cross===null || sr.cross===undefined) return;
      out+='<circle cx="'+X(sr.cross).toFixed(1)+'" cy="'+Y(FIRE_USD).toFixed(1)+'" r="4.5" fill="#fff" stroke="'+sr.color+'" stroke-width="2.5"/>';
    }});
    series.forEach(function(sr,idx){{ var lx=pad_l+idx*130; out+='<g><line x1="'+lx+'" y1="'+(pad_t-10)+'" x2="'+(lx+24)+'" y2="'+(pad_t-10)+'" stroke="'+sr.color+'" stroke-width="2.5"/><text x="'+(lx+30)+'" y="'+(pad_t-6)+'" font-size="12" fill="#475569">'+sr.name+'</text></g>'; }});
    out+='<g id="chg" style="display:none"><line id="chv" x1="0" y1="'+pad_t+'" x2="0" y2="'+(height-pad_b)+'" stroke="#94A3B8" stroke-width="1" stroke-dasharray="4 3"/><line id="chh" x1="'+pad_l+'" y1="0" x2="'+(width-pad_r)+'" y2="0" stroke="#94A3B8" stroke-width="1" stroke-dasharray="4 3"/></g>';
    for (var di=0; di<series.length; di++){{ out+='<circle class="cdot" data-i="'+di+'" r="4" fill="'+series[di].color+'" stroke="#fff" stroke-width="2" style="display:none"/>'; }}
    out+='<rect id="chov" x="'+pad_l+'" y="'+pad_t+'" width="'+plot_w+'" height="'+plot_h+'" fill="transparent" style="cursor:crosshair"/>';
    return '<svg id="snowSvg" viewBox="0 0 '+width+' '+height+'" style="width:100%;height:auto;display:block">'+out+'</svg>';
  }}
  function bindCrosshair(series, labels, vmax) {{
    var svg=document.getElementById('snowSvg'); if(!svg) return;
    var chv=document.getElementById('chv'), chh=document.getElementById('chh'), chg=document.getElementById('chg');
    var chov=document.getElementById('chov');
    var dots=svg.querySelectorAll('.cdot');
    var tip=document.getElementById('chTip');
    if(!tip){{ tip=document.createElement('div'); tip.id='chTip'; tip.style.cssText='display:none;position:absolute;background:rgba(15,23,42,0.94);color:#fff;padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;z-index:20;line-height:1.7;white-space:nowrap'; svg.parentNode.style.position='relative'; svg.parentNode.appendChild(tip); }}
    var width=680,height=320,pad_l=74,pad_r=60,pad_t=30,pad_b=30;
    var plot_w=width-pad_l-pad_r, plot_h=height-pad_t-pad_b;
    function X(i){{return pad_l+plot_w*i/(labels.length-1);}}
    function Y(v){{return pad_t+plot_h*(1-v/vmax);}}
    chov.addEventListener('mousemove',function(e){{
      var rect=svg.getBoundingClientRect();
      var mx=(e.clientX-rect.left)*(width/rect.width);
      var idx=Math.round((mx-pad_l)/plot_w*(labels.length-1));
      idx=Math.max(0,Math.min(labels.length-1,idx));
      var px=X(idx); chg.style.display='block';
      chv.setAttribute('x1',px); chv.setAttribute('x2',px);
      var html='<b>第 '+labels[idx]+' 年</b><br>';
      var pyTop=Infinity, hset=false;   // 该年份最高的一条曲线（像素越小的 y 越高）
      series.forEach(function(sr,si){{
        var val=sr.data[idx], py=Y(val);
        // 这一年已经达标（曲线画到达标就停）→ 只报告达成时点，不再报超出图外的数字
        var done = (sr.cross!==null && sr.cross!==undefined && idx > sr.cross);
        if(done){{
          if(dots[si]) dots[si].style.display='none';
          html+='<span style="color:'+sr.color+'">●</span> '+sr.name+': <b>已达 FIRE（第 '+sr.cross.toFixed(1)+' 年）</b><br>';
          return;
        }}
        if(py<pyTop) pyTop=py;
        if(!hset){{chh.setAttribute('y1',py);chh.setAttribute('y2',py);hset=true;}}
        if(dots[si]){{dots[si].style.display='block';dots[si].setAttribute('cx',px);dots[si].setAttribute('cy',py);}}
        html+='<span style="color:'+sr.color+'">●</span> '+sr.name+': <b>$'+Math.round(val).toLocaleString()+'</b><br>';
      }});
      tip.innerHTML=html; tip.style.display='block';
      // 落点：先定左右（优先放竖线右侧，越界就翻到左侧），
      // 再在这一横向区间里找「没有被任何曲线或 FIRE 虚线穿过」的最大纵向空档，把提示框塞进去——避免压住曲线。
      var tipW=tip.offsetWidth||180, tipH=tip.offsetHeight||96, scl=rect.width/width;
      var tw=tipW/scl, th=tipH/scl;
      var bx0=px+14, bx1=bx0+tw;
      if(bx1>width-6){{ bx1=px-14; bx0=bx1-tw; }}
      if(bx0<6){{ bx0=6; bx1=bx0+tw; }}
      var obs=[];
      series.forEach(function(sr){{
        var lo=Infinity, hi=-Infinity;
        for(var xi=bx0; xi<=bx1; xi+=4){{
          var fi=(xi-pad_l)/plot_w*(labels.length-1);
          if(sr.cross!==null && sr.cross!==undefined && fi>sr.cross) continue;   // 这条线到这里已经结束
          var i0=Math.max(0,Math.min(labels.length-1,Math.floor(fi)));
          var i1=Math.min(labels.length-1,i0+1), tt=fi-i0;
          var vv=sr.data[i0]*(1-tt)+sr.data[i1]*tt, yy=Y(vv);
          if(yy>=pad_t && yy<=height-pad_b){{ if(yy<lo) lo=yy; if(yy>hi) hi=yy; }}
        }}
        if(lo<Infinity) obs.push([lo,hi]);
      }});
      obs.sort(function(a,b){{ return a[0]-b[0]; }});
      var topLim=pad_t+4, botLim=height-pad_b-4, best=null, cur=topLim;
      obs.forEach(function(o){{
        if(o[0]>cur){{ var g=o[0]-cur; if(!best||g>best[1]) best=[cur,g]; }}
        if(o[1]>cur) cur=o[1];
      }});
      if(botLim>cur){{ var g2=botLim-cur; if(!best||g2>best[1]) best=[cur,g2]; }}
      var ty=best ? best[0]+Math.max(0,(best[1]-th)/2) : topLim;
      if(ty+th>botLim) ty=Math.max(topLim, botLim-th);
      tip.style.left=(bx0*scl)+'px'; tip.style.top=(ty*scl)+'px';
    }});
    chov.addEventListener('mouseleave',function(){{ chg.style.display='none'; tip.style.display='none'; for(var i=0;i<dots.length;i++) dots[i].style.display='none'; }});
  }}
  function renderSnowball(rateKey) {{
    var twrMode = rateKey === 'twr';
    if ($('twrControls')) $('twrControls').hidden = !twrMode;
    if ($('rateToolbar')) $('rateToolbar').classList.toggle('twr-mode', twrMode);
    if ($('twrStatus')) {{
      $('twrStatus').hidden = !twrMode;
      $('twrStatus').textContent = TWR_MANUAL ? '已手动调整 · 仅用于模拟，历史收益不变'
        : (CFG.TWR_IS_REAL ? '账户历史 TWR · 自动填入' : '模拟参考值 · 暂无账户 TWR');
    }}
    var annual = RATES[rateKey], r = Math.pow(1+annual,1/12)-1;
    var years = []; for (var y=0;y<=10;y++) years.push(String(y));
    // data = 10 年完整数值（悬停用）；pts = 画线用（画到达标那一刻为止）；cross = 达标年份
    var series = LEVELS.map(function(p,idx){{
      var full = years.map(function(yy){{ return fv(P0,p,r,parseInt(yy)*12); }});
      var cy = crossYear(p, r), pts = [];
      for (var y=0; y<=(cy===null?10:Math.floor(cy)); y++) pts.push({{y:y, v:fv(P0,p,r,y*12)}});
      if (cy !== null) pts.push({{y:cy, v:FIRE_USD}});
      return {{name: p.toLocaleString()+' USD/月', color: SCOLORS[idx], data: full, pts: pts, cross: cy}};
    }});
    series.push({{name:'FIRE 目标', color:'#C75B5B', dashed:true, cross:null,
                  data: years.map(function(){{return FIRE_USD;}}),
                  pts:[{{y:0,v:FIRE_USD}},{{y:10,v:FIRE_USD}}]}});
    // 纵轴围绕 FIRE 目标（略高于目标即可）——曲线的最高点就是目标线，不再为了「不冲出图顶」把上限撑到几百万
    var vmax = niceMax(FIRE_USD*1.15);
    if ($('snowChart')) $('snowChart').innerHTML = svgLine(series, years, vmax);
    bindCrosshair(series, years, vmax);
    var body='';
    LEVELS.forEach(function(p,idx){{ var s10=fv(P0,p,r,120), fy=fireYear(p,r); var cls=idx===2?' class="total"':''; body+='<tr'+cls+'><td>'+p.toLocaleString()+' USD/月</td><td>$'+s10.toLocaleString(undefined,{{maximumFractionDigits:0}})+'</td><td>'+(fy?'第 '+fy+' 年':'60 年内未达')+'</td></tr>'; }});
    if ($('snowBody')) $('snowBody').innerHTML = body;
    if ($('rateLabel')) $('rateLabel').textContent = '→ ' + RATE_LABELS[rateKey];
  }}
  // ===== 大额支出决策 =====
  // FIRE 推迟改为真算（复利公式与 core.fv / fire_year 一致）：
  //   期末定投 p、月利率 r，t 个月后达到目标 T 的闭式解 t = ln((T + p/r) / (B + p/r)) / ln(1+r)
  //   多笔支出分布在不同月份时无闭式解 → 逐月模拟，并在跨过目标的那个月做线性插值
  function fireMonthsToTarget(balance, contrib, r, withdrawals) {{
    var keys = withdrawals ? Object.keys(withdrawals) : [];
    if (r === 0) return contrib > 0 ? (FIRE_USD - balance) / contrib : null;
    if (!keys.length) {{
      var num = (FIRE_USD + contrib / r) / (balance + contrib / r);
      return num > 0 ? Math.log(num) / Math.log(1 + r) : 0;
    }}
    var bal = balance, prevGap = FIRE_USD - balance;
    for (var m = 1; m <= 60 * 12; m++) {{
      if (withdrawals[m]) bal -= withdrawals[m];
      bal = bal * (1 + r) + contrib;
      var gap = FIRE_USD - bal;
      if (gap <= 0) return (m - 1) + prevGap / (prevGap - gap);
      prevGap = gap;
    }}
    return null;
  }}
  // 把「单次金额 × 次数 + 间隔」展开成"第几个月 → 金额"的映射
  function bigSpendWithdrawals(usdOnce, times, interval) {{
    var w = {{}};
    if (interval === 'same') {{ w[1] = usdOnce * times; return w; }}
    var step = interval === 'year' ? 12 : 1;
    for (var i = 0; i < times; i++) {{
      var m = 1 + i * step;
      w[m] = (w[m] || 0) + usdOnce;
    }}
    return w;
  }}
  function spendVerdict(pctFrac, monthsEquiv) {{
    if (pctFrac < BS.low_pct && monthsEquiv < BS.low_months) return {{ text: '✅ 几乎无影响', color: '#2E7D32' }};
    if (pctFrac < BS.high_pct && monthsEquiv < BS.high_months) return {{ text: '⚠️ 有一定影响', color: '#B26A00' }};
    return {{ text: '❌ 建议分批', color: '#C75B5B' }};
  }}
  function checkBigSpend() {{
    var hkdOnce = parseFloat($('bigSpend').value) || 0;
    var times = Math.max(1, Math.floor(parseFloat($('bsTimes') ? $('bsTimes').value : 1) || 1));
    var interval = $('bsInterval') ? $('bsInterval').value : 'same';
    var usdOnce = hkdOnce / USD_HKD;
    var usdTotal = usdOnce * times;                 // 累计金额（判定对象）
    var rateKey = $('rateSel') ? $('rateSel').value : 'nasdaq';
    var annual = typeof RATES[rateKey] === 'number' ? RATES[rateKey] : RATES.nasdaq;
    var r = Math.pow(1 + annual, 1/12) - 1;

    var baseMonths = fireMonthsToTarget(P0, MONTHLY_INVEST, r);
    var withMonths = fireMonthsToTarget(P0, MONTHLY_INVEST, r, bigSpendWithdrawals(usdOnce, times, interval));
    var delay = (withMonths === null || baseMonths === null) ? null : Math.max(withMonths - baseMonths, 0);

    var pctFrac = usdTotal / P0;                    // 占净资产（次要参考）
    var monthsEquiv = usdTotal / MONTHLY_INVEST;
    var once = spendVerdict(usdOnce / P0, usdOnce / MONTHLY_INVEST);
    var total = spendVerdict(pctFrac, monthsEquiv);

    // ===== 主判断：现金视角（支出只从现金/短债出，不卖股票）=====
    // 按「间隔」逐月模拟现金：每月先扣掉当月该花的钱（保守：支出发生后才算月底结余到账），
    // 所以「每月一次 × N」和「同一月内 × N」虽然合计一样，对现金的压力完全不同。
    var hkdTotal = hkdOnce * times;
    var spendable = CASH.spendable, cashNow = CASH.cash, emergency = CASH.emergency, essential = CASH.essential;
    var monthlyNet = CASH.monthly_net || 0;
    function cashSim(perTime, count, kind) {{
      var horizon = kind === 'same' ? 1 : (kind === 'month' ? count : (count - 1) * 12 + 1);
      var bal = cashNow, min = bal, minMonth = 0;
      for (var m = 1; m <= horizon; m++) {{
        var spend = 0;
        if (kind === 'same') spend = (m === 1) ? perTime * count : 0;
        else if (kind === 'month') spend = (m <= count) ? perTime : 0;
        else spend = (((m - 1) % 12 === 0) && ((m - 1) / 12 < count)) ? perTime : 0;
        bal -= spend;
        if (bal < min) {{ min = bal; minMonth = m; }}
        bal += monthlyNet;                     // 月底结余到账
      }}
      return {{ horizon: horizon, min: min, minMonth: minMonth, end: bal }};
    }}
    var sim = cashSim(hkdOnce, times, interval);
    var minCash = sim.min, minMonth = sim.minMonth;
    var monthsAfter = essential > 0 ? minCash / essential : null;
    var left = spendable - hkdTotal;                      // 合计相对可花现金（一次性口径的参考）
    var cashVerdict, cashColor;
    if (minCash >= emergency) {{ cashVerdict = '✅ 不用卖股票'; cashColor = '#2E7D32'; }}
    else if (minCash >= 0) {{ cashVerdict = '⚠️ 会动到应急金'; cashColor = '#B26A00'; }}
    else {{ cashVerdict = '❌ 现金不够'; cashColor = '#C75B5B'; }}

    if ($('bsTotal')) $('bsTotal').textContent = 'HK$' + Math.round(hkdTotal).toLocaleString();
    $('bsUsd').textContent = '$' + Math.round(usdTotal).toLocaleString();
    // 「摊到每月」：同一月内 = 全部落在当月；每月一次 = 单次；每年一次 = 合计摊到模拟期
    if ($('bsPerMonth')) {{
      var perMonthAvg = hkdTotal / Math.max(sim.horizon, 1);
      $('bsPerMonth').textContent = 'HK$' + Math.round(perMonthAvg).toLocaleString();
      $('bsPerMonth').style.color = perMonthAvg > monthlyNet ? '#B26A00' : '#2E7D32';
    }}
    if ($('bsMin')) {{
      $('bsMin').textContent = 'HK$' + Math.round(minCash).toLocaleString();
      $('bsMin').style.color = minCash >= emergency ? '#2E7D32' : (minCash >= 0 ? '#B26A00' : '#C75B5B');
    }}
    if ($('bsMinMonth')) {{
      $('bsMinMonth').textContent = minMonth > 1 ? '（第 ' + minMonth + ' 个月）' : '（当月）';
    }}
    if ($('bsMonthsLeft')) {{
      $('bsMonthsLeft').textContent = monthsAfter === null ? '—' : monthsAfter.toFixed(1) + ' 个月';
      $('bsMonthsLeft').style.color = (monthsAfter !== null && monthsAfter < 3) ? '#C75B5B' : '#1E293B';
    }}
    $('bsPct').textContent = (pctFrac*100).toFixed(2) + '%';
    $('bsPct').style.color = total.color;
    $('bsMonths').textContent = monthsEquiv < 0.1 ? '< 0.1 个月' : monthsEquiv.toFixed(1) + ' 个月';
    $('bsDelay').textContent = delay === null ? '60 年内未达成'
      : (delay < 0.05 ? '< 0.05 个月' : '约 ' + delay.toFixed(2) + ' 个月');
    $('bsVerdict').textContent = cashVerdict;
    $('bsVerdict').style.color = cashColor;
    if (CASH.credit_debt_missing || CASH.credit_date_mismatch) {{
      $('bsVerdict').textContent = '现金数据待核对';
      $('bsVerdict').style.color = '#B26A00';
    }}

    var timesLabel = interval === 'same' ? '同一月内 ' + times + ' 次'
      : (interval === 'month' ? '每月 1 次，共 ' + times + ' 次' : '每年 1 次，共 ' + times + ' 次');
    var advice = '本次按「' + timesLabel + '」计算：单次 HK$' + Math.round(hkdOnce).toLocaleString()
      + ' × ' + times + ' = 合计 HK$' + Math.round(hkdTotal).toLocaleString()
      + '，占可花现金 ' + (spendable > 0 ? (hkdTotal / spendable * 100).toFixed(0) : '—') + '%。';
    if (interval === 'same') {{
      advice += ' 一次性拿出 HK$' + Math.round(hkdTotal).toLocaleString()
        + '，现金最低点 HK$' + Math.round(minCash).toLocaleString()
        + (monthsAfter === null ? '' : '（' + monthsAfter.toFixed(1) + ' 个月必要支出）') + '。';
    }} else {{
      var perMonth = interval === 'month' ? hkdOnce : (hkdOnce / 12);
      var netPerMonth = perMonth - monthlyNet;
      advice += ' 分摊后每月约 HK$' + Math.round(perMonth).toLocaleString()
        + '，而你每月结余是 HK$' + Math.round(monthlyNet).toLocaleString()
        + '（每月净 ' + (netPerMonth > 0 ? '−' : '+') + 'HK$' + Math.round(Math.abs(netPerMonth)).toLocaleString() + '）'
        + '；模拟 ' + sim.horizon + ' 个月，现金最低点第 ' + minMonth + ' 个月 HK$' + Math.round(minCash).toLocaleString()
        + (monthsAfter === null ? '' : '（' + monthsAfter.toFixed(1) + ' 个月必要支出）') + '。';
      if (monthlyNet >= perMonth) advice += ' 因为每月结余能覆盖这笔分摊支出，不会再动到应急金。';
    }}
    if (cashVerdict.charAt(0) === '⚠') advice += ' ⚠️ 会动到应急金（现金最低点 ' + (monthsAfter === null ? '—' : monthsAfter.toFixed(1) + ' 个月') + '）。';
    if (monthsAfter !== null && monthsAfter < 3) advice += ' ⚠️ 低于 3 个月必要支出，建议分期或先从下个月结余里扣。';
    if (times > 1 && once.text !== total.text) advice += ' ⚠️ 单次看是「' + once.text + '」，累计 ' + times + ' 次后变成「' + total.text + '」——只看单次会漏掉重复消费的影响。';
    $('bsAdvice').textContent = (CASH.credit_debt_missing ? '未提供信用卡未偿还欠款，下列金额尚未扣减，不能据此确认可花额度。'
      : CASH.credit_date_mismatch ? '信用卡欠款与银行余额日期不同，下列结果需先核对还款，避免重复扣减。' : '') + advice;
    if ($('bsSellAdvice')) {{
      var sell = '如果只能卖股票：占净资产 ' + (pctFrac*100).toFixed(2) + '%、相当于 ' + monthsEquiv.toFixed(2) + ' 个月定投';
      sell += delay === null ? '；60 年内达不到 FIRE。' : '；FIRE 达成时间推迟约 ' + delay.toFixed(2) + ' 个月（按当前年化 ' + (annual*100).toFixed(0) + '% 逐月模拟）。';
      $('bsSellAdvice').textContent = sell;
    }}

    if ($('bsOnce')) $('bsOnce').textContent = times > 1
      ? '单次判定：' + once.text + '（' + (usdOnce/P0*100).toFixed(2) + '% 净资产 / ' + (usdOnce/MONTHLY_INVEST).toFixed(2) + ' 个月定投）'
      : '';

    // 本月已发生的大额消费（单笔 ≥ 冷静期阈值，固定支出除外）——把"已经花掉的那几次"也纳入视野
    if ($('bsHistory')) {{
      var th = CFG.BIG_SPEND_THRESHOLD || 0, cm = CFG.CALC_MONTH || '';
      var n = 0, sum = 0;
      TXNS.forEach(function(t){{ if (!t.fixed && t.d.slice(0,7) === cm && t.amt >= th) {{ n++; sum += t.amt; }} }});
      var thTxt = Math.round(th).toLocaleString();
      if (!n) {{
        $('bsHistory').textContent = cm + ' 没有单笔 ≥ HK$' + thTxt + ' 的消费（大额阈值 = 单笔冷静期额度）。';
      }} else {{
        var thisMonthPlan = (interval === 'same' ? usdTotal : usdOnce) * USD_HKD;
        var monthTotal = sum + thisMonthPlan;
        var over = (monthTotal / USD_HKD) / P0 >= BS.high_pct;
        $('bsHistory').innerHTML = cm + ' 已发生的大额消费（单笔 ≥ HK$' + thTxt + '）：<b>' + n + ' 笔，合计 HK$'
          + Math.round(sum).toLocaleString() + '</b>；加上本次落在本月的 HK$' + Math.round(thisMonthPlan).toLocaleString()
          + ' → <b style="color:' + (over ? '#C75B5B' : '#475569') + '">本月大额累计 HK$' + Math.round(monthTotal).toLocaleString() + '</b>'
          + (over ? '（已超过 ' + (BS.high_pct*100) + '% 净资产阈值）' : '');
      }}
    }}
  }}
  function bindAccountReturns() {{
    function percent(value) {{ return value == null ? '—' : (value >= 0 ? '+' : '') + (value * 100).toFixed(1) + '%'; }}
    var seriesMode = 'both';
    function clearTips() {{
      document.querySelectorAll('.return-chart-tooltip').forEach(function(tip) {{ tip.style.display = 'none'; }});
      document.querySelectorAll('.return-crosshair').forEach(function(line) {{ line.style.opacity = 0; }});
    }}
    document.querySelectorAll('[data-return-mode]').forEach(function(button) {{
      button.addEventListener('click', function() {{
        seriesMode = this.getAttribute('data-return-mode');
        document.querySelectorAll('[data-return-mode]').forEach(function(btn) {{
          btn.setAttribute('aria-pressed', btn.getAttribute('data-return-mode') === seriesMode ? 'true' : 'false');
        }});
        document.querySelectorAll('[data-return-series]').forEach(function(line) {{
          line.toggleAttribute('hidden', seriesMode !== 'both' && line.getAttribute('data-return-series') !== seriesMode);
        }});
        document.querySelectorAll('[data-return-legend]').forEach(function(label) {{
          label.hidden = seriesMode !== 'both' && label.getAttribute('data-return-legend') !== seriesMode;
        }});
        clearTips();
      }});
    }});
    var buttons = document.querySelectorAll('[data-return-period]');
    for (var i = 0; i < buttons.length; i++) buttons[i].addEventListener('click', function() {{
      var key = this.getAttribute('data-return-period'), period = (CFG.PERFORMANCE_PERIODS || {{}})[key];
      if (!period) return;
      clearTips();
      document.querySelectorAll('[data-return-period]').forEach(function(btn) {{
        btn.setAttribute('aria-pressed', btn.getAttribute('data-return-period') === key ? 'true' : 'false');
      }});
      document.querySelectorAll('[data-return-chart]').forEach(function(panel) {{ panel.hidden = panel.getAttribute('data-return-chart') !== key; }});
      ['twr', 'mwr'].forEach(function(method) {{ ['total', 'annual'].forEach(function(metric) {{
        var value = period[method + '_' + metric], el = $('return-' + method + '-' + metric);
        el.textContent = percent(value);
        el.className = value > 0 ? 'gain' : value < 0 ? 'loss' : '';
      }}); }});
      $('returnPeriodDesc').textContent = period.start + '~' + period.end + '，' + period.days + ' 天'
        + (period.partial ? ' · 历史不足，按可用区间' : '') + ' · 股票、期权与现金整体账户 · USD';
    }});
    document.querySelectorAll('.return-chart').forEach(function(svg) {{
      var rows = JSON.parse(svg.getAttribute('data-series')), panel = svg.parentElement;
      var tip = panel.querySelector('.return-chart-tooltip'), line = svg.querySelector('.return-crosshair');
      svg.addEventListener('pointermove', function(event) {{
        var point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
        var local = point.matrixTransform(svg.getScreenCTM().inverse());
        var row = rows.reduce(function(best, item) {{ return Math.abs(item[3] - local.x) < Math.abs(best[3] - local.x) ? item : best; }}, rows[0]);
        line.setAttribute('x1', row[3]); line.setAttribute('x2', row[3]); line.style.opacity = 1;
        var values = [];
        if (seriesMode !== 'mwr') values.push('TWR ' + percent(row[1] / 100));
        if (seriesMode !== 'twr') values.push('MWR ' + percent(row[2] == null ? null : row[2] / 100));
        tip.innerHTML = esc(row[0]) + '<br>' + values.join(' · ');
        tip.style.display = 'block';
        var box = panel.getBoundingClientRect();
        var x = event.clientX - box.left + 12;
        if (x + tip.offsetWidth > box.width - 8) x = event.clientX - box.left - tip.offsetWidth - 12;
        tip.style.left = Math.max(8, Math.min(box.width - tip.offsetWidth - 8, x)) + 'px';
        tip.style.top = Math.max(8, Math.min(box.height - tip.offsetHeight - 8, event.clientY - box.top - tip.offsetHeight - 12)) + 'px';
      }});
      svg.addEventListener('pointerleave', function() {{ tip.style.display = 'none'; line.style.opacity = 0; }});
    }});
  }}
  try {{
    if ($('searchInput')) $('searchInput').addEventListener('input', renderTable);
    if ($('monthToggle')) $('monthToggle').addEventListener('click', function(ev){{
      ev.stopPropagation(); closeColMenus(); toggleMonthMenu();
    }});
    COLFILTERS.forEach(function(cf){{
      if ($(cf.btn)) $(cf.btn).addEventListener('click', function(ev){{
        ev.stopPropagation(); closeMonthMenu(); toggleColMenu(cf);
      }});
      if ($(cf.menu)) $(cf.menu).addEventListener('click', chooseColOption);
    }});
    if ($('monthMenu')) $('monthMenu').addEventListener('click', onMonthOnlyClick);
    if ($('monthMenu')) $('monthMenu').addEventListener('change', onMonthChange);
    document.addEventListener('click', function(e){{
      var root = $('monthSelect');
      if (root && !root.contains(e.target)) {{ $('monthMenu').classList.remove('open'); $('monthToggle').classList.remove('active'); }}
      closeColMenus();
    }});
    if ($('btn1')) $('btn1').addEventListener('click', function(){{ switchTab('1'); }});
    if ($('btn2')) $('btn2').addEventListener('click', function(){{ switchTab('2'); }});
    if ($('btn3')) $('btn3').addEventListener('click', function(){{ switchTab('3'); }});
    if ($('btn4')) $('btn4').addEventListener('click', function(){{ switchTab('4'); }});
    if ($('rateSel')) $('rateSel').addEventListener('change', function(){{ renderSnowball(this.value); checkBigSpend(); }});
    renderMonthSelect();
    populateTableFilters();
    renderTable();
    renderCharts();
    bindIndustryPie();
    bindAllocationCrosshair();
    if ($('industryFilter')) $('industryFilter').addEventListener('change', function(){{ renderIndustryHoldings(this.value); }});
    renderIndustryHoldings('all');
    bindAccountReturns();
    renderMetrics();
    renderSnowball($('rateSel') ? $('rateSel').value : 'twr');
    layoutStickyHead();
    // 图表按宽度布局；预览容器的高度变化不应触发全量重绘。
    var chartViewportWidth = document.documentElement.clientWidth, resizeTick = false;
    if (window.addEventListener) window.addEventListener('resize', function(){{
      if (resizeTick) return;
      resizeTick = true;
      var run = function() {{
        resizeTick = false;
        var width = document.documentElement.clientWidth;
        if (width === chartViewportWidth) return;
        chartViewportWidth = width;
        layoutStickyHead(); renderCharts();
      }};
      if (window.requestAnimationFrame) window.requestAnimationFrame(run); else setTimeout(run, 16);
    }});
    // 滚动时更新「已吸顶」标记（只切 class，用 rAF 节流，避免每帧读布局造成抖动）
    if (window.addEventListener) {{
      var stickyTick = false;
      window.addEventListener('scroll', function() {{
        if (stickyTick) return;
        stickyTick = true;
        var run = function() {{ stickyTick = false; updateStuckState(); }};
        if (window.requestAnimationFrame) window.requestAnimationFrame(run); else setTimeout(run, 16);
      }}, {{passive: true}});
    }}
    // TWR 年化可手填（IBKR TWR 模式下生效）：改完立刻重绘曲线与大额支出判定
    if ($('twrInput')) $('twrInput').addEventListener('input', function() {{
      var v = parseFloat(this.value);
      if (isNaN(v) || v <= -100) return;
      TWR_MANUAL = true;
      RATES.twr = v / 100;
      RATE_LABELS.twr = 'IBKR TWR · 模拟年化 ' + v.toFixed(1) + '%（手动填写）';
      if ($('rateSel') && $('rateSel').value === 'twr') {{ renderSnowball('twr'); checkBigSpend(); }}
    }});
    ['bigSpend', 'bsTimes'].forEach(function(id){{ if ($(id)) $(id).addEventListener('input', checkBigSpend); }});
    if ($('bsInterval')) $('bsInterval').addEventListener('change', checkBigSpend);
    if ($('bigSpend')) {{ $('bigSpend').addEventListener('input', checkBigSpend); checkBigSpend(); }}
  }} catch(e) {{ console.error(e); }}
}})();
"""


def build_cash_html(cash):
    """把「真实可动用现金 / 应急金 / 可花现金」做成卡片内容。
    cash 来自 core.cash_panel()；可花现金也是下面「能买什么」梯度的计算基准。"""
    spendable = cash["spendable_hkd"]
    cash_total = cash["cash_hkd"]
    emergency = cash["emergency_hkd"]
    months = cash.get("months_cover")
    bank, ibkr_hkd = cash.get("bank_hkd"), cash.get("ibkr_hkd", 0.0)
    debt_missing = cash.get("credit_debt_missing", cash.get("credit_card_debt_hkd") is None)
    credit_pending = debt_missing or cash.get("credit_date_mismatch", False)
    spend_label = "可花现金上限（未扣信用卡）" if debt_missing else "可花现金（已扣信用卡）"
    cash_label = "现金上限（欠款待补充）" if debt_missing else "净现金（已扣信用卡）"

    spend_color = "#2E7D32" if spendable >= 0 else "#C75B5B"
    kpi = (
        '<div class="kpis">'
        f'<div class="kpi"><div class="k1">{spend_label}</div>'
        f'<div class="k2" style="color:{spend_color}">{fmt(spendable)} '
        f'<span style="font-size:12px;color:#6B7280">HKD</span></div></div>'
        f'<div class="kpi"><div class="k1">{cash_label}</div>'
        f'<div class="k2" style="color:#4A90D9">{fmt(cash_total)} '
        f'<span style="font-size:12px;color:#6B7280">HKD</span></div></div>'
        f'<div class="kpi"><div class="k1">应急金（{cash["emergency_months"]:.0f} × 月必要支出 '
        f'{fmt(cash["essential_monthly"])}）</div>'
        f'<div class="k2" style="color:#B26A00">{fmt(emergency)} '
        f'<span style="font-size:12px;color:#6B7280">HKD</span></div></div>'
        f'<div class="kpi"><div class="k1">现金能撑</div>'
        f'<div class="k2">{(f"{months:.1f}" if months is not None else "—")} '
        f'<span style="font-size:12px;color:#6B7280">个月必要支出</span></div></div>'
        '</div>'
    )


    src_rows = []
    if bank is not None:
        src_rows.append(f'银行储蓄余额 <b>{fmt(bank)}</b> HKD'
                        + (f'（{cash["bank_date"]:%Y-%m-%d} 快照）' if cash.get("bank_date") else ''))
    else:
        src_rows.append('银行储蓄余额 <b>未读到</b>（流水里没有 Balance 列）')
    if cash.get("ibkr_usd") is not None:
        note = '（负数 = 用了保证金）' if cash["ibkr_usd"] < 0 else ''
        src_rows.append(f'IBKR 现金 <b>${fmt(cash["ibkr_usd"])}</b>'
                        f'（≈ {fmt(abs(cash["ibkr_hkd"]))} HKD{note}）'
                        + (f' · {escape(cash["ibkr_source"])}' if cash.get("ibkr_source") else ''))
    else:
        src_rows.append('IBKR 现金 <b>未接入</b>（Gateway 和 Flex 均无可用现金数据）')
    if debt_missing:
        src_rows.append('信用卡未偿还欠款 <b style="color:#B26A00">待补充</b>（交易流水不等于欠款余额）')
    else:
        src_rows.append(f'信用卡未偿还欠款 <b>−{fmt(cash["credit_card_debt_hkd"])}</b> HKD'
                        + (f'（{cash["credit_card_debt_date"]:%Y-%m-%d} 快照）' if cash.get("credit_card_debt_date") else ''))
    src_html = ('<div style="display:flex;gap:22px;flex-wrap:wrap;font-size:12px;color:#64748B;'
                'margin:2px 0 12px">' + ''.join(f'<div>{r}</div>' for r in src_rows) + '</div>')
    if debt_missing:
        src_html += '<div class="info-note">信用卡欠款未提供：当前现金和可花金额是未扣欠款的上限，不能作为已扣债务的可花额度。</div>'
    elif cash.get("credit_date_mismatch"):
        src_html += '<div class="info-note">银行余额与信用卡欠款的快照日期不同；需核对期间还款，避免将已从银行扣款的还款再次扣减。</div>'

    tier_html = ""
    for threshold, name, icon, price in config.RESERVOIR_TIERS:
        is_unlocked = not credit_pending and spendable >= threshold
        bg = "#F0FDF4" if is_unlocked else "#F8FAFC;opacity:0.55"
        fw = "700" if is_unlocked else "400"
        sc = "#2E7D32" if is_unlocked else "#94A3B8"
        badge = "待核对" if credit_pending else "✅" if is_unlocked else "🔒 " + format(threshold, ",")
        tier_html += (f'<div style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:6px;background:{bg}">'
                      f'<span style="font-size:18px">{icon}</span>'
                      f'<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:{fw};color:#1E293B">{name}</div>'
                      f'<div style="font-size:11px;color:#94A3B8">{price}</div></div>'
                      f'<span style="font-size:11px;font-weight:600;color:{sc};white-space:nowrap">{badge}</span></div>')

    unlocked = [t for t in config.RESERVOIR_TIERS if spendable >= t[0]]
    if credit_pending:
        unlocked_text = '<div class="info-note">欠款余额或快照日期待核对，暂不判断当前现金可以买什么。</div>'
    elif unlocked:
        unlocked_text = (f'<div style="background:linear-gradient(135deg,#F0FDF4,#ECFDF5);border-radius:8px;padding:12px 16px;margin-bottom:12px">'
                         f'<div style="font-size:12px;color:#64748B">可花现金 {fmt(spendable)} HKD，现在就能买</div>'
                         f'<div style="font-size:18px;font-weight:700;color:#1E293B;margin-top:2px">{unlocked[-1][2]} {unlocked[-1][1]}</div>'
                         f'<div style="font-size:12px;color:#64748B">{unlocked[-1][3]}</div></div>')
    else:
        unlocked_text = (f'<div style="background:#FFFBEB;border-radius:8px;padding:12px 16px;margin-bottom:12px">'
                         f'<div style="font-size:12px;color:#92400E">可花现金 {fmt(spendable)} HKD —— 还没超出应急金，先别动</div>'
                         f'<div style="font-size:16px;font-weight:700;color:#1E293B;margin-top:2px">🛟 先把应急金存满，再考虑这些</div></div>')

    nxt = next((t for t in config.RESERVOIR_TIERS if spendable < t[0]), None)
    if nxt and spendable > 0 and not credit_pending:
        next_pct = min(spendable / nxt[0] * 100, 100)
        next_text = (f'<div style="margin-top:10px"><div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">'
                     f'<span style="color:#64748B">下一个：{nxt[2]} {nxt[1]}</span>'
                     f'<span style="font-weight:600;color:#4A90D9">{next_pct:.0f}%</span></div>'
                     f'<div style="background:#F1F5F9;border-radius:4px;height:16px;overflow:hidden">'
                     f'<div style="width:{next_pct:.0f}%;height:100%;background:linear-gradient(90deg,#4A90D9,#7A9A3F);border-radius:4px"></div></div>'
                     f'<div style="font-size:11px;color:#94A3B8;margin-top:4px">还差 {fmt(max(nxt[0] - spendable, 0))} HKD</div></div>')
    else:
        next_text = ""

    note = (f'<div class="info-note" style="margin-top:12px"><b>怎么算：</b>'
            f'净现金 = 银行储蓄余额 + IBKR 现金 − 未偿还信用卡欠款；应急金 = {cash["emergency_months"]:.0f} × 月必要支出'
            f'（房租 + 必要消费 = {fmt(cash["essential_monthly"])} HKD/月）；'
            f'<b>可花现金 = 净现金 − 应急金</b>；未提供欠款时仅展示未扣欠款的上限。'
            f'下面这张清单用可花现金算进度（旧版的「消费蓄水池余额」= 计算月结余，和「月结余」是同一个数，已合并到这里）。<br>'
            f'<b>两个注意：</b>① 银行余额是最近一次交易时的快照（有滞后），IBKR 现金优先取 Gateway 当前快照，不可用时取 Flex 最近净值行，来源日期见上方；'
            f'② 如果短期债券/货币基金不在 IBKR 账户里，别忘了把它也算进现金。</div>')
    return kpi + src_html + unlocked_text + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px">' + tier_html + '</div>' + next_text + note


def build_option_offset_links_js():
    """按已核验的合约关联键绘制冲减关系线；仅处理布局与高亮，不配腿或分摊数量。"""
    return r'''(function(){
  var stage=document.getElementById('optionOffsetStage');
  if(!stage)return;
  var svg=stage.querySelector('svg'), ns='http://www.w3.org/2000/svg', frame=0, active='';
  var nodes=Array.from(stage.querySelectorAll('[data-option-offset-key]'));
  function highlight(key){
    active=key;
    stage.classList.toggle('has-active-offset',!!key);
    nodes.forEach(function(n){n.classList.toggle('is-active-offset',n.dataset.optionOffsetKey===key);});
    svg.querySelectorAll('g').forEach(function(g){g.classList.toggle('is-active-offset',g.dataset.optionOffsetKey===key);});
  }
  function draw(){
    frame=0;
    if(!stage.getClientRects().length||!stage.offsetWidth)return;
    var base=stage.getBoundingClientRect(), groups=new Map(), columnEnds=new Map();
    svg.setAttribute('viewBox','0 0 '+stage.offsetWidth+' '+stage.offsetHeight);
    svg.setAttribute('width',stage.offsetWidth);svg.setAttribute('height',stage.offsetHeight);
    svg.replaceChildren();
    nodes.forEach(function(n){
      var key=n.dataset.optionOffsetKey;
      if(!groups.has(key))groups.set(key,[]);
      var r=n.getBoundingClientRect(), column=n.closest('td').cellIndex, end=r.left-base.left-4;
      columnEnds.set(column,Math.min(columnEnds.has(column)?columnEnds.get(column):end,end));
      groups.get(key).push({node:n,column:column,y:r.top-base.top+r.height/2});
    });
    groups.forEach(function(points,key){
      if(!points.some(function(p){return p.node.dataset.optionSide==='BUY';})||!points.some(function(p){return p.node.dataset.optionSide==='SELL';}))return;
      var g=document.createElementNS(ns,'g');g.dataset.optionOffsetKey=key;
      // 每列共用端点轴，横臂等宽，不受BUY/SELL文字宽度或关系顺序影响。
      var end=columnEnds.get(points[0].column), lane=end-18;
      var ys=points.map(function(p){return p.y;});
      var d='M '+lane+' '+Math.min.apply(null,ys)+' V '+Math.max.apply(null,ys);
      points.forEach(function(p){d+=' M '+lane+' '+p.y+' H '+end;});
      var path=document.createElementNS(ns,'path');path.setAttribute('d',d);g.appendChild(path);
      points.forEach(function(p){var dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',end);dot.setAttribute('cy',p.y);dot.setAttribute('r','2.5');g.appendChild(dot);});
      svg.appendChild(g);
    });
    highlight(active);
  }
  function schedule(){if(!frame)frame=requestAnimationFrame(draw);}
  function targetKey(target){var n=target.closest&&target.closest('[data-option-offset-key]');return n?n.dataset.optionOffsetKey:'';}
  stage.addEventListener('pointerover',function(e){highlight(targetKey(e.target));});
  stage.addEventListener('pointerleave',function(){highlight('');});
  stage.addEventListener('focusin',function(e){highlight(targetKey(e.target));});
  stage.addEventListener('focusout',function(e){highlight(e.relatedTarget?targetKey(e.relatedTarget):'');});
  window.addEventListener('resize',schedule);
  if(window.ResizeObserver)new ResizeObserver(schedule).observe(stage);
  var pane=document.getElementById('tab3');
  if(pane&&window.MutationObserver)new MutationObserver(schedule).observe(pane,{attributes:true,attributeFilter:['style']});
  if(document.fonts&&document.fonts.ready)document.fonts.ready.then(schedule);
  schedule();
})();'''


def build_option_positions_html(positions, description, strategies=None):
    """当前持仓仅显示策略组合行，无池/到期区块或逐腿持仓清单。"""
    def number(value,percent=False):
        return '—' if value is None else f'{value:,.2f}'+('%' if percent else '')
    def tone(value):
        return 'option-pnl-positive' if value is not None and value>0 else 'option-pnl-negative' if value is not None and value<0 else ''
    if positions is None:
        content='<div class="info-note">暂无可用的当前期权持仓快照；历史收益仍见下表。</div>'
    elif not positions:
        content='<div class="info-note">当前快照确认没有期权持仓。</div>'
    else:
        strategies=reconstruct_option_strategies(positions,[]) if strategies is None else strategies
        buckets=group_option_holdings(positions)
        totals={field:sum(group[field] for group in buckets) if all(group[field] is not None for group in buckets) else None for field in ('pnl','cost','value')}
        ratio=totals['pnl']/abs(totals['cost'])*100 if totals['pnl'] is not None and totals['cost'] else None
        metrics=[('未实现盈亏 · USD',totals['pnl'],False,True),('盈亏率',ratio,True,True),('持仓市值 · USD',totals['value'],False,False),('净成本 · USD',totals['cost'],False,False)]
        metric_html=''.join('<div><small>'+label+'</small><b class="'+(tone(value) if colored else '')+'">'+number(value,percent)+'</b></div>' for label,value,percent,colored in metrics)
        rows=[]
        for row in strategies:
            expiry=row['expiry']
            if len(expiry)==8 and expiry.isdigit():expiry=expiry[:4]+'-'+expiry[4:6]+'-'+expiry[6:]
            cells=[]
            for kind in ('P','C'):
                selected=[leg for leg in row['legs'] if leg.get('type')==kind and leg.get('strike') is not None]
                selected.sort(key=lambda leg:(leg.get('side')!='SELL',leg['strike']))
                leg_html=[]
                for leg in selected:
                    attributes=(' data-option-offset-key="'+escape(json.dumps(leg['offset_key'],ensure_ascii=False),quote=True)+'" data-option-side="'+escape(leg['side'],quote=True)+'" tabindex="0"' if leg.get('offset_key') else '')
                    leg_html.append('<span class="option-offset-anchor"'+attributes+'>'+escape(leg['side']+' '+f'{leg["strike"]:.2f}')+('<small class="option-offset-leg">涉及冲减</small>' if leg.get('offset') else '')+'</span>')
                cells.append('<br>'.join(leg_html) or '—')
            rows.append('<tr><td>'+escape(row['symbol'])+'</td><td class="option-strategy-cell"><span class="option-offset-anchor">'+escape(row['name'])+('<small class="option-offset-badge" title="该策略有腿与其他策略的反向腿发生净额抵销；保留原策略展示，不能视为全部腿仍独立持有。">涉及冲减</small>' if row.get('has_offset') else '')+'</span></td><td>'+(f'{row["quantity"]:g}' if row['quantity'] is not None else '待核验')+'</td><td>'+escape(expiry or '未提供')+'</td><td>'+cells[0]+'</td><td>'+cells[1]+'</td></tr>')
        content='<div class="chart-card"><div class="option-position-metrics">'+metric_html+'</div><div class="option-position-legs"><div class="option-offset-stage" id="optionOffsetStage"><table class="holdings-table option-strategy-table"><colgroup><col class="option-col-symbol"><col class="option-col-strategy"><col class="option-col-quantity"><col class="option-col-expiry"><col class="option-col-put"><col class="option-col-call"></colgroup><thead><tr><th>标的</th><th>策略</th><th>组数</th><th>到期日</th><th>Put行权价</th><th>Call行权价</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table><svg class="option-offset-links" aria-hidden="true"></svg></div></div></div>'
    return '<div class="section" id="currentOptionHoldings"><div class="section-header"><div class="section-title">当前期权组合</div></div><div class="tab-data-note">'+escape(description)+'</div>'+content+'</div>'


def render_report(data, cf, sim_series, sim_years, freedom_ladder,
                  wf2_svg, ladder_svg,
                  usd_hkd, fx_time, p0_usd, fire_target_usd, output_path,
                  twr_annual=None, twr_note="", twr_total=None,
                  alloc_svg="", alloc_kpi=None, cash=None, opt_note="", opt_monthly=None,
                  opt_monthly_desc="", stock_positions=None, industry_groups=None, alloc_series=None,
                  option_openings=None, equity_extra=None, mwr=None, performance_periods=None, stock_data_desc="",
                  option_positions=None, option_positions_desc="", option_strategy_rows=None):
    """组装完整 HTML 报告。月度/滚雪球 SVG 来自 charts 层；Spending & Transactions 的饼图/柱状图由
    report.js 动态渲染（随月份筛选联动，见 build_js 的 svgDonut/svgBars）。
    输出文件固定文件名覆盖（只保留最新一份）。"""
    option_positions_html = build_option_positions_html(option_positions, option_positions_desc, option_strategy_rows)
    month_key = cf["month_key"]
    latest_date = cf["latest_date"]

    month_level, partial_note = month_completeness(month_key, latest_date)
    month_suffix = "至今" if month_level == "in_progress" else ""

    cash_card_html = build_cash_html(cash) if cash else (
        '<div class="info-note">未接入现金数据（需要银行流水里的 Balance 列 + IBKR 现金）。</div>')

    if opt_monthly:
        rows_html = ""
        tot_open = tot_cash = tot_real = 0.0
        tot_opens = tot_closes = 0
        tot_open_qty = tot_close_qty = 0.0
        for row in opt_monthly:
            tot_open += row.get("open_cash", 0.0)
            tot_cash += row["cash_net"]
            tot_real += row["realized"]
            tot_opens += row.get("opens", 0)
            tot_closes += row.get("closes", 0)
            tot_open_qty += row.get("open_qty", 0.0)
            tot_close_qty += row.get("close_qty", 0.0)
            rows_html += (
                f'<tr><td style="text-align:center">{row["month"]}</td>'
                f'<td style="text-align:center">{row.get("opens", 0)}</td>'
                f'<td style="text-align:center">{fmt(row.get("open_cash", 0))}</td>'
                f'<td style="text-align:center">{row["closes"]}</td>'
                f'<td style="text-align:center">{fmt(row["realized"])}</td>'
                f'<td style="text-align:center">{fmt(row["cash_net"])}</td></tr>')
        rows_html += (
            f'<tr class="total"><td style="text-align:center">合计</td>'
            f'<td style="text-align:center">{tot_opens}</td><td style="text-align:center">{fmt(tot_open)}</td>'
            f'<td style="text-align:center">{tot_closes}</td><td style="text-align:center">{fmt(tot_real)}</td>'
            f'<td style="text-align:center">{fmt(tot_cash)}</td></tr>')
        opt_monthly_html = (
            '<table class="option-monthly-table option-sticky"><colgroup><col style="width:10%"><col style="width:19%"><col style="width:15%"><col style="width:19%"><col style="width:19%"><col style="width:18%"></colgroup><thead><tr><th>月份</th><th>开仓数量（组合腿合并，成交笔数）</th><th>开仓现金流入（净）</th>'
            '<th>Close 数量（组合腿合并，平仓笔数）</th><th>Close 已实现收益（当月平仓已实现（净））</th><th>全部交易净现金流（当月现金流入（净））</th></tr></thead>'
            f'<tbody>{rows_html}</tbody></table>'
            '<div class="info-note" style="margin-top:12px"><b>两种口径怎么读：</b><br>'
            '① <b>开仓现金流入</b> = 只统计 `openCloseIndicator = O` 的开仓净现金（已扣佣金与交易费）；<br>'
            '② <b>Close 已实现收益</b> = IBKR 的 `fifoPnlRealized`，按平仓日归集；Close 数量按 IBKR 的 `openCloseIndicator = C` 统计，即使该笔收益为 0 也会计入；<br>'
            '③ <b>全部交易净现金流</b> = 当月所有开仓和 Close 交易的净现金，用来和现金账户核对。<br>'
            f'<b>数量核对：</b>上表“开仓/Close 数量”按 IBKR 的组合订单分组；累计实际腿数量约为开仓 {tot_open_qty:,.0f} 张、Close {tot_close_qty:,.0f} 张，数量差约 {tot_open_qty - tot_close_qty:,.0f} 张。'
            '同一组合的一组长腿和短腿按 1 组计，10 组同样的组合按 10 组计；到期日自动生成的两条腿按买卖两侧配对，单腿交易按实际数量计数。<br>'
            '<b>注意两点：</b>ⓐ 卖出 put 被行权时（合成数据不包含真实指派记录），权利金并入股票成本、期权这边记 0，'
            '那几个月「已实现」会偏低；ⓑ 到期和平仓可能集中发生在部分交易日，所以周内数据看起来是"跳着走"的，'
            '本演示不会自动刷新或连接券商。</div>')
    else:
        opt_monthly_html = '<div class="info-note">未接入 IBKR Flex（启用后这里会按月份列出期权收入的两种口径）。</div>'
    if opt_monthly:
        latest_opt = opt_monthly[-1]
        option_summary_html = (
            '<div class="option-summary">'
            f'<div class="option-kpi"><span>本月开仓现金流入（净）</span><b>${fmt(latest_opt.get("open_cash", 0))}</b>'
            f'<small>{latest_opt["month"]} · {latest_opt.get("opens", 0)} 组开仓</small></div>'
            f'<div class="option-kpi"><span>本月 Close 已实现收益</span><b>${fmt(latest_opt.get("realized", 0))}</b>'
            f'<small>{latest_opt["month"]} · {latest_opt.get("closes", 0)} 组 Close</small></div></div>')
    else:
        option_summary_html = ""
    option_openings = option_openings or []
    opening_rows = "".join(
        f'<tr><td>{escape(x.get("date") or "日期未提供")}</td><td>{escape(x["underlying"])}</td><td>{x["quantity"]:g}</td><td>{escape(x["strategy"])}</td><td>{build_opening_strikes_html(x)}</td><td>'+ '<br>'.join(escape(part) for part in x.get("otm_text", "缺少该日行情").split('; '))+f'</td><td>{escape(x["expiry"])}</td></tr>'
        for x in option_openings)
    option_openings_html = (
        '<div class="section"><div class="section-header option-opening-head" id="optionOpeningsHead"><div class="section-title">Option Opening Details</div>'
        '<div class="section-desc">历史成交按具体日期逐笔列示；虚值距离仅显示卖出腿</div></div><div class="chart-card option-table-card"><table class="option-openings-table option-sticky"><colgroup><col style="width:11%"><col style="width:8%"><col style="width:7%"><col style="width:17%"><col style="width:24%"><col style="width:22%"><col style="width:11%"></colgroup><thead><tr>'
        '<th>成交日期</th><th>标的</th><th>数量</th><th>策略</th><th>行权价</th><th>短腿虚值距离</th><th>到期日</th></tr></thead><tbody>'
        + (opening_rows or '<tr><td colspan="7">未接入 IBKR Flex 期权明细</td></tr>') + '</tbody></table>'
        '<div class="info-note option-note">行权价按Put、Call分行，先SELL、后BUY。虚值距离按成交日标的未复权收盘价计算，仅展示卖出腿；Iron Condor展示Put、Call两条短腿。正值为虚值，负值为实值，不代表成交瞬间距离；缺失行情显示具体日期和原因。</div></div></div>')
    stock_positions = stock_positions or []
    equity_extra = equity_extra or {}
    if stock_positions:
        industry_groups = industry_groups or []
        group_colors = {i: charts.INDUSTRY_COLORS[idx % len(charts.INDUSTRY_COLORS)] for idx, (i, _, _) in enumerate(industry_groups)}
        industry_rows = "".join(
            f'<div class="industry-note" style="--tag-color:{group_colors[i]}"><b>{i}</b><span>{w:.1f}% · ${v:,.0f}</span><small>{config.INDUSTRY_GROUP_NOTES.get(i, "以长期基本面和估值为主，定期复核。")}</small></div>'
            for i, w, v in industry_groups)
        holding_rows = "".join(
            f'<tr><td>{p["symbol"]}</td><td><span class="industry-tag" style="--tag-color:{group_colors.get(config.INDUSTRY_GROUPS.get(p["industry"], "其他"), "#64748B")}">{config.INDUSTRY_GROUPS.get(p["industry"], "其他")}</span></td><td>{p["weight"]:.1f}%</td><td>${p["value"]:,.0f}</td><td style="color:{"#2E7D32" if p["pnl"] >= 0 else "#C75B5B"}">${p["pnl"]:,.0f}</td><td style="color:{"#2E7D32" if p["return_pct"] >= 0 else "#C75B5B"}">{p["return_pct"]:+.1f}%</td></tr>'
            for p in stock_positions)
        stock_analysis_html = (
            '<div class="section"><div class="section-header"><div class="section-title">正股行业分布</div>'
            '<div class="section-desc">合并为少数长期观察类别</div></div><div class="chart-card">'
            '<div class="industry-layout"><div id="industryChart">' + charts.svg_industry_donut([(i, w) for i, w, _ in industry_groups]) + '</div>'
            f'<div class="industry-notes">{industry_rows}</div></div>'
            '<details class="holdings-details"><summary>查看正股明细</summary>'
            '<div class="industry-filter"><label for="industryFilter">行业筛选</label><select id="industryFilter"><option value="all">全部行业</option>'
            + ''.join(f'<option value="{i}">{i}</option>' for i, _, _ in industry_groups)
            + '</select></div><div id="industryHoldings">'
            '<table class="holdings-table"><thead><tr><th>标的</th><th>行业</th><th>占净流动资产（%netliq）</th><th>市值</th><th>收益</th><th>收益率</th></tr></thead>'
            f'<tbody>{holding_rows}</tbody></table></div></details></div></div>')
    else:
        stock_analysis_html = ('<div class="section"><div class="section-header"><div class="section-title">正股行业分类与长期观察</div></div>'
                               '<div class="chart-card"><div class="info-note">当前快照没有可展示的正股多头持仓，或持仓数据尚未接入。</div></div></div>')
    extra_html = build_equity_analysis_html(equity_extra)
    drawdown_html = build_equity_analysis_html(equity_extra, drawdown_only=True)
    cat_colors = {k: config.PIE_COLORS[k] for k in config.CATS}

    rates = dict(config.RATES)
    rate_labels = dict(config.RATE_LABELS)
    if twr_annual is not None:
        rates["twr"] = twr_annual


        cumulative = f"，累计 {twr_total*100:+.1f}%" if twr_total is not None else ""
        rate_labels["twr"] = (
            f"演示 TWR ·  {twr_note.split('，')[-1]}{cumulative} → 年化 {twr_annual*100:.1f}%（回溯值）"
        )
    twr_is_real = twr_annual is not None

    return_rows = ""
    for key, label, caption, total, annual in (
        ("twr", "时间加权", "剔除外部出入金影响", twr_total, twr_annual),
        ("mwr", "资金加权", "计入资金投入时点", (mwr or {}).get("mwr_total"), (mwr or {}).get("mwr_annual")),
    ):
        total_text = f"{total * 100:+.1f}%" if total is not None else "—"
        annual_text = f"{annual * 100:+.1f}%" if annual is not None else "—"
        total_class = "gain" if total is not None and total > 0 else "loss" if total is not None and total < 0 else ""
        annual_class = "gain" if annual is not None and annual > 0 else "loss" if annual is not None and annual < 0 else ""
        return_rows += (
            f'<div class="return-panel {key}"><div class="return-method"><strong>{key.upper()}</strong>'
            f'<span>{label}</span></div><dl class="return-values">'
            f'<div class="return-value"><dt>总收益率 · 区间累计</dt><dd id="return-{key}-total" class="{total_class}">{total_text}</dd></div>'
            f'<div class="return-value annual"><dt>年化收益率</dt><dd id="return-{key}-annual" class="{annual_class}">{annual_text}</dd></div>'
            f'</dl><div class="return-caption">{caption}</div></div>'
        )
    returns_desc = twr_note if twr_is_real else "暂无可用 IBKR 收益数据"
    performance_periods = performance_periods or {}
    period_controls = ''.join(
        f'<button type="button" data-return-period="{key}" aria-pressed="{"true" if key == "ALL" else "false"}"'
        f'{" disabled" if key not in performance_periods else ""}>{label}</button>'
        for key, label in (("YTD", "YTD"), ("1YEAR", "1 YEAR"), ("ALL", "ALL")))
    return_charts = ''.join(
        f'<div class="return-chart-panel" data-return-chart="{key}"{" hidden" if key != "ALL" else ""}>'
        + charts.svg_account_returns(period["series"])
        + '<div class="return-chart-tooltip"></div></div>'
        for key, period in performance_periods.items())
    if not return_charts:
        return_charts = '<div class="info-note">暂无可用收益曲线。</div>'
    returns_html = (
        '<div class="section" id="accountReturns"><div class="section-header">'
        '<div class="section-title">账户收益率</div>'
        f'<div class="section-desc" id="returnPeriodDesc">{returns_desc} · 股票、期权与现金整体账户 · USD</div></div>'
        f'<div class="returns-grid">{return_rows}</div>'
        '<div class="return-chart-header"><div class="return-chart-legend"><span data-return-legend="twr"><i></i>TWR</span><span data-return-legend="mwr"><i class="mwr-line"></i>MWR</span></div>'
        '<div class="return-chart-controls"><div class="return-periods" role="group" aria-label="收益曲线类型">'
        '<button type="button" data-return-mode="twr" aria-pressed="false">TWR</button>'
        '<button type="button" data-return-mode="mwr" aria-pressed="false">MWR</button>'
        '<button type="button" data-return-mode="both" aria-pressed="true">两者</button></div>'
        f'<div class="return-periods" role="group" aria-label="收益统计区间">{period_controls}</div></div></div>{return_charts}'
        '<details class="return-notes"><summary>统计口径</summary><p>TWR 剔除外部出入金的影响，ALL 与 Tab2 的历史 TWR 一致；'
        'MWR 按资金投入时点计算 IRR，累计值按相同统计区间复利折算。'
        '缺失值表示数据不足或无有效解。</p></details></div>'
    )

    alloc_desc, alloc_kpi_html, alloc_note_html = "", "", ""
    if alloc_svg and alloc_kpi:
        k = alloc_kpi
        alloc_desc = (f"{k['first']} ~ {k['last']} · {k['days']} 个交易日 · "
                      f"只统计总资产 ≥ ${config.TWR_MIN_FUNDED_USD:,.0f} 的日子（与 TWR 同一门槛）")
        alloc_kpi_html = (
            '<div class="kpis">'
            f'<div class="kpi"><div class="k1">当前现金占比</div>'
            f'<div class="k2" style="color:#4A90D9">{k["latest"]:.1f}%</div></div>'
            f'<div class="kpi"><div class="k1">当前股票占比</div>'
            f'<div class="k2" style="color:#7A9A3F">{k["stock_latest"]:.1f}%</div></div>'
            f'<div class="kpi"><div class="k1">当前期权占比</div>'
            f'<div class="k2" style="color:#C9A227">{k["opt_latest"]:.1f}%</div></div>'
            f'<div class="kpi"><div class="k1">用保证金的天数（现金为负）</div>'
            f'<div class="k2" style="color:#B26A00">{k["margin_days"]} '
            f'<span style="font-size:12px;color:#6B7280">天</span></div></div>'
            '</div>'
        )
        alloc_note_html = (
            '<div class="info-note"><b>怎么读：</b>三条线都是「÷ 当日总资产」，'
            '<b>三者之和恒等于 100%</b>（账户净值口径）：现金 + 股票 + 期权（按市价）。'
            '所以「现金占比」就是有多少钱在场外等机会，股票占比就是实际仓位。'
            '<b>现金为负 = 用了保证金</b>（借钱持股），这时股票会超过 100%（最极端的一天：现金 −155% + 股票 257% = 约 2.6 倍杠杆）；'
            '期权为负 = 卖出开仓（按市价计负债），为正 = 买入持仓。'
            f"这一段：现金占比 {k['first_val']:.0f}% → 中位 {k['median']:.0f}% → 现在 {k['latest']:.1f}%"
            f"（期间区间 {k['low']:.0f}% ~ {k['high']:.0f}%）；"
            f"股票占比中位 {k['stock_median']:.0f}%；期权中位 {k['opt_median']:.1f}%；"
            f"有 {k['margin_days']} 天现金为负。"
            '<b>和收益率的关系：</b>TWR 是时间加权口径，自动包含现金拖累——现金闲着时收益被摊薄，'
            '这就是它低于「满仓纳指」的原因之一。</div>'
        )
    industry_items = []
    holdings_items = []
    if industry_groups:
        for idx, (name, weight, amount) in enumerate(industry_groups):
            industry_items.append([name, amount, charts.INDUSTRY_COLORS[idx % len(charts.INDUSTRY_COLORS)], weight])
    if stock_positions:
        color_map = {item[0]: item[2] for item in industry_items}
        for p in stock_positions:
            group = config.INDUSTRY_GROUPS.get(p["industry"], "其他")
            holdings_items.append([p["symbol"], group, p["weight"], p["value"], p["pnl"], color_map.get(group, "#64748B"), p["return_pct"]])
    js_cfg = {
        "P0": p0_usd,
        "FIRE_USD": fire_target_usd,
        "USD_HKD": usd_hkd,
        "LEVELS": [p for _, p in config.INVEST_LEVELS],
        "RATES": rates,
        "RATE_LABELS": rate_labels,
        "MONTHLY_INVEST": config.FIXED_INVEST_USD,
        "BIG_SPEND": config.BIG_SPEND,
        "CATS": list(config.CATS),
        "DAYS_PER_MONTH": config.DAYS_PER_MONTH,
        "DEFAULT_RATE": config.DEFAULT_RATE,
        "TWR_IS_REAL": twr_is_real,

        "CALC_MONTH": month_key,
        "BIG_SPEND_THRESHOLD": cf["mindless_cooling"],

        "CASH": {
            "spendable": (cash or {}).get("spendable_hkd", 0.0),
            "cash": (cash or {}).get("cash_hkd", 0.0),
            "emergency": (cash or {}).get("emergency_hkd", 0.0),
            "essential": (cash or {}).get("essential_monthly", 0.0),
            "months": (cash or {}).get("months_cover"),
            "credit_debt_missing": (cash or {}).get("credit_debt_missing", (cash or {}).get("credit_card_debt_hkd") is None),
            "credit_date_mismatch": (cash or {}).get("credit_date_mismatch", False),


            "monthly_net": cf["month_surplus"],
        },
        "INDUSTRY_ITEMS": industry_items,
        "HOLDINGS": holdings_items,
        "ALLOC_SERIES": [[d.isoformat(), c, s, o] for d, c, s, o in (alloc_series or [])],
        "PERFORMANCE_PERIODS": {key: {field: value for field, value in period.items() if field != "series"}
                                for key, period in performance_periods.items()},
    }

    rate_options = "".join(
        f'<option value="{key}"{" selected" if key == config.DEFAULT_RATE else ""}>'
        f'{rate_labels[key]}</option>'
        for key in rates
    )

    fixed_items = data.get("utility_bills", [])
    js = build_js(data["txns"] + fixed_items, js_cfg, cat_colors)
    utility_plan = cf.get("utility_plan")
    utility_note = ""
    if utility_plan:
        rows_html = ""
        for item in utility_plan["components"]:
            detail = item["status"]
            if item["rows"]:
                detail += "；扣款日期 " + "、".join(r["date"] for r in item["rows"])
                if item["usage_month"]:
                    detail += "；对应 " + item["usage_month"] + " 用量，作为当前月预算参考"
                if item["kind"] == "gas":
                    detail += f"；净费用 {fmt2(sum(r['net'] for r in item['rows']))} ÷ {item['coverage_months']} 个月"
            rows_html += f"<tr><td style='text-align:center'>{item['label']}</td><td style='text-align:center'>{fmt2(item['monthly'])}</td><td style='text-align:left'>{detail}</td></tr>"
        deposit_rows = [b for b in utility_plan["bills"] if b["deposit"] > 0]
        deposit_note = " ".join(f"{b['date']} 燃气扣款 {fmt2(b['hkd'])}，含押金 {fmt2(b['deposit'])}；费用净额 {fmt2(b['net'])}。" for b in deposit_rows)
        utility_note = (f"<div class='info-note'><b>固定生活费月度预算：</b>房租 {fmt2(cf['rent'])} + 水电煤网 {fmt2(cf['utility'])} = {fmt2(cf['fix'])} HKD/月。"
                        f"<table><thead><tr><th style='width:12%;text-align:center'>项目</th><th style='width:18%;text-align:center'>HKD/月</th><th style='width:70%'>来源与口径</th></tr></thead><tbody>{rows_html}</tbody></table>"
                        f"{deposit_note}<br>押金仅计入付款当月现金流，不计入月均生活成本或应急金。"
                        "Tab1 显示实际固定账单扣款，保留真实日期；房租及未接入 Visa 的网费按手动月额计入 Tab2。"
                        "水费有收费账单后需核对覆盖期；暂计 0 不代表永久免缴。</div>")


    ladder_rows = ""
    for item in freedom_ladder:
        status_color = "#2E7D32" if item["reached"] else "#B26A00"
        status_text = "已达成" if item["reached"] else f"约 {item['years_needed']} 年"
        ladder_rows += (f'<tr><td style="text-align:left"><span style="font-size:16px">{item["icon"]}</span> <b>{item["name"]}</b></td>'
                        f'<td style="text-align:left;color:#64748B">{LADDER_DEFS[item["name"]]}</td>'
                        f'<td>{item["cost_hkd"]:,.0f} HKD</td>'
                        f'<td>${item["target_usd"]:,.0f}</td>'
                        f'<td style="color:{status_color};font-weight:600">{status_text}</td></tr>')


    actual_disc = cf["actual_discretionary"]
    nonessential_label = " + ".join(config.NONESSENTIAL_CATS)
    mindless = cf["mindless_monthly"]

    thr = cf.get("spend_thresholds") or {
        "months": config.MIND_SPEND["months"], "window": [], "active_months": 0,
        "sample": 0, "monthly_avg": 0.0,
        "raw_free": cf["mindless_per_trip"], "raw_cooling": cf["mindless_cooling"],
        "free_hits": 0, "cooling_hits": 0, "month_hits": 0,
    }
    overspend = actual_disc > mindless
    disc_color = "#C75B5B" if overspend else "#7A9A3F"
    disc_text = (f"超支 {fmt(actual_disc - mindless)} HKD ⚠️" if overspend
                 else f"结余 {fmt(mindless - actual_disc)} HKD 转入可花现金 ✅")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wealth Showcase · Fictional Data</title>
<style>{CSS}</style></head>
<body><div class="container">

<div class="report-header">
  <div class="report-title">Wealth OS</div>
  {build_report_controls()}
  <div class="report-subtitle">Spending &amp; Transactions · Cash Flow &amp; FIRE · Options Trading · Equity Holdings ｜ 汇率 USD/HKD {usd_hkd}（{fx_time}）</div>
</div>

<div class="tab-bar" id="tabBar">
  <button class="tab-btn active" id="btn1">Tab 1 · Spending &amp; Transactions</button>
  <button class="tab-btn" id="btn2">Tab 2 · Cash Flow &amp; FIRE</button>
  <button class="tab-btn" id="btn3">Tab 3 · Options Trading</button>
  <button class="tab-btn" id="btn4">Tab 4 · Equity Holdings</button>
</div>

<!-- ============ TAB 1 消费模式 ============ -->
<div id="tab1">
  <div class="tab-intro">
  <div class="tab-data-note" id="tab1DataRange">消费统计范围：全部已导入月份</div>
  </div>
  <div class="src-note">
    <div class="src-item"><div class="s1">PayMe</div><div><b>基本为餐饮消费</b></div><div class="muted" style="font-size:11px">归类到「饮食」</div></div>
    <div class="src-item"><div class="s1">八达通</div><div><b>餐饮 + 交通</b></div><div class="muted" style="font-size:11px">充值按比例分摊到「饮食 / 交通」</div></div>
    <div class="src-item"><div class="s1">其他卡 / 转账</div><div><b>按商户描述自动归类</b></div><div class="muted" style="font-size:11px">9 品类规则</div></div>
  </div>

  <div class="metrics-bar">
    <div class="metric"><div class="metric-label">消费合计</div><div class="metric-value" id="mSpend">—</div><div class="metric-label" style="margin-top:2px" id="mSpendRange">HKD（全部月份）</div></div>
    <div class="metric"><div class="metric-label">固定支出月度预算</div><div class="metric-value">{fmt2(cf['fix'])}</div><div class="metric-label" style="margin-top:2px">HKD/月</div></div>
    <div class="metric"><div class="metric-label">消费笔数</div><div class="metric-value" id="mCount">—</div><div class="metric-label" style="margin-top:2px" id="mCountRange">笔（全部月份）</div></div>
    <div class="metric"><div class="metric-label">日均消费</div><div class="metric-value" id="mDaily">—</div><div class="metric-label" style="margin-top:2px">HKD/天</div></div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title" id="secTitle">品类消费（全部月份）</div>
    <div class="section-desc"><span class="tag tag-real">真实</span> 占比 + 金额（随上方月份筛选联动）</div></div>
    <div style="display:flex;gap:14px;flex-wrap:wrap">
      <div class="chart-card" style="flex:1 1 300px;min-width:0">
        <div class="chart-title">品类占比</div>
        <div class="chart-body" id="pieChart"></div>
      </div>
      <div class="chart-card" style="flex:1 1 300px;min-width:0">
        <div class="chart-title">各品类金额（从高到低）</div>
        <div class="chart-body" id="barsChart"></div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-header sticky-head" id="txnHead"><div class="section-title">消费与固定支出明细（可搜索）</div>
    <div class="section-desc">关键词搜描述/品类/来源；月份可多选，饼图/柱状图与顶部指标同步联动</div></div>
    <div class="chart-card" id="txnTableCard">
      <div class="toolbar sticky-bar" id="txnBar">
        <input class="search-box" id="searchInput" type="text" placeholder="搜索：如 八达通 / 饮食 / 星巴克…">
        <span class="month-range" id="monthRange">月份：全部</span>
        <span class="muted">固定账单不计入日常消费合计 ｜ 共 <b id="tblCount">0</b> ｜ 实际消费合计 <b id="tblTotal">0</b></span>
      </div>
      <table id="txnTable"><colgroup><col class="col-date"><col class="col-desc"><col class="col-cat"><col class="col-source"><col class="col-amount"><col class="col-nature"></colgroup><thead><tr><th><div class="col-filter" id="monthSelect"><button type="button" class="col-filter-btn" id="monthToggle"><span class="cf-label">日期</span><span class="caret">▾</span></button><div class="month-menu" id="monthMenu"></div></div></th><th>描述</th><th><div class="col-filter"><button type="button" class="col-filter-btn" id="btnCat">品类<span class="caret">▾</span></button><div class="col-filter-menu" id="menuCat"></div></div></th><th><div class="col-filter"><button type="button" class="col-filter-btn" id="btnSource">来源<span class="caret">▾</span></button><div class="col-filter-menu" id="menuSource"></div></div></th><th><div class="col-filter"><button type="button" class="col-filter-btn" id="btnAmount">金额<span class="caret">▾</span></button><div class="col-filter-menu" id="menuAmount"></div></div></th><th><div class="col-filter"><button type="button" class="col-filter-btn" id="btnNature">性质<span class="caret">▾</span></button><div class="col-filter-menu" id="menuNature"></div></div></th></tr></thead>
      <tbody id="txnBody"></tbody></table>
    </div>
  </div>
</div>

<!-- ============ TAB 2 滚雪球现金流 ============ -->
<div id="tab2" style="display:none">
  <div class="tab-intro">
  <div class="tab-data-note">收支计算月：{month_key} {partial_note} · 最新收支记录 {latest_date or "未提供"}</div>
  </div>
  <div class="usage-guide">
    <div class="ug-title">这三块怎么用：Tab2 只沿着一条主链看金额 ① → ② → ③</div>
    <div class="ug-step"><b>收入</b>：工资 − 定投 + 期权收入 = 可用于生活的钱（见上方指标）。</div>
    <div class="ug-step"><b>① 本月可自由花 = 月度可支配预算</b>：可用于生活的钱 − 房租 − 水电煤网月均 − 饮食/交通 = <b>本月可自由花</b>。</div>
    <div class="ug-step"><b>① 管每月节奏 · 实际结果</b>：本月可自由花 − 购物等非必要消费 = <b>月度预算结余</b>；这笔结余会留在现金账户。</div>
    <div class="ug-step" style="margin-top:6px;color:#64748B"><b>① 管每月节奏 → ② 当前可花现金 → ③ 大额支出判断：</b>当前可花现金管账户里已有多少钱；大额支出判断管下一笔计划是否会跌破应急金。</div>
  </div>
  <div class="metrics-bar">
    <div class="metric"><div class="metric-label">定投（固定）</div><div class="metric-value pos">${cf['invest_usd']:,.0f}</div><div class="metric-label" style="margin-top:2px">USD/月（≈{fmt(cf['invest_hkd'])} HKD）</div></div>
    <div class="metric"><div class="metric-label">工资剩余</div><div class="metric-value">{fmt(cf['salary_remaining'])}</div><div class="metric-label" style="margin-top:2px">HKD（可用于生活）</div></div>
    <div class="metric"><div class="metric-label">期权收入（平仓已实现）</div><div class="metric-value">{fmt(cf['opt_hkd'])}</div><div class="metric-label" style="margin-top:2px">HKD（{fmt(cf['opt_usd'])} USD）{("· " + opt_note) if opt_note else ""}</div></div>
    <div class="metric"><div class="metric-label">月度预算结余（{month_key}{month_suffix}）</div><div class="metric-value">{fmt(cf['month_surplus'])}</div><div class="metric-label" style="margin-top:2px">HKD</div></div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title">资金流转瀑布图（{month_key}{month_suffix} 口径）</div>
    <div class="section-desc"><span class="tag tag-real">合成工资</span> <span class="tag tag-tmp">期权按月匹配</span></div></div>
    <div class="chart-card">{wf2_svg}
      <div class="info-note"><b>这张图只看本月现金实际流动：</b>工资剩余 + 期权收入 − 定投以外的实际固定支出 − 实际消费 = 扣款口径结余。月度预算主链使用经常性固定支出月均 <b>{fmt2(cf["fix"])}</b> HKD；实际扣款为 <b>{fmt2(cf.get("cash_fix", cf["fix"]))}</b> HKD，账单集中扣款或一次性押金会造成差异。</div>
      <div class="info-note"><b>读图顺序：</b>先看收入总额，再沿着定投 → 固定支出 → 实际消费向下走，最后一格就是本月实际结余；这张图的结余会进入下面的现金存量。绿色为增加，金色为扣减，蓝色为结余。汇率：{usd_hkd}（{fx_time} 演示固定汇率）。</div>
      <div style="background:#F4F8EF;border-radius:6px;padding:10px 14px;margin-top:8px;font-size:13px">
        <b style="color:#2E7D32">口径：</b>定投固定 <b>${cf['invest_usd']:,.0f} USD/月</b>（≈{fmt(cf['invest_hkd'])} HKD）。瀑布图展示实际扣款；下面的「本月可自由花」和「月度预算结余」展示经常性月均预算，两者只因账单发生时间不同而不同。
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title">① 月度可支配预算（{month_key}{month_suffix} 口径）</div>
    <div class="section-desc">月度预算口径：工资剩余 + 期权收入 − 房租 − 必要消费（含水电煤网月均）= 本月可自由花的预算上限</div></div>
    <div class="chart-card">
      {utility_note}
      <div class="kpis">
        <div class="kpi"><div class="k1">月度可支配预算（本月可自由花）</div><div class="k2" style="color:#7A9A3F">{fmt(mindless)} <span style="font-size:12px;color:#6B7280">HKD/月</span></div></div>
        <div class="kpi"><div class="k1">本月实际非必要消费</div><div class="k2" style="color:{disc_color}">{fmt(actual_disc)} <span style="font-size:12px;color:#6B7280">HKD</span></div></div>
        <div class="kpi"><div class="k1">单笔免审</div><div class="k2">≤ {fmt(cf['mindless_per_trip'])} <span style="font-size:12px;color:#6B7280">HKD</span></div></div>
        <div class="kpi"><div class="k1">冷静期阈值</div><div class="k2" style="color:#C75B5B">&gt; {fmt(cf['mindless_cooling'])} <span style="font-size:12px;color:#6B7280">HKD</span></div></div>
      </div>
      <div style="margin:10px 0;line-height:2">
<b>第1步</b>：工资 {fmt(cf['salary'])} − 定投 {fmt(cf['invest_hkd'])}（${cf['invest_usd']:,.0f}）= 工资剩余 <b>{fmt(cf['salary_remaining'])} HKD</b><br>
<b>第2步</b>：可支配 = 工资剩余 {fmt(cf['salary_remaining'])} + 期权 {fmt(cf['opt_hkd'])} − 房租 {fmt(cf['rent'])} − 必要消费（饮食 {fmt(cf['food_total'])} + 交通 {fmt(cf['transport'])} + 水电煤网月均 {fmt2(cf['utility'])} = {fmt(cf['essential_base'])}）= <b>{fmt(mindless)} HKD</b><br>
<b>第3步</b>：本月实际非必要消费按品类加总：{nonessential_label} = <b>{fmt(actual_disc)} HKD</b>（固定账单单列，不计入日常消费合计）<br>
<b>第4步</b>：可支配 {fmt(mindless)} − 非必要消费 {fmt(actual_disc)} = <b style="color:{disc_color}">{disc_text}</b>
      </div>
      <div class="info-note"><b>非必要消费口径：</b>当前按 {nonessential_label} 直接加总；如果以后某个类别改为必要消费，只需调整 <code>config.NONESSENTIAL_CATS</code>。固定支出不属于这里的非必要消费。<br></div>
      <details class="info-note"><summary style="cursor:pointer;font-weight:600">展开查看口径和算法</summary><div style="margin-top:6px"><b>金额关系：</b>本月可自由花 {fmt(mindless)} 是扣掉必要开销后的月度额度；月度预算结余 {fmt(cf['month_surplus'])} 是再扣除本月实际日常消费后的结果。固定账单实际扣款与月均预算可能不同，实际扣款结余见上面的瀑布图。</div></details>
      <details class="info-note"><summary style="cursor:pointer;font-weight:600">展开查看消费阈值算法与触发率</summary><div style="margin-top:6px"><b>上面两个阈值是怎么算的（按你自己的消费习惯，不随当月收入变）：</b><br>
      单笔免审 <b>{fmt(cf['mindless_per_trip'])}</b> = 最近 {thr['months']} 个月「单笔消费」的 {config.MIND_SPEND['free_pct']*100:.0f} 分位
      （原始 {fmt(thr['raw_free'])}，限幅 {fmt(config.MIND_SPEND['free_floor'])}~{fmt(config.MIND_SPEND['free_cap'])}）
      —— 含义：约 {config.MIND_SPEND['free_pct']*100:.0f}% 的日常笔数不用想，剩下的才需要判断；<br>
      冷静期阈值 <b>{fmt(cf['mindless_cooling'])}</b> = 最近 {thr['months']} 个月「月均消费 {fmt(thr['monthly_avg'])}」× {config.MIND_SPEND['cooling_pct']*100:.0f}%
      （原始 {fmt(thr['raw_cooling'])}，限幅 {fmt(config.MIND_SPEND['cooling_floor'])}~{fmt(config.MIND_SPEND['cooling_cap'])}）
      —— 含义：这一笔动了这个月消费的一大块，先放 1~2 天，或者拿去下面的「大额支出判断」算一次。<br>
      <b>可检验的触发率（窗口内 {thr['sample']} 笔）：</b>免审放行 {thr['free_hits']} 笔（{thr['free_hits'] / thr['sample'] * 100 if thr['sample'] else 0:.0f}%）；
      达到冷静期 {thr['cooling_hits']} 笔；其中落在计算月（{month_key}）的 {thr['month_hits']} 笔——这个数就是下面「大额支出判断」里"本月已发生的大额消费"的来源。
      系数都在 <code>config.MIND_SPEND</code>（窗口月数、分位、比例、上下限）。</div></details>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title">② 当前可花现金（存量口径）</div>
    <div class="section-desc">真实现金 − 应急金 = 可花现金 ｜ 支出只从现金/短债出，不动股票</div></div>
    <div class="chart-card">
      {cash_card_html}
    </div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title">③ 大额支出判断</div>
    <div class="section-desc">这笔钱从现金/短债出，不动股票：看花完还剩多少、会不会动到应急金</div></div>
    <div class="chart-card">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
        <span style="font-size:13px;font-weight:600">计划支出：</span>
        <input id="bigSpend" type="number" placeholder="如 2800" value="2800" style="width:130px;padding:8px 12px;border:1px solid #CBD5E1;border-radius:6px;font-size:14px">
        <span style="font-size:13px;color:#64748B">HKD ×</span>
        <input id="bsTimes" type="number" min="1" step="1" value="1" style="width:64px;padding:8px 10px;border:1px solid #CBD5E1;border-radius:6px;font-size:14px">
        <span style="font-size:13px;color:#64748B">次</span>
        <select id="bsInterval" style="padding:8px 10px;border:1px solid #CBD5E1;border-radius:6px;font-size:13px">
          <option value="same">同一月内</option>
          <option value="month">每月一次</option>
          <option value="year">每年一次</option>
        </select>
        <span style="font-size:12px;color:#94A3B8">（从现金 / 短债出，不动股票）</span>
      </div>
      <div id="bigSpendResult" style="background:#F8FAFC;border-radius:8px;padding:14px">
        <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:10px">
          <div><div style="font-size:11px;color:#94A3B8">计划合计</div><div id="bsTotal" style="font-size:18px;font-weight:700">HK$2,800</div></div>
          <div><div style="font-size:11px;color:#94A3B8">等值 USD</div><div id="bsUsd" style="font-size:18px;font-weight:700">$359</div></div>
          <div><div style="font-size:11px;color:#94A3B8">摊到每月</div><div id="bsPerMonth" style="font-size:18px;font-weight:700">—</div></div>
          <div><div style="font-size:11px;color:#94A3B8">现金最低点 <span id="bsMinMonth" style="color:#CBD5E1"></span></div><div id="bsMin" style="font-size:18px;font-weight:700">—</div></div>
          <div><div style="font-size:11px;color:#94A3B8">最低点能撑</div><div id="bsMonthsLeft" style="font-size:18px;font-weight:700">—</div></div>
          <div><div style="font-size:11px;color:#94A3B8">判断（按合计）</div><div id="bsVerdict" style="font-size:18px;font-weight:700;color:#2E7D32">✅ 几乎无影响</div></div>
        </div>
        <div id="bsAdvice" style="font-size:12.5px;color:#64748B;line-height:1.7">占净资产不到 1%，相当于不到 1 个月定投。对 10 年滚雪球和 FIRE 达成年限几乎无影响，随时赎回都科学。</div>
        <div id="bsOnce" style="font-size:12px;color:#64748B;margin-top:6px"></div>
        <div id="bsHistory" style="font-size:12px;color:#64748B;margin-top:6px"></div>
        <details style="margin-top:10px">
          <summary style="cursor:pointer;font-size:12px;color:#64748B">如果现金不够、只能卖股票（次要参考）</summary>
          <div style="display:flex;gap:20px;flex-wrap:wrap;margin:8px 0 4px">
            <div><div style="font-size:11px;color:#94A3B8">占净资产</div><div id="bsPct" style="font-size:16px;font-weight:700">—</div></div>
            <div><div style="font-size:11px;color:#94A3B8">相当于定投</div><div id="bsMonths" style="font-size:16px;font-weight:700">—</div></div>
            <div><div style="font-size:11px;color:#94A3B8">FIRE 推迟</div><div id="bsDelay" style="font-size:16px;font-weight:700">—</div></div>
          </div>
          <div id="bsSellAdvice" style="font-size:12px;color:#64748B;line-height:1.7"></div>
        </details>
      </div>
      <div class="info-note" style="margin-top:12px"><b>判断标准（现金视角）：</b><br>
① 模拟期内<b>现金最低点 ≥ 应急金</b> = ✅ <b>不用卖股票</b>（花完仍在安全垫之上）<br>
② 现金最低点在 0 与应急金之间 = ⚠️ <b>会动到应急金</b>（花完低于 6 个月必要支出）<br>
③ 现金最低点 &lt; 0 = ❌ <b>现金不够，要么分期、要么卖股票</b><br>
<b>三种间隔的区别（现在真的不一样了）：</b>「同一月内 × N 次」= 一次性拿出 N×单次；
「每月一次 × N」= 分摊到 N 个月，期间每个月还有你的<b>月结余 {fmt(cf['month_surplus'])} HKD</b>补进来，
所以只要单次 ≤ 月结余就不会动到应急金；「每年一次 × N」= 每 12 个月一次，中间累积的结余更多，压力最小。
判断口径统一为「模拟期内的<b>现金最低点</b>」和应急金比较。<br>
<b>判定对象是「累计金额」</b>（单次金额 × 次数），不是单次——否则"每次 5,000、每月一次"这类重复消费每次都会被判成无影响；同时会列出"本月已发生的大额消费"（单笔 ≥ 单笔冷静期额度，从流水自动筛选），避免已经花掉的那几次被忽略。<br>
<b>口径：</b>支出只从现金/短债出、不卖股票，所以主判断用「可花现金 = 真实现金 − 应急金」；「卖股票」那一栏只在③的情况下才需要看，它用的是原来的口径（按选定年化逐月模拟 FIRE 推迟）。</div>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title">滚雪球预测（10 年 · 单位：USD）</div>
    <div class="section-desc"><span class="tag tag-real">P0 真实</span> ${fmt(p0_usd)}（IBKR 净值）· FIRE 目标 ${fmt(fire_target_usd)}（SWR {config.SWR*100:.1f}% 推导）· 定投 {', '.join(l for l, _ in config.INVEST_LEVELS)}</div></div>
    <div class="chart-card">
      <div class="rate-toolbar twr-mode" id="rateToolbar">
        <div class="rate-source"><label for="rateSel">收益率来源：</label>
        <select id="rateSel">
          {rate_options}
        </select>
        </div>
        <div class="rate-input" id="twrControls"><label for="twrInput">TWR 模拟年化：</label>
        <input id="twrInput" type="number" step="0.1" min="-99.9" value="{rates['twr']*100:.1f}">
        <span>%</span></div>
        <div class="rate-meta"><span id="rateLabel"></span>
        <span id="twrStatus">{"账户历史 TWR · 自动填入" if twr_is_real else "模拟参考值 · 暂无账户 TWR"}</span></div>
      </div>
      <div class="chart-title">三档定投 · 到 FIRE 的路径（USD）
        <span style="font-weight:400;font-size:11.5px;color:#94A3B8">纵轴到 FIRE 目标（{fmt(fire_target_usd*1.15)} 封顶）；曲线画到达到 FIRE 的那一刻为止（终点圆点 = 达标），10 年终点见下表</span>
      </div>
      <div id="snowChart"></div>
    </div>
    <div class="chart-card">
      <table>
        <thead><tr><th>定投档</th><th>10 年末资产</th><th>FIRE（${fmt(fire_target_usd)}）达成年</th></tr></thead>
        <tbody id="snowBody"></tbody>
      </table>
    </div>
    <div class="info-note"><b>口径：</b><br>
① P0 = ${fmt(p0_usd)} USD（IBKR 当前净值，汇率按运行日最新 USD/HKD 换算）<br>
② 月收益 r = (1+年化)^(1/12)−1，月末投入<br>
    ③ 期权收入用<b>平仓已实现</b>口径（IBKR 的 fifoPnlRealized 按平仓日归集：几个月前卖出、本月才买回/到期的仓位记在本月；{opt_note or f"未启用 Flex 时暂定 ${fmt(config.OPT_TMP_USD)} USD/月"}）<br>
④ 收益率来源三选一：<b>IBKR TWR</b>（账户时间加权收益率，自动含现金拖累，最贴近你的真实配置；{"已接入 IBKR Flex 自动获取" if twr_is_real else "待接入 IBKR Flex 自动获取，现为占位值"}）/ 纳斯达克 100 历史平均 14% / 标普 500 历史平均 10%</div>
  </div>

  <div class="section">
    <div class="section-header"><div class="section-title">财富自由阶梯</div>
    <div class="section-desc">每级目标 = 月成本 × 12 ÷ {config.SWR*100:.1f}%（SWR，可配置）· 当前净资产 ${fmt(p0_usd)} USD · 定投 ${fmt(config.FIXED_INVEST_USD)}/月</div></div>
    <div class="chart-card">
      {ladder_svg}
      <table class="ladder-table" style="margin-top:14px;font-size:12px">
        <thead><tr><th>自由等级</th><th>定义</th><th>月成本</th><th>目标净资产</th><th>状态</th></tr></thead>
        <tbody>
          {ladder_rows}
        </tbody>
      </table>
      <div class="info-note" style="margin-top:12px"><b>动态计算：</b>每级月成本基于香港真实价格（房租参考港岛/尖沙咀优质地段、旅行参考年预算18万等），目标净资产 = 月成本×12÷{config.SWR*100:.1f}%（与滚雪球、大额支出的 FIRE 目标同一口径）；<b>柱内填充 = 当前净资产 ÷ 该级目标（完成度，柱顶标注百分比）</b>，柱高仍按等级递升形成阶梯；已达成 = 当前净资产 ≥ 目标，未达成按定投 ${fmt(config.FIXED_INVEST_USD)}/月、年化 {rates[config.DEFAULT_RATE]*100:.1f}%（默认 {rate_labels[config.DEFAULT_RATE].split(' · ')[0]}）测算达成年限。<b>配色与 Tab1 一致</b>（填充色轮转 Tab1 品类色）。</div>
    </div>
  </div>
</div>

<!-- ============ TAB 3 期权 ============ -->
<div id="tab3" style="display:none">
  <div class="tab-intro">
  <div class="tab-data-note">{opt_monthly_desc}</div>
  <div class="workspace-entry" id="optionWorkspaceEntry"><a id="openOptionWorkspace" href="workspace.html" target="_blank" rel="noopener">打开期权工作台 →</a><span id="optionWorkspaceStatus" role="status" aria-live="polite">只读演示 · 候选、持仓及检查项均为虚构数据。</span></div>
  </div>
  <div class="section">
    <div class="section-header"><div class="section-title">期权收入 · 按月（两种口径）</div>
    <div class="section-desc">单位 USD ｜ 已扣佣金与交易费</div></div>
    <div class="chart-card">
      {option_summary_html}
      {opt_monthly_html}
    </div>
  </div>
  {option_positions_html}
  {option_openings_html}
</div>

<!-- ============ TAB 4 正股 ============ -->
<div id="tab4" style="display:none">
  <div class="tab-intro">
  <div class="tab-data-note">历史账户收益截至：{(performance_periods.get("ALL") or {}).get("end", str((alloc_kpi or {}).get("last", "未提供")))}</div>
  <div class="tab-data-note">{escape(stock_data_desc)}</div>
  </div>
  {returns_html}
  {drawdown_html}
  <div class="section">
    <div class="section-header"><div class="section-title">仓位结构 · 现金 / 股票 / 期权占比</div>
    <div class="section-desc">{alloc_desc}</div></div>
    <div class="chart-card">
      {alloc_kpi_html}
      <div id="allocChart">{alloc_svg}</div>
      {alloc_note_html}
    </div>
  </div>
  {stock_analysis_html}
  {extra_html}
</div>

<div class="footnote">
  <p><sup>1</sup> 绿色 = 真实数据（银行流水解析）；红色 = 暂定值（期权收入，IBKR Flex 未启用时按月匹配暂定 ${fmt(config.OPT_TMP_USD)} USD/月）。</p>
  <p><sup>2</sup> 汇率按运行日最新 USD/HKD 换算；年化收益率三选一（IBKR TWR 实际年化 / 纳斯达克历史平均 14% / 标普 500 历史平均 10%），均为历史参考，非收益承诺。</p>
  <p><sup>3</sup> Tab2 月度口径：可支配、月度预算结余使用固定账单月均；瀑布图使用实际固定支出，按 Tab2 标注的收支月份计算；可花现金取账户现金减未偿还信用卡欠款及应急金，欠款未知时只展示上限；品类消费随 Tab1 月份筛选联动（<span id="fnRange">全部月份</span>）。</p>
  <p><sup>4</sup> 图表为纯 SVG/CSS、搜索与切换为原生 JS，零外部依赖，本地打开即用。</p>
</div>

</div>
<script>
{build_report_controls_js()}
{build_report_service_js()}
{build_workspace_entry_js()}
{build_option_offset_links_js()}
{js}
</script>
</body></html>"""


    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent,
                                         suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
            f.write(html)
        os.replace(temporary, out)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(out), len(html)
