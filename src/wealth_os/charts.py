
"""图表层：纯 SVG 生成，不做业务计算。改外观/颜色/字体只动这个文件。
viewBox 宽度：瀑布/阶梯统一 680（确保同容器内字体视觉一致）。
消费饼图/柱状图已随月份筛选改为 report.js 动态渲染（svgDonut/svgBars，viewBox 420），
滚雪球曲线亦由 report.js 动态渲染（收益率切换 + crosshair 交互），charts 不提供静态版本。"""
import math
import json

from .core import fmt
from . import config


def svg_account_returns(series):
    """绘制预计算的日期/TWR%/MWR%曲线，提供用于悬停的日期与坐标。"""
    if len(series) < 2:
        return '<div class="info-note">暂无可用收益曲线。</div>'
    from datetime import date
    from html import escape
    width, height, left, right, top, bottom = 680, 280, 56, 20, 20, 38
    values = [value for row in series for value in row[1:] if value is not None]
    low, high = min(0, min(values)), max(0, max(values))
    pad = max((high - low) * 0.12, 1.0)
    low, high = low - pad, high + pad
    first = date.fromisoformat(series[0][0])
    span = max((date.fromisoformat(series[-1][0]) - first).days, 1)
    plot_w, plot_h = width - left - right, height - top - bottom
    coords = []
    for day, twr, mwr in series:
        x = left + (date.fromisoformat(day) - first).days / span * plot_w
        ys = [top + (high - value) / (high - low) * plot_h if value is not None else None
              for value in (twr, mwr)]
        coords.append([day, twr, mwr, x, *ys])
    output = []
    for i in range(5):
        value = low + (high - low) * i / 4
        y = top + plot_h * (1 - i / 4)
        output.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#E2E8F0"/><text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="#64748B">{value:+.0f}%</text>')
    zero_y = top + high / (high - low) * plot_h
    output.append(f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="#94A3B8" stroke-dasharray="4 4"/>')
    for value_index, color in ((4, "#2476B5"), (5, "#297D68")):
        segments, points = [], []
        for row in coords:
            if row[value_index] is None:
                if points:
                    segments.append(points)
                    points = []
            else:
                points.append(f'{row[3]:.2f},{row[value_index]:.2f}')
        if points:
            segments.append(points)
        method = "twr" if value_index == 4 else "mwr"
        output.extend(f'<polyline data-return-series="{method}" points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="2.3" stroke-linejoin="round"/>' for points in segments)
    for index, anchor in ((0, "start"), (len(coords) - 1, "end")):
        output.append(f'<text x="{coords[index][3]:.1f}" y="{height-10}" text-anchor="{anchor}" font-size="11" fill="#64748B">{coords[index][0]}</text>')
    data = escape(json.dumps(coords), quote=True)
    return (f'<svg class="return-chart" viewBox="0 0 {width} {height}" role="img" aria-label="TWR 与 MWR 区间累计收益曲线" data-series="{data}">'
            + ''.join(output)
            + f'<line class="return-crosshair" x1="0" y1="{top}" x2="0" y2="{height-bottom}" stroke="#64748B" stroke-dasharray="4 3" opacity="0"/>'
            + '</svg>')


def svg_equity_drawdown(series):
    """把 core 输出的 (日期, TWR指数, 回撤%) 画成面积图，并提供边界内十字线提示。"""
    if len(series) < 2:
        return ''
    width, height = 680, 200
    left, right, top, bottom = 55, 20, 20, 40
    plot_width, plot_height = width - left - right, height - top - bottom
    low = min(-5, min(row[2] for row in series) * 1.15)
    points = [(left + i / (len(series) - 1) * plot_width,
               top + row[2] / low * plot_height) for i, row in enumerate(series)]
    line = ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)
    grid = ''.join(f'<line x1="{left}" y1="{top + i / 2 * plot_height}" x2="{width-right}" y2="{top + i / 2 * plot_height}" stroke="#E2E8F0"/><text x="{left-8}" y="{top + i / 2 * plot_height+4}" text-anchor="end" font-size="11" fill="#64748B">{low*i/2:.0f}%</text>' for i in range(3))
    data = json.dumps([{"day": row[0], "level": row[1], "dd": row[2]} for row in series], ensure_ascii=False).replace('&', '&amp;').replace('"', '&quot;')
    return f"""<svg id="equityDrawdownChart" viewBox="0 0 {width} {height}" role="img" aria-label="账户 TWR 历史回撤曲线" style="width:100%;display:block">{grid}<polygon points="{left},{top} {line} {width-right},{top}" fill="#C75B5B" opacity="0.12"/><polyline points="{line}" fill="none" stroke="#C75B5B" stroke-width="2"/><text x="{left}" y="{height-12}" fill="#64748B" font-size="11">{series[0][0]}</text><text x="{width-right}" y="{height-12}" text-anchor="end" fill="#64748B" font-size="11">{series[-1][0]}</text><line id="drawdownCrosshair" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#334155" stroke-dasharray="4 3" opacity="0"/><circle id="drawdownDot" cx="{left}" cy="{top}" r="4" fill="#C75B5B" opacity="0"/><g id="drawdownTip" opacity="0" pointer-events="none"><rect x="0" y="0" width="230" height="46" rx="5" fill="#0F172A" opacity=".96"/><text id="drawdownTipText" x="10" y="19" font-size="11" fill="white"></text><text id="drawdownTipText2" x="10" y="36" font-size="11" fill="#CBD5E1"></text></g><rect id="drawdownHit" x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="transparent" data-series="{data}" style="cursor:crosshair"/></svg><script>(function(){{const s=document.getElementById('equityDrawdownChart'), hit=document.getElementById('drawdownHit'), line=document.getElementById('drawdownCrosshair'), dot=document.getElementById('drawdownDot'), tip=document.getElementById('drawdownTip'), t1=document.getElementById('drawdownTipText'), t2=document.getElementById('drawdownTipText2'), rows=JSON.parse(hit.dataset.series), L={left}, T={top}, W={plot_width}, H={plot_height}, VW={width}, VH={height}; function move(e){{const p=s.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(s.getScreenCTM().inverse());const i=Math.max(0,Math.min(rows.length-1,Math.round((q.x-L)/W*(rows.length-1))));const r=rows[i];const x=L+i/(rows.length-1)*W;const y=T+r.dd/{low}*H;line.setAttribute('x1',x);line.setAttribute('x2',x);dot.setAttribute('cx',x);dot.setAttribute('cy',y);const tipW=230,tipH=46;let tx=x+12;if(tx+tipW>VW-{right})tx=x-tipW-12;tx=Math.max(L,Math.min(VW-{right}-tipW,tx));let ty=y<VH/2?y+12:y-tipH-12;ty=Math.max(T,Math.min(VH-{bottom}-tipH,ty));tip.setAttribute('transform','translate('+tx+','+ty+')');line.style.opacity=1;dot.style.opacity=1;tip.style.opacity=1;t1.textContent=r.day+'  ·  回撤 '+r.dd.toFixed(1)+'%';t2.textContent='TWR指数 '+r.level.toFixed(1)+'（起点=100）';}}function leave(){{line.style.opacity=0;dot.style.opacity=0;tip.style.opacity=0;}}hit.addEventListener('mousemove',move);hit.addEventListener('mouseleave',leave);}})();</script>"""

