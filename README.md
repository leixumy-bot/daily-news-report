# AI+Cloud 每日早报

> 版本：v4 · 自动采集 → LLM 处理 → 飞书推送

每日自动搜集 AI 与云计算领域的最新资讯，经 LLM 去重聚类、精读摘要后，推送飞书群聊并归档知识库。

## 架构

```
┌─ 采集层 ─────────────────────┐
│ RSS 订阅（16 个源）            │
│ Web 搜索（20 个定向站点）       │
│ 播客搜索（7 个节目）           │
│ 微信/小红书（本地 MCP 采集）    │
└──────────┬───────────────────┘
           ↓
┌─ 处理层 ─────────────────────┐
│ 关键词过滤                    │
│ LLM 去重与聚类（分层聚类）      │
│ LLM 精读摘要                  │
└──────────┬───────────────────┘
           ↓
┌─ 输出层 ─────────────────────┐
│ 飞书群聊（精选卡片 + 完整列表）  │
│ 飞书知识库归档                 │
│ 飞书多维表格记录持久化          │
└──────────────────────────────┘
```

## 数据流

1. **采集**：同时从 RSS、Web Search、播客搜索、本地 MCP 四个通道采集 AI/Cloud 相关资讯
2. **过滤**：关键词匹配筛选（含中英文 AI/云计算关键词 30+）
3. **去重聚类**：LLM 分层聚类，合并相同主题的多来源报道
4. **精读摘要**：LLM 对每个聚类生成结构化摘要（要点、影响、来源）
5. **格式化**：组装精选卡片和完整列表
6. **推送**：飞书群聊消息 + 知识库文档 + 多维表格记录

## 部署

### GitHub Actions（推荐）

配置 Repository Secrets：

| Secret | 说明 |
|--------|------|
| `ANTHROPIC_AUTH_TOKEN` | LLM API Key（DeepSeek via Anthropic 协议） |
| `ANTHROPIC_BASE_URL` | API Base URL（可选，默认 `https://api.deepseek.com/anthropic`） |
| `LARK_APP_ID` | 飞书自建应用 App ID |
| `LARK_APP_SECRET` | 飞书自建应用 App Secret |
| `LARK_BASE_TOKEN` | 飞书多维表格 Token |

配置后自动生效。每天北京时间 09:30 和 11:30 各触发一次（双定时兜底，已跑过的自动跳过）。

### 本地运行

```bash
# 准备工作
export ANTHROPIC_AUTH_TOKEN="sk-..."
export LARK_APP_ID="cli_xxx"
export LARK_APP_SECRET="xxx"

# 安装依赖
pip install -r requirements.txt

# 完整流程（采集→处理→推送）
python3 daily_report.py

# 只采集+处理，不推送
python3 daily_report.py --dry-run

# 只采集不做处理
python3 daily_report.py --collect-only

# 补跑某天的报告
python3 daily_report.py --date 2026-07-24

# 强制重跑（跳过今日已完成的检查）
python3 daily_report.py --force
```

## 配置

所有配置集中在 `config.json`：

- **sources.rss**：RSS 订阅源列表（支持 OpenAI、DeepMind、AWS、36氪、雷峰网等 16 个源）
- **sources.web_search**：定向搜索站点列表（20 个站点 × 每站 3 条结果）
- **sources.podcast**：播客节目搜索（硅谷101、42章经、Dwarkesh 等 7 个）
- **keywords**：中英文包含/排除关键词
- **feishu**：飞书群聊、Wiki、应用凭证
- **llm**：模型 API 配置（默认 deepseek-v4-flash[1M]）

## 幂等保护

- 双定时（09:30 / 11:30）间通过 `.last_run` 文件 + GitHub Actions Cache 双重保障，已完成的当天不重复跑
- 手动触发使用 `--date` 参数可补跑历史日期

## 本地采集（可选）

微信文章和小红书笔记通过本地 MCP 客户端采集（不包含在 CI 流程中）：

```bash
python3 daily_report.py --collect-only
```

需配置本地 MCP 服务。详见 `collectors/mcp_client.py`。
