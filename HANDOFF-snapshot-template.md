# 快照页面模板化改造 — 交接文档

## 1. 背景

当前主页 `betanews.html` 由 `gen_page.py` 从 `template.html` 生成。点击"历史快照"下拉菜单中的某个时间点时，会打开一个新窗口显示该快照的详情。

### 当前实现的问题

快照详情页的 HTML 是在 JavaScript 字符串里拼接生成的（`openSnapNewTab` 函数）：

```javascript
// template.html 第 250-262 行
function openSnapNewTab(s){
  var b='<!DOCTYPE html><html><head>...<style>body{font-family:Inter...';
  b+='<h2>快照：'+d.toLocaleString('zh-CN')+'</h2>';
  if(s.btc){ b+='<div class="k">...'; }
  if(s.hn&&s.hn.length){ b+='<h3>Hacker News</h3><table>...'; }
  if(s.crypto&&s.crypto.length){ b+='<h3>加密热点</h3><table>...'; }
  var w=window.open('','_blank');w.document.write(b+'</body></html>');w.document.close();
}
```

**问题**：
- CSS 嵌在 JS 字符串里，改样式要翻代码
- 样式非常简陋，跟主页风格割裂
- `document.write` 是过时 API，新窗口难以调试
- 扩展性差，加新数据字段要拼接更多字符串

## 2. 数据结构

快照数据存储在 `dashboard-snapshots.jsonl`，每行一个 JSON 对象：

```json
{
  "ts": "2026-06-04T16:32:00Z",
  "btc": {
    "price": 63708,
    "change": -3.20,
    "mcap": 1270
  },
  "hn": [
    {"t": "标题", "s": 752, "c": 562, "ts": 1779986954},
    ...
  ],
  "crypto": [
    {"t": "标题", "tag": "交易所"},
    ...
  ],
  "rankings": {
    "bn_spot_vol": ["SYM1", "SYM2", "SYM3"],
    ...
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| ts | string | ISO 8601 时间戳 |
| btc.price | number | BTC 价格（USD） |
| btc.change | number | 24h 涨跌幅（%） |
| btc.mcap | number | 市值（美元） |
| hn | array[8] | Hacker News 热门 8 条 |
| hn[].t | string | 标题 |
| hn[].s | number | 分数 |
| hn[].c | number | 评论数 |
| hn[].ts | number | 发布时间（Unix 秒） |
| crypto | array[8] | CoinTelegraph 加密新闻 8 条 |
| crypto[].t | string | 标题 |
| crypto[].tag | string | 分类标签 |
| rankings | object | 各交易所各市场 Top 3 排名（用于 streak 计算） |

**注意**：JSONL 文件约 370KB，保留最近 7 天数据（由 `SNAP_RETAIN_HOURS=168` 控制）。

## 3. 目标

创建一个独立的快照模板页 `snapshot.html`，实现：

1. **样式一致** — 复用主页的设计系统（CSS 变量、字体、配色）
2. **数据驱动** — 模板只定义结构，数据通过 URL 参数或 API 动态填充
3. **易于维护** — 改样式改 HTML，不碰 JS 逻辑
4. **加载可靠** — 使用 CDN fallback 机制（已实现）

## 4. 文件结构

```
Dashboard/
├── template.html          # 主页模板（gen_page.py 读取）
├── snapshot.html          # 【新增】快照详情页模板
├── gen_page.py            # 生成主页 + 推送 GitHub
├── betanews.html          # 生成的主页（含快照下拉菜单）
├── dashboard-snapshots.jsonl  # 快照数据
└── ...
```

## 5. 实现方案

### 方案 A：纯前端方案（推荐）

`snapshot.html` 是一个完整的独立页面，通过 URL hash 传递数据索引：

```
https://peterzhangbo.github.io/Dashboard/snapshot.html#2
```

`#2` 表示显示 JSONL 文件中的第 2 条（从最新开始数）。

**流程**：
1. 主页点击快照 → `window.open('snapshot.html#' + index)`
2. `snapshot.html` 加载时解析 hash 获取索引
3. 从 CDN fallback 链加载 `dashboard-snapshots.jsonl`
4. 解析 JSONL，找到对应索引的记录
5. 用 DOM 操作填充模板