INDUSTRY_COLORS = ["#4A90D9", "#7A9A3F", "#C9A227", "#9EACEA", "#C75B5B", "#8BC8EA", "#94D8C3"]


def svg_waterfall(steps, width=680, height=340, pad_l=70, pad_r=30, pad_t=44, pad_b=56):
    """steps: [{label, value, type: start|pos|neg|end}]。viewBox 宽 680。"""
    cum = 0
    bars = []
    for s in steps:
        v = s["value"]
        if s["type"] == "start":
            bars.append({"label": s["label"], "y0": 0, "y1": v, "type": "total", "conn_from": v, "val": v})
            cum = v
        elif s["type"] == "pos":
            bars.append({"label": s["label"], "y0": cum, "y1": cum + v, "type": "increase", "conn_from": cum + v, "val": v})
            cum += v
        elif s["type"] == "neg":
            bars.append({"label": s["label"], "y0": cum + v, "y1": cum, "type": "decrease", "conn_from": cum + v, "val": -v})
            cum += v
        elif s["type"] == "end":
            bars.append({"label": s["label"], "y0": 0, "y1": cum, "type": "total", "conn_from": cum, "val": cum})
    vmax = max(max(b["y0"], b["y1"]) for b in bars) * 1.1
    vmin = 0
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    step_w = plot_w / len(bars)
    bar_w = step_w * 0.5
    def Y(v): return pad_t + plot_h * (1 - (v - vmin) / (vmax - vmin))
    def X(i): return pad_l + step_w * i + (step_w - bar_w) / 2


    COLORS = {
        "increase": config.PIE_COLORS["交通"],
        "decrease": config.PIE_COLORS["购物"],
        "total": config.PIE_COLORS["饮食"],
    }

    out = ""

    ticks = 6
    for t in range(ticks + 1):
        v = vmin + (vmax - vmin) * t / ticks
        gy = Y(v)
        out += f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width-pad_r}" y2="{gy:.1f}" stroke="#E2E8F0" stroke-width="1"/>'
        out += f'<text x="{pad_l-10}" y="{gy+4:.1f}" text-anchor="end" font-size="11" fill="#94A3B8">{fmt(v)}</text>'

    out += f'<line x1="{pad_l}" y1="{Y(0):.1f}" x2="{width-pad_r}" y2="{Y(0):.1f}" stroke="#CBD5E1" stroke-width="1.2"/>'


    legend_y = 16
    lx = pad_l
    for ltype, lname in [("increase", "增加"), ("decrease", "扣减"), ("total", "总计")]:
        out += f'<rect x="{lx}" y="{legend_y-9}" width="12" height="12" rx="2" fill="{COLORS[ltype]}"/>'
        out += f'<text x="{lx+18}" y="{legend_y+1}" font-size="12" fill="#475569">{lname}</text>'
        lx += 80

    for i, b in enumerate(bars):
        x = X(i)
        y_top = Y(b["y1"])
        y_bot = Y(b["y0"])
        bar_h = max(y_bot - y_top, 1)
        color = COLORS[b["type"]]

        out += f'<rect x="{x:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="2" fill="{color}"/>'

        prefix = "+" if b["type"] == "increase" else ""
        out += f'<text x="{x+bar_w/2:.1f}" y="{y_top-7:.1f}" text-anchor="middle" font-size="12" font-weight="700" fill="{color}">{prefix}{fmt(b["val"])}</text>'

        out += f'<text x="{x+bar_w/2:.1f}" y="{height-pad_b+18}" text-anchor="middle" font-size="12" fill="#475569" font-weight="600">{b["label"]}</text>'

        if i < len(bars) - 1:
            conn_y = Y(b["conn_from"])
            out += f'<line x1="{x+bar_w:.1f}" y1="{conn_y:.1f}" x2="{x+step_w:.1f}" y2="{conn_y:.1f}" stroke="#94A3B8" stroke-width="1" stroke-dasharray="4 3"/>'
    return f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;display:block">{out}</svg>'


