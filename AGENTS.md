# Showcase maintenance

这是独立公开展示版，所有输入必须来自 `demo/` 的合成数据。禁止读取或复制个人账本、私有环境配置、设备标识、券商凭据与原项目的授权/运行记录。

- 保持计算在 `core.py`、样式和页面在 `charts.py` / `report.py`、参数在 `config.py`。
- 不添加真实交易接口；工作台只在浏览器中切换静态场景。
- 不将 data/、.env、数据库、账户导出加入 Git。
- 不自动 commit/push；不要制造或倒填历史提交。
- 修改代码同步版本和 CHANGELOG；执行 `python -m pytest tests/ -v` 与 `python scripts/gen_report.py`。
- 生成 HTML 是已审查的合成展示产物，可入库；不要用个人报告覆盖。
- 维护开发时间线时注明数据来自私有源项目，不等同公开仓库提交历史。
