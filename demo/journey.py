"""以真实提交支持的功能演进呈现项目，避免把提交数量等同代码质量。"""
import json
from pathlib import Path
from html import escape
from .pages import shell

MILESTONES = [
    dict(commit='77c0105', area='分析与报告', title='从账单到可交互的消费报告',
         change='建立银行流水解析、现金流计算和报告生成流程，并加入核心计算与解析测试。',
         outcome='把输入、计算和图表展示分开，形成可以持续扩展的模块结构。', tags=['数据解析', '模块职责', '回归测试']),
    dict(commit='a76e3af', area='分析与报告', title='同时解释收益与资金投入的影响',
         change='报告加入 MWR，配合 TWR 展示不同资金投入时点对收益率的影响。',
         outcome='区间收益、年化收益和两种收益口径分别呈现，减少数字看似相同却含义不同的问题。', tags=['TWR / MWR', '统计口径']),
    dict(commit='ac706c1', area='质量与可靠性', title='让当前快照与历史数据各司其职',
         change='源项目接入 Gateway 只读快照，并保留 Flex 历史数据与失败回退。',
         outcome='当前资产状态与历史收益使用适合的数据源；公开展示版以合成快照替代连接。', tags=['数据回退', '来源标记']),
    dict(commit='efc834a', area='交易工作台', title='把期权状态集中到独立工作台',
         change='源项目增加期权扫描和本地工作台服务，集中展示候选、状态与检查结果。',
         outcome='报告与工作台各自承担统计回顾和运行状态展示；此处保留原工作台界面。', tags=['状态展示', '独立入口']),
    dict(commit='2c02220', area='质量与可靠性', title='先核对净仓，再展示组合',
         change='期权持仓按策略组合展示，增加原始结构还原与净仓一致性检查。',
         outcome='面对多腿与相互抵销的持仓，结构不完整时明确待核验，避免猜出一个看似完整的策略。', tags=['净仓核对', '多腿结构']),
    dict(commit='b1502a9', area='交易工作台', title='把订单状态与现金结算说清楚',
         change='调整订单展示，按交易日组织记录，并完善现金流和费用的展示。',
         outcome='成交、费用、现金净收付款与策略盈亏分开说明，未完成核对时保留待确认状态。', tags=['交易日', '结算展示'])]

STYLES = '''.journey-hero{padding:44px 0 30px;border-bottom:1px solid #dbe3ed}.journey-hero h1{font-size:36px;letter-spacing:-1px}.journey-hero p{max-width:660px;margin:14px 0}.journey-meta{display:flex;gap:22px;flex-wrap:wrap;font-size:12px;color:#61718a;margin-top:24px}.journey-layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:60px;margin-top:35px}.journey-nav{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 30px}.journey-nav button{font-size:12px;border:0;background:#e8edf3;color:#52657c;padding:7px 11px}.journey-nav button[aria-pressed=true]{background:#203d5b;color:white}.milestone{position:relative;padding:0 0 34px 32px;margin-left:6px;border-left:1px solid #d3dfe9}.milestone:before{content:'';position:absolute;left:-5px;top:5px;width:9px;height:9px;border-radius:50%;background:#46779c;box-shadow:0 0 0 5px #f3f6fa}.milestone-date{font:12px/1.4 ui-monospace,monospace;color:#6a7c91}.milestone h2{margin:9px 0;font-size:20px;line-height:1.5}.milestone p{font-size:14px;margin:7px 0;color:#4e6279}.milestone .outcome{color:#223f59}.milestone-tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.milestone-tags span{font-size:11px;color:#536c85;background:#e9eff5;padding:2px 7px;border-radius:3px}.milestone-source{font:11px ui-monospace,monospace;color:#8190a3;margin-top:10px}.journey-aside{border-top:2px solid #2c4865;padding-top:15px}.journey-aside h2{font-size:14px;margin:0 0 14px}.journey-aside h3{font-size:13px;margin:22px 0 5px}.journey-aside p{font-size:12px;line-height:1.9;margin:0}.journal-details{background:#fff;border:1px solid #dce4ee;border-radius:10px;padding:18px 22px;margin-top:18px}.journal-details>summary{font-size:13px;font-weight:600;color:#38536f}.journal-details .scroll{max-height:420px;margin-top:12px}.journal-details th{position:sticky;top:0;background:white}.journal-details td{font-size:12px}.record-note{font-size:12px;max-width:820px}.journal-details select{font-size:12px;padding:5px 8px}@media(max-width:800px){.journey-layout{grid-template-columns:1fr;gap:20px}.journey-hero{padding:28px 0}.journey-hero h1{font-size:29px}.journey-aside{margin-bottom:20px}}'''


