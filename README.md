# AI+Cloud 每日早报

> 版本：v5.5 · 自动采集 → LLM 去重聚类 → 精读摘要 → 飞书推送

每日自动搜集 AI 与云计算领域最新资讯，经 LLM 去重聚类、精读摘要后，推送飞书群聊，并归档到飞书知识库与多维表格。

## 架构

```
┌─ 采集层 ─────────────────────┐
│ RSS 订阅（16 个源）            │
│ Web 搜索（29 个定向查询）      │
│ 播客搜索（7 个节目）           │
│ 官方媒体 / 微信 / 小红书        │
└──────────┬───────────────────┘
           ↓
┌─ 处理层 ─────────────────────┐
│ 关键词过滤（57 个关键词）       │
│ LLM 去重聚类（分层 + 语义合并） │
│ LLM 精读摘要                  │
└──────────┬───────────────────┘
           ↓
┌─ 输出层 ─────────────────────┐
│ 飞书群聊（精选 + 政策安全两段）  │
│ 飞书多维表格记录持久化          │
│ 飞书知识库归档（本地模式）       │
└──────────────────────────────┘
```

## 数据流

1. **采集**：RSS、Web 搜索、播客、官方媒体等多通道并行采集
2. **过滤**：中英文关键词匹配（57 个，官方媒体宽松过滤）
3. **去重聚类**：LLM 分层聚类合并多来源重复报道；跨批再做语义合并（宁合不拆）
4. **精读摘要**：LLM 对每个聚类生成 200-300 字结构化摘要，标注对 AI/Cloud GTM 的启示
5. **跨天去重**：与近 7 天多维表格历史比对，仅推新主题或明确新进展（内容指纹 + URL + LLM 语义判断）
6. **推送**：飞书群聊消息 + 多维表格记录 + 知识库归档

## 部署

### GitHub Actions（推荐）

运行环境 Python 3.13，依赖锁定在 `requirements*.txt`。

配置 Repository Secrets：

| Secret | 说明 |
|--------|------|
| `ANTHROPIC_AUTH_TOKEN` | LLM API Key（DeepSeek via Anthropic 协议） |
| `ANTHROPIC_BASE_URL` | API Base URL（可选，默认 `https://api.deepseek.com/anthropic`） |
| `LARK_APP_ID` | 飞书自建应用 App ID |
| `LARK_APP_SECRET` | 飞书自建应用 App Secret |
| `LARK_BASE_TOKEN` | 飞书多维表格 Token |

配置后自动生效。每天北京时间 **09:00** 主推送、**09:45** 保底（仅在 09:00 未完成时补跑）。

### 本地运行

```bash
# 环境变量
export ANTHROPIC_AUTH_TOKEN="sk-..."
export LARK_APP_ID="cli_xxx"
export LARK_APP_SECRET="xxx"

pip install -r requirements.txt

python3 daily_report.py                # 完整流程（本地默认只预览）
python3 daily_report.py --dry-run      # 只采集+处理，不推送
python3 daily_report.py --collect-only # 只采集
python3 daily_report.py --date 2026-07-24  # 补跑某天
python3 daily_report.py --force        # 强制重跑今天
```

## 配置

集中在 `config.json`：

- **sources.rss**：16 个 RSS 源（OpenAI、DeepMind、AWS、36氪、雷峰网等）
- **sources.web_search**：29 个定向查询 × 每查询多条结果
- **sources.podcast**：7 个播客节目（硅谷101、42章经、Dwarkesh 等）
- **keywords**：中英文包含/排除关键词
- **feishu**：飞书群聊、知识库、应用凭证
- **bitable**：多维表格 ID、跨天去重窗口（默认 7 天）
- **llm**：模型 API 配置（默认 deepseek-v4-flash[1M]）

## 幂等与防重复

- **双定时**：09:00 主推送 + 09:45 保底，间隔 45 分钟（< 飞书 uuid 1 小时去重窗口）
- **`.last_run` 标记**：群消息全部发送成功后**立即**由脚本写入并 push，不等 workflow 收尾——即使后续步骤（Base/知识库）超时失败，当天也不会再推
- **飞书 uuid 去重**：同一天同一序号消息复用稳定 uuid，飞书端兜底
- **跨天去重**：多维表格存近 7 天历史（内容指纹 + 主题指纹），杜绝同一事件隔天重复推送

## 版本历史

| 版本 | 更新点 |
|------|--------|
| **v5.5** | 修复双推送与内容重复：推送成功后脚本内立即标记 `.last_run`；workflow 超时 30→60 分钟；修复 Base 日期字段格式（恢复历史写入）；摘要生成内容/主题指纹；跨批 LLM 语义合并（宁合不拆） |
| **v5.0** | 可靠性修复：双定时调整至 09:00/09:45；`.last_run` 改为 git 提交（不再依赖 cache）；消息 uuid 幂等；退出码状态机细化 |
| **v4.2 / v4.1** | 修复结构化飞书历史字段（链接/日期格式） |
| **v4.0** | 凭证安全加固（密钥全部走 Secrets）；失败退出码状态机；LLM 输出结构校验；单 CI 调度 + 七天跨天去重 |
| **v3.x** | 七分类改版（能源/芯片/基建/模型/应用/政策/安全）；新增官方媒体、研报来源；推送拆分（精选 + 政策安全）；多维表格归档回填 |
| **v2** | 双定时（09:30/11:30）兜底 + `.last_run` + Cache 幂等；多维表格留存精读记录 |