def svg_ladder(items, width=680, height=420, pad_l=30, pad_r=30, pad_t=48, pad_b=96):
    """财富自由阶梯（竖向）：柱高按等级递升形成阶梯，柱内自下而上的填充表示「当前净资产 ÷ 该级目标」。
    填充色轮转 config.PIE_COLORS（与 Tab1 同源），轨道为中性浅灰；viewBox 宽 680，与瀑布图一致。
    等级图标（emoji）放在**实心填充块的垂直中心**（不是柱顶）；图例放在柱子**下方**并水平居中。
    items: [{name, icon, cost_hkd, target_usd, reached, years_needed, progress}]"""
    n = len(items)
    palette = [config.PIE_COLORS[c] for c in config.CATS]
    step_w = (width - pad_l - pad_r) / n
    bar_w = step_w * 0.62
    base_y = height - pad_b
    max_bar_h = base_y - pad_t - 54

    out = ""

    for i in range(n - 1):
        y1 = base_y - (i + 1) / n * max_bar_h
        y2 = base_y - (i + 2) / n * max_bar_h
        x1 = pad_l + step_w * i + step_w / 2 + bar_w / 2
        x2 = pad_l + step_w * (i + 1) + step_w / 2 - bar_w / 2
        out += (f'<path d="M {x1:.1f} {y1:.1f} L {x2:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}" '
                f'fill="none" stroke="#DDE4EC" stroke-width="1.2" stroke-dasharray="4,3"/>')

    for i, item in enumerate(items):
        bar_h = (i + 1) / n * max_bar_h
        progress = max(0.0, min(float(item.get("progress", 0.0)), 1.0))
        color = palette[i % len(palette)]
        x_center = pad_l + step_w * i + step_w / 2
        x_left = x_center - bar_w / 2
        y_top = base_y - bar_h


        out += (f'<rect x="{x_left:.1f}" y="{y_top:.1f}" width="{bar_w:.1f}" '
                f'height="{bar_h:.1f}" rx="6" fill="{color}" fill-opacity="0.16"/>')
        fill_h = 0.0
        if progress > 0:
            fill_h = max(bar_h * progress, 6)
            out += (f'<rect x="{x_left:.1f}" y="{base_y - fill_h:.1f}" width="{bar_w:.1f}" '
                    f'height="{fill_h:.1f}" rx="6" fill="{color}"/>')

        out += (f'<text x="{x_center:.1f}" y="{y_top-9:.1f}" text-anchor="middle" '
                f'font-size="12" font-weight="700" fill="{color}">{progress*100:.1f}%</text>')

        emoji_cy = base_y - max(fill_h / 2.0, 12.0)
        out += (f'<text x="{x_center:.1f}" y="{emoji_cy + 6:.1f}" text-anchor="middle" '
                f'font-size="18">{item["icon"]}</text>')

        out += (f'<text x="{x_center:.1f}" y="{base_y+18:.1f}" text-anchor="middle" '
                f'font-size="12" font-weight="700" fill="#2D3748">{item["name"]}</text>')
        if item["reached"]:
            status, status_c = "✓ 已达成", color
        elif item["years_needed"]:
            status, status_c = f"约 {item['years_needed']} 年", "#B26A00"
        else:
            status, status_c = "—", "#A0A0A0"
        out += (f'<text x="{x_center:.1f}" y="{base_y+34:.1f}" text-anchor="middle" '
                f'font-size="10.5" fill="{status_c}" font-weight="600">{status}</text>')


    legend_y = height - 24
    out += (f'<text x="{width/2:.1f}" y="{legend_y:.1f}" text-anchor="middle" font-size="11" fill="#64748B">'
            f'<tspan fill="{palette[0]}">■</tspan> 实色 = 当前净资产 ÷ 该级目标（完成度）'
            f'　　　<tspan fill="{palette[0]}" fill-opacity="0.18">■</tspan> 淡色 = 尚未达成部分</text>')
    return f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;display:block">{out}</svg>'