def write_timeline(output, source):
    """输出六个有源提交依据的演进节点，默认收起完整元数据。"""
    metadata = json.loads(source.read_text(encoding='utf-8'))
    commits = metadata['commits']
    milestones = []
    for item in MILESTONES:
        record = next(row for row in commits if row['source_commit'].startswith(item['commit']))
        milestones.append({**item, 'date': record['author_date'], 'hash': record['source_commit']})
    cards = ''.join(
        '<article class="milestone" data-area="'+escape(item['area'])+'">'
        '<div class="milestone-date">'+item['date']+' / '+escape(item['area'])+'</div>'
        '<h2>'+escape(item['title'])+'</h2><p>'+escape(item['change'])+'</p>'
        '<p class="outcome">'+escape(item['outcome'])+'</p>'
        '<div class="milestone-tags">'+''.join('<span>'+escape(tag)+'</span>' for tag in item['tags'])+'</div>'
        '<div class="milestone-source">源提交 '+item['hash']+'</div></article>' for item in milestones)
    body = f'''<style>{STYLES}</style><header><a href="index.html">← 返回产品演示</a><span class="muted">WEALTH / PROJECT NOTES</span></header>
<section class="journey-hero"><span class="eyebrow">项目演进</span><h1>从消费报告，到期权工作台。</h1><p>围绕真实使用中的问题，逐步完善数据口径、交互体验和异常状态。下面选取六个有提交依据的功能节点，说明每一步解决了什么。</p><div class="journey-meta"><span>{commits[0]['author_date']} — {commits[-1]['author_date']}</span><span>6 个演进节点</span><span>{metadata['count']} 条源提交记录</span></div></section>
<div class="journey-layout"><section><nav class="journey-nav" aria-label="功能节点筛选"><button aria-pressed="true" data-area-filter="all">全部节点</button><button aria-pressed="false" data-area-filter="分析与报告">分析与报告</button><button aria-pressed="false" data-area-filter="交易工作台">交易工作台</button><button aria-pressed="false" data-area-filter="质量与可靠性">质量与可靠性</button></nav>{cards}</section>
<aside class="journey-aside"><h2>实现取舍</h2><h3>计算与展示分层</h3><p>业务计算由 Python 完成，页面接收计算结果；参数从配置注入，减少同一口径维护多份实现的机会。</p><h3>离线优先</h3><p>图表和交互内嵌在 HTML 中，下载后即可查看，适合本地使用和作品评估。</p><h3>异常也是界面的一部分</h3><p>行情过期、净仓差异和未确认成交都有明确状态。工作台演示可以切换这些场景。</p><h3>可运行的证据</h3><p><a href="workspace.html">原框架期权工作台 →</a><br><a href="index.html">四页财务报告 →</a></p></aside></div>
<details class="journal-details" id="source-records"><summary>查看完整源提交记录 · {metadata['count']} 条</summary><p class="record-note">以下为私有源项目导出的日期、短哈希与修改范围；完整差异未公开。展示版使用独立 Git 历史记录后续改进。</p><label for="area">修改范围 </label><select id="area"><option value="all">全部</option><option>Report &amp; analytics</option><option>Options system</option><option>Regression tests</option><option>Application tooling</option><option>Documentation</option><option>Project maintenance</option></select><p id="count" class="muted" role="status"></p><div class="scroll"><table><thead><tr><th>序号</th><th>源提交</th><th>日期</th><th>修改范围</th></tr></thead><tbody id="history"></tbody></table></div></details>
<details class="journal-details"><summary>展示范围与数据来源</summary><p class="record-note">功能节点由实际源提交整理，覆盖源项目曾实现的能力。公开版保留通用计算和页面，以合成数据替代个人数据及真实连接。工作台沿用原模板和显示函数，执行入口已隔离；本页面不能证明真实下单或券商执行验收。源项目采用 AI 辅助开发。</p></details>'''
    payload = json.dumps(commits, ensure_ascii=False).replace('<', '\\u003c')
    script = 'const commits=' + payload + ''';
function renderRecords(){const area=document.getElementById('area').value;const rows=commits.filter(row=>area==='all'||row.areas.includes(area));document.getElementById('count').textContent=rows.length+' / '+commits.length+' 条';document.getElementById('history').replaceChildren(...rows.map(row=>{const tr=document.createElement('tr');[row.sequence,row.source_commit,row.author_date,row.areas.join(' · ')].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td)});return tr}));}
document.getElementById('area').addEventListener('change',renderRecords);renderRecords();
document.querySelectorAll('[data-area-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-area-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));document.querySelectorAll('.milestone').forEach(item=>{item.hidden=button.dataset.areaFilter!=='all'&&item.dataset.area!==button.dataset.areaFilter;});}));'''
    (output / 'timeline.html').write_text(shell('Wealth · 项目演进', body, script), encoding='utf-8')
