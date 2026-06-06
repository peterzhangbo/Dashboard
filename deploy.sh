#!/bin/bash
# 部署脚本：提交所有改动并推送 GitHub
# 在本地终端运行：bash deploy.sh
set -e

cd "$(dirname "$0")"

echo "=== Git 状态 ==="
git status --short

echo ""
echo "=== 添加文件 ==="
# 核心文件（被误 untrack 的）
git add template.html

# 本次改动
git add gen_page.py .gitignore

# 生成的输出文件
git add betanews.html artifact-index.html new-listings.json dashboard-snapshots.jsonl

echo ""
echo "=== 提交 ==="
git commit -m "refactor: streak阈值↑3 + Bitget缓存 + 自动刷新重构 + 项目清理

- streak 徽标改为连续在榜>3小时才显示
- Bitget现货 listing_time 加全量symbols缓存
- 自动刷新改为基于更新时间+65分钟
- 补偿循环/推送线程变量名优化
- CSS去重 + 历史文件归档至 _archive/
- template.html 重新纳入 git 跟踪"

echo ""
echo "=== 推送 ==="
git push origin main

echo ""
echo "=== 完成 ==="
echo "GitHub 已更新，CDN 会在几分钟内生效。"
