# 项目本地说明文档

> 此文件不提交 GitHub，仅用于本地维护参考。

## 项目概述

竞品监控 Dashboard，自动从四所（Binance、OKX、Bitget、Bybit）拉取加密货币数据，聚合 HN 和 Cointelegraph 资讯，生成静态 HTML 页面，推送到 GitHub Pages。

## 核心文件

### 生产文件（提交 GitHub）

| 文件 | 用途 | 维护状态 |
|------|------|----------|
| `gen_page.py` | 主脚本，1152 行。拉数据 + 生成 HTML + 推送 GitHub | 活跃维护 |
| `template.html` | betanews.html 的 HTML 模板 | 活跃维护 |
| `betanews.html` | 生成的主仪表盘页面 | 自动生成 |
| `snapshot.html` | 快照对比页面（含内嵌 JS） | 手动维护 |
| `config.json` | GitHub token + repo 配置（.gitignore 排除） | 手动维护 |
| `.gitignore` | 排除本地文件 | 手动维护 |

### 数据文件（提交 GitHub，自动生成）

| 文件 | 用途 |
|------|------|
| `exchange-pairs-snapshot.json` | 四所交易对快照，用于差集检测新币 |
| `new-listings.json` | 12h 内新上线币对列表 |
| `dashboard-snapshots.jsonl` | 历史快照（7 天滚动），供快照对比页使用 |

### 历史遗留文件（本地保留，不提交 GitHub）

| 文件 | 来历 | 说明 |
|------|------|------|
| `protemplate.html` (15MB) | CoinW 设计系统模板 | 早期设计参考，内嵌 base64 字体，占 repo 99% 体积 |
| `phase1.py` / `phase1.json` | 开发阶段产物 | 第一阶段：拉取 ticker + 差集检测 |
| `phase2.py` / `phase2.json` | 开发阶段产物 | 第二阶段：K线数据处理 |
| `phase3.py` | 开发阶段产物 | 第三阶段：HTML 生成 |
| `fetch-dashboard-data.sh` | 早期 shell 脚本 | 用 curl 拉 CoinGecko + HN 数据 |
| `index.html` | 早期 HTML 页面 | 被 betanews.html 替代 |
| `_snap_data.json` | 调试残留 | gen_page.py 不读取 |
| `ct_news.json` / `hn_stories.json` | 调试残留 | gen_page.py 直接拉实时数据 |
| `exchange-freq.json` | 配置残留 | 交易所频率配置，gen_page.py 不使用 |
| `HANDOFF-snapshot-template.md` | 交接文档 | snapshot.html 的开发说明 |

## 架构演进

项目经历了三个开发阶段：

1. **Phase 1-3**（已废弃）：分阶段脚本，输出到 JSON 中间文件，再由前端读取渲染
2. **betaDashboard/protemplate**（已废弃）：CoinW 设计系统的前端方案
3. **gen_page.py**（当前）：单脚本全搞定，Python 直接生成静态 HTML，无需前端 JS 框架

## gen_page.py 执行流程

1. 拉四所 ticker → 更新 exchange-pairs-snapshot.json → 差集检测新币
2. 拉 1h K线（新币优先 + 各所 Top N）→ 计算涨跌幅和成交额
3. 拉四所公告 → 英文标题翻译
4. 拉 HN Top 15 + Cointelegraph RSS → 标题翻译
5. 读 template.html → 填入数据 → 生成 betanews.html
6. 追加快照到 dashboard-snapshots.jsonl（自动清理 7 天前旧快照）
7. 并行推送 5 个文件到 GitHub（GitHub Contents API）

## 定时任务

通过 Cowork 的 scheduled-tasks 机制自动运行，执行 `python3 gen_page.py`。

## 注意事项

- GitHub token 存在 config.json，已在 .gitignore 中排除
- 推送使用 GitHub Contents API（非 git push），支持并行推送
- OKX 有信号量限流（`_okx_sem`），防止并发请求过多
- 翻译使用 Google Translate API（无 key，有频率限制）