**snapshot.html 结构**：
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>快照 - 科技与加密货币仪表盘</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    /* 复用主页的 CSS 变量和设计系统 */
    :root { --bg: #f1f5f9; --card: #fff; --border: #e2e8f0; ... }
    /* 快照页特有的样式 */
    .snap-header { ... }
    .btc-kpi { display: grid; grid-template-columns: 1fr 1fr 1fr; ... }
    .news-table { width: 100%; border-collapse: collapse; ... }
  </style>
</head>
<body>
  <div class="container">
    <h1 id="snap-title">快照</h1>
    <div id="btc-section" class="btc-kpi"></div>
    <div id="hn-section"></div>
    <div id="crypto-section"></div>
  </div>
  <script>
    // 1. 解析 hash 获取索引
    // 2. CDN fallback 加载 JSONL
    // 3. 解析并填充 DOM
  </script>
</body>
</html>
```

### 方案 B：服务端渲染（备选）

在 `gen_page.py` 中为每个快照生成独立 HTML 文件：

```
snapshots/
├── 2026-06-04T16-32.html
├── 2026-06-04T15-00.html
└── ...
```

**缺点**：文件数量多（每天 24 个 × 7 天 ≈ 168 个文件），不适合 GitHub Pages。

## 6. 主页需要改动的地方

`template.html` 中 `openSnapNewTab` 函数改为：

```javascript
function openSnapNewTab(s){
  document.getElementById('snap-dd').classList.remove('open');
  // 找到当前快照在数组中的索引
  var idx = snapshots.indexOf(s);
  window.open('snapshot.html#' + idx, '_blank');
}
```

同时 `loadSnaps` 函数需要把解析后的 `snapshots` 数组存到全局变量（当前已经是全局变量）。

## 7. 设计规范

从 `template.html` 提取的 CSS 变量（必须复用）：

```css
:root {
  --bg: #08080A;
  --surface: #121214;
  --surface-2: #1A1A1C;
  --surface-3: #232326;
  --hairline: rgba(255,255,255,0.09);
  --divider: rgba(255,255,255,0.06);
  --fg: #fff;
  --fg-2: rgba(255,255,255,0.66);
  --fg-3: rgba(255,255,255,0.42);
  --brand: #5227FF;
  --brand-400: #6C4FFF;
  --up: #1ED760;
  --down: #FF5C42;
  --warning: #FFA940;
  --lime: #D1FF55;
  --mono: 'Fira Code', monospace;
  --sans: 'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
```

## 8. CDN Fallback（已实现）

`loadSnaps` 函数已实现多节点 fallback，可直接复用到 `snapshot.html`：

```javascript
var REPO='peterzhangbo/Dashboard';
var CDN_URLS = [
  'dashboard-snapshots.jsonl',  // 本地同目录优先
  'https://cdn.jsdelivr.net/gh/' + REPO + '@main/dashboard-snapshots.jsonl',
  'https://fastly.jsdelivr.net/gh/' + REPO + '@main/dashboard-snapshots.jsonl',
  'https://gcore.jsdelivr.net/gh/' + REPO + '@main/dashboard-snapshots.jsonl'
];
// + GitHub API 兜底
```

## 9. 测试清单

- [ ] 主页点击快照能打开新窗口
- [ ] 新窗口显示正确的快照时间
- [ ] BTC 价格、涨跌、市值显示正确
- [ ] HN 15 条数据完整，标题/分数/评论对齐
- [ ] 加密热点 10 条数据完整，分类标签显示
- [ ] 样式与主页一致（配色、字体、间距）
- [ ] 国内网络能正常加载（CDN fallback 生效）
- [ ] 无快照数据时显示友好提示
- [ ] 浏览器 F12 可正常调试

## 10. 注意事项

1. **字体加载** — Google Fonts 在国内被墙，需要 fallback 字体链：`'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif`
2. **JSONL 大小** — 当前 245KB，7 天后会更大。考虑是否需要分页或限制条数
3. **时间显示** — `hn[].ts` 是 Unix 秒时间戳，需要转换为本地时间
4. **空数据处理** — 某些快照可能缺少 `hn` 或 `crypto` 字段，需要容错
