# BetaNews Dashboard

加密货币竞品监控仪表盘，自动从四大交易所拉取数据，聚合行业资讯，生成静态页面。

## 功能

- **竞品监控**：Binance、OKX、Bitget、Bybit 四所 Top 交易对，按 1h 成交额/涨幅/跌幅排名
- **新币上线**：12h 内新上线交易对，自动检测并展示
- **行业资讯**：交易所公告（自动翻译）、Hacker News 热门、Cointelegraph RSS
- **快照对比**：历史数据快照，支持时间点对比

## 数据来源

| 来源 | 用途 |
|------|------|
| Binance API | ticker、K线、公告 |
| OKX API | ticker、K线、公告 |
| Bitget API | ticker、K线、公告 |
| Bybit API | ticker、K线、公告 |
| Hacker News API | 科技热点 |
| Cointelegraph RSS | 加密行业资讯 |

## 文件说明

| 文件 | 说明 |
|------|------|
| `betanews.html` | 主仪表盘页面（自动生成） |
| `snapshot.html` | 快照对比页面 |
| `exchange-pairs-snapshot.json` | 交易对快照数据 |
| `dashboard-snapshots.jsonl` | 历史快照（7 天滚动） |
| `new-listings.json` | 新上线币对列表 |

## 技术栈

- Python 3（数据抓取 + 页面生成）
- 纯静态 HTML/CSS/JS（无框架依赖）
- GitHub Contents API（自动部署）
