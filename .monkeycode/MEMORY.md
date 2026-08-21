# User Instruction Memory

This file records user instructions, preferences, and teachings for reference in future interactions.

## Format

### User Instruction Entry
User instruction entries should follow this format:

[User Instruction Summary]
- Date: [YYYY-MM-DD]
- Context: [Mentioned scenario or time]
- Instructions:
  - [Content of user teaching or instruction, described line by line]

### Project Knowledge Entry
Entries discovered by the Agent during task execution should follow this format:

[Project Knowledge Summary]
- Date: [YYYY-MM-DD]
- Context: Discovered by Agent while performing [specific task description]
- Category: [Operations & Deployment|Build Methods|Testing Methods|Troubleshooting & Debugging|Workflow & Collaboration|Environment Configuration]
- Instructions:
  - [Specific knowledge points, described line by line]

## Deduplication Strategy
- Before adding a new entry, check for similar or identical instructions.
- If a duplicate is found, skip the new entry or merge it with the existing one.
- When merging, update the context or date information.
- This helps avoid redundant entries and keeps the memory file tidy.

## Entries

[User Instruction Summary]
- Date: 2026-08-21
- Context: 构建 X-UI-Worker 项目（基于 K-UI-workers 重构）时用户明确要求
- Instructions:
  - agent.py 必须与 K-UI-workers 原版完全一致，仅允许 KUI→X-UI 品牌与路径改名，不得移植 X-UI-VPS 的 probe_only 逻辑。
  - 探针功能采用独立脚本（probe.py + probe.sh）实现，参考 cf-vps-monitor，不修改 agent.py。

[Project Knowledge Summary]
- Date: 2026-08-21
- Context: Discovered by Agent while building X-UI-Worker from K-UI-workers
- Category: Operations & Deployment
- Instructions:
  - GitHub 仓库：https://github.com/xiaoli8571/X-UI-Worker（public，master 分支），一键部署 URL 指向该仓库。
  - 部署：`npx wrangler login && npx wrangler deploy`；本地预览 `npm run dev`；本地工程位于 /tmp/opencode/X-UI-Worker。
  - Worker 名称 xui，D1 binding 固定为 DB，DO 绑定 VPS_PRESENCE/DASHBOARD_HUB，兼容性标志需 assets_navigation_prefer_worker。
  - CF 免费额度优化策略：cron 每 15 分钟、realtime 广播间隔降频（admin 15s/public 20s/idle 60s）、agent 上报间隔由后端 effectiveInterval 动态下发（fastMode ≥15s，idle ≥90s，上限 300s）。