def svg_allocation(series, width=760, height=340, pad_l=64, pad_r=112, pad_t=42, pad_b=46):
    """仓位结构随时间变化（% 总资产）。series: [(date, cash%, stock%, options%)]，已按实缴门槛过滤。
    三条线：现金（蓝）、股票（绿）、期权（金）。注意三者之和 = 100%（净值口径），所以：
    - 现金为负 = 用了保证金（借钱持股），此时股票会 > 100%（例如现金 −155% + 股票 257%）；
    - 期权为负 = 卖出的期权按市价计负债（卖出开仓），为正 = 买权持仓。
    纵轴按三条线的范围自适应（50% 一档，必含 0%），0% 画深色虚线。"""
    if len(series) < 2:
        return ""
    dates = [r[0] for r in series]
    cash = [r[1] for r in series]
    stock = [r[2] for r in series]
    options = [r[3] for r in series]
    lo = min(cash + stock + options + [0.0])
    hi = max(cash + stock + options + [0.0])
    pad = max((hi - lo) * 0.08, 12.0)
    y_min = math.floor((lo - pad) / 50.0) * 50.0
    y_max = math.ceil((hi + pad) / 50.0) * 50.0
    if y_max == y_min:
        y_max = y_min + 50.0

    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(series)
    span_days = max((dates[-1] - dates[0]).days, 1)

    def X(i):
        return pad_l + plot_w * ((dates[i] - dates[0]).days / span_days)

    def Y(v):
        return pad_t + plot_h * (1 - (v - y_min) / (y_max - y_min))

    LINE_CASH, LINE_STOCK, LINE_OPT = "#4A90D9", "#7A9A3F", "#C9A227"
    out = ""

    v = y_min
    while v <= y_max + 1e-9:
        gy = Y(v)
        is_zero = abs(v) < 1e-9
        stroke = "#94A3B8" if is_zero else "#EDF0F4"
        dash = ' stroke-dasharray="5 4"' if is_zero else ""
        label_c = "#64748B" if is_zero else "#94A3B8"
        out += (f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width-pad_r}" y2="{gy:.1f}" '
                f'stroke="{stroke}"{dash}/>')
        out += (f'<text x="{pad_l-8}" y="{gy+4:.1f}" text-anchor="end" font-size="11" '
                f'fill="{label_c}">{v:.0f}%</text>')
        v += 50.0

    for i in sorted({0, n // 4, n // 2, 3 * n // 4, n - 1}):
        out += (f'<text x="{X(i):.1f}" y="{height-pad_b+18:.1f}" text-anchor="middle" '
                f'font-size="11" fill="#94A3B8">{dates[i].strftime("%Y-%m")}</text>')

    for vals, color in ((cash, LINE_CASH), (stock, LINE_STOCK), (options, LINE_OPT)):
        pts = " ".join(f"{X(i):.1f},{Y(vals[i]):.1f}" for i in range(n))
        out += (f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.2" '
                f'stroke-linejoin="round"/>')
        out += (f'<circle cx="{X(n-1):.1f}" cy="{Y(vals[-1]):.1f}" r="4" fill="#fff" '
                f'stroke="{color}" stroke-width="2.5"/>')

    labels = sorted([(Y(cash[-1]) - 5, LINE_CASH, cash[-1]),
                     (Y(stock[-1]) - 5, LINE_STOCK, stock[-1]),
                     (Y(options[-1]) - 5, LINE_OPT, options[-1])], key=lambda r: r[0])
    min_gap = 22.0
    top_limit, bottom_limit = pad_t + 12, height - pad_b - 6
    labels = [(max(top_limit, min(y, bottom_limit)), c, v) for y, c, v in labels]
    for i in range(1, len(labels)):
        if labels[i][0] - labels[i - 1][0] < min_gap:
            labels[i] = (labels[i - 1][0] + min_gap, labels[i][1], labels[i][2])
    overflow = labels[-1][0] - bottom_limit
    if overflow > 0:
        labels = [(y - overflow, c, v) for y, c, v in labels]

    for ly, color, val in labels:
        out += (f'<line x1="{X(n-1)+5:.1f}" y1="{Y(val):.1f}" x2="{width-pad_r+16:.1f}" y2="{ly:.1f}" '
                f'stroke="{color}" stroke-width="1" stroke-opacity="0.65"/>')
        out += (f'<text x="{width-8:.1f}" y="{ly+4:.1f}" text-anchor="end" '
                f'font-size="12" font-weight="700" fill="{color}">{val:.1f}%</text>')

    legend_y = 20
    out += f'<rect x="{pad_l}" y="5" width="{plot_w:.1f}" height="24" rx="5" fill="#F8FAFC"/>'
    out += (f'<text x="{width/2:.1f}" y="21" text-anchor="middle" font-size="11.5" fill="#64748B">'
            f'<tspan fill="{LINE_CASH}" font-weight="700">━</tspan> 现金　'
            f'<tspan fill="{LINE_STOCK}" font-weight="700">━</tspan> 股票　'
            f'<tspan fill="{LINE_OPT}" font-weight="700">━</tspan> 期权　　'
            f'<tspan fill="#94A3B8">┄</tspan> 0% 线（现金为负 = 使用保证金）</text>')
    out += f'<g id="allocCrosshair" style="display:none"><line id="allocV" x1="0" y1="{pad_t}" x2="0" y2="{height-pad_b}" stroke="#64748B" stroke-width="1" stroke-dasharray="4 3"/><circle id="allocDotCash" r="4" fill="{LINE_CASH}" stroke="#FFF" stroke-width="2"/><circle id="allocDotStock" r="4" fill="{LINE_STOCK}" stroke="#FFF" stroke-width="2"/><circle id="allocDotOpt" r="4" fill="{LINE_OPT}" stroke="#FFF" stroke-width="2"/></g>'
    for i in range(n):
        left = X(i) - (plot_w / max(n - 1, 1) / 2 if i else 0)
        right = X(i) + (plot_w / max(n - 1, 1) / 2 if i < n - 1 else 0)
        out += f'<rect class="alloc-hit" data-i="{i}" data-cash-y="{Y(cash[i]):.1f}" data-stock-y="{Y(stock[i]):.1f}" data-opt-y="{Y(options[i]):.1f}" x="{max(pad_l,left):.1f}" y="{pad_t}" width="{max(right-left,2):.1f}" height="{plot_h}" fill="transparent"/> '
    return f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:auto;display:block">{out}</svg>'


def svg_industry_donut(items, width=420, height=380):
    """生成长期持仓行业占比环形图。items 为 [(行业, 百分比)]。"""
    colors = INDUSTRY_COLORS
    cx, cy, r, stroke = 210, 135, 105, 42
    total = sum(v for _, v in items) or 1
    circumference, acc = 2 * math.pi * r, 0
    out = []
    for idx, (label, value) in enumerate(items):
        dash = value / total * circumference
        rot = acc / circumference * 360 - 90
        out.append(f'<circle class="industry-pie-seg" data-i="{idx}" cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{colors[idx % len(colors)]}" stroke-width="{stroke}" stroke-dasharray="{dash:.2f} {circumference-dash:.2f}" transform="rotate({rot:.2f} {cx} {cy})" style="cursor:pointer"/>')
        col, row = idx % 2, idx // 2
        lx, ly = 50 + col * 200, 291 + row * 24
        out.append(f'<rect x="{lx}" y="{ly-10}" width="10" height="10" rx="2" fill="{colors[idx % len(colors)]}"/>')
        out.append(f'<text x="{lx+17}" y="{ly}" font-size="12" fill="#475569">{label} {value:.1f}%</text>')
        acc += dash
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{r-stroke/2}" fill="#FFF"/>')
    out.append(f'<text x="{cx}" y="{cy-2}" text-anchor="middle" font-size="12" fill="#94A3B8">正股</text>')
    out.append(f'<text x="{cx}" y="{cy+18}" text-anchor="middle" font-size="16" font-weight="700" fill="#0F172A">{total:.1f}%</text>')
    return f'<svg viewBox="0 0 {width} {height}" style="width:100%;max-width:{width}px;height:auto;display:block">{"".join(out)}</svg>'
