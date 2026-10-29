"""独立静态演示页面；所有交互只更新浏览器内的虚构数据。"""
import json
from html import escape

CSS = '''*{box-sizing:border-box}body{margin:0;background:#f3f6fa;color:#17243a;font:15px/1.65 system-ui,sans-serif}main{max-width:1160px;margin:auto;padding:44px 24px}a{color:#2865a0}h1{font-size:40px;line-height:1.2;letter-spacing:-1.5px;margin:12px 0}h2{font-size:20px}p{color:#576980}.eyebrow{color:#36769b;font-size:12px;letter-spacing:2px;font-weight:700}.badge{display:inline-block;padding:4px 10px;border-radius:6px;background:#e1eef3;color:#256178;font-size:12px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:25px 0}.card{background:white;padding:24px;border:1px solid #e0e7ef;border-radius:14px;box-shadow:0 5px 18px #23395b05}.value{font-size:30px;font-weight:650;font-variant-numeric:tabular-nums}.muted{color:#61718a;font-size:13px}select,button{font:inherit;background:#fff;border:1px solid #c9d5e4;border-radius:7px;padding:8px 12px}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:14px 10px;border-bottom:1px solid #e8edf3}th{color:#65748c;font-size:12px}.scroll{overflow:auto}.positive{color:#287255}summary{cursor:pointer}header{display:flex;justify-content:space-between;gap:20px;align-items:center}footer{margin-top:32px;color:#718097;font-size:12px}@media(max-width:700px){.grid{grid-template-columns:1fr}h1{font-size:30px}main{padding:25px 16px}header{display:block}}'''


def shell(title, body, script=''):
    """返回包含内嵌样式与脚本的完整离线HTML。"""
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)}</title><style>{CSS}</style><main>{body}'
            '<footer>WEALTH SHOWCASE · 合成数据 · 无外部资源依赖</footer></main>'
            f'<script>{script}</script></html>')


def write_workspace(output):
    """复用原工作台模板，以合成快照驱动原显示函数。"""
    from .workspace import write_workspace as write
    write(output)


def write_timeline(output, source):
    """以可核验的功能节点展示演进，完整提交元数据默认折叠。"""
    from .journey import write_timeline as write
    write(output, source)
