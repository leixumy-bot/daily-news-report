# 踩坑记录 / Troubleshooting

本文件记录 v3.x ~ v5.x 改造过程中踩过的坑、根因和解决方案，供后续维护参考。

## 1. LLM 聚类超时：200+ 条一次喂给 LLM 必失败

- **症状**：`dedup-cluster: LLM Stage 1 JSON parse failed (raw len=0), retrying...`，重试也失败，最终走 fallback，产出全是「其他/新闻」噪音簇。
- **原因**：单次聚类输入 200+ 条时，DeepSeek 生成超时/截断。关键词补政策/安全语义后，候选项从 ~80 条涨到 ~220 条，触发了此问题。
- **解决**：`processors/dedup_cluster.py` 分批聚类（`BATCH_SIZE = 30`），跨批按 topic 去重。snippet 截 80 字（`body[:80]`）控制输入体积。

## 2. 官方源无条件豁免 → 无关政府新闻灌入

- **症状**：官方媒体采集器抓到「全民健身计划」「健康中国」等无关内容。
- **原因**：`keyword_filter` 曾对 `官方/` 前缀源无条件放行。
- **解决**：官方源改用 `config.json.keywords.official_include` 专属宽松词过滤（AI/数据/算力/监管等），普通源用 `include`。抓不相关的政府新闻会被滤掉，聚类阶段的严格过滤再兜底。

## 3. 关键词白名单缺「政策/安全」语义

- **症状**：官方媒体采集的政策新闻、安全风险事件在关键词过滤阶段被误杀。
- **原因**：原 `keywords.include` 全是技术/产品词（AI、大模型、算力…），无监管/安全词。
- **解决**：`include` 补充政策词（网信办/监管/备案/数据出境/个人信息保护…）和安全词（对抗样本/deepfake/深度伪造/AI安全…）。注意：裸宽泛安全词（泄露/黑客/诈骗）会海量召回无关内容，已从 include 移除，靠官方源专属词 + 聚类兜底。

## 4. 工信部全站 JS 化，无法静态采集

- **症状**：`miit.gov.cn` 各栏目返回 HTTP 200 但正文链接为 0（JS 动态渲染）。
- **解决**：从官方采集器移除工信部，改用 `site:miit.gov.cn` 加入 web_search 白名单搜索覆盖。效果接近但非实时一手。其他政府站（网信办/发改委/国家数据局/gov.cn）可静态抓取。

## 5. 政府站 GBK 编码乱码

- **症状**：部分政府站列表页中文乱码。
- **解决**：`collectors/official_media.py` 先读 `meta charset` 声明解码，失败依次回退 utf-8/gbk。

## 6. 飞书应用需开通多维表格权限

- **症状**：CI 里表格归档报 `Access denied. One of the following scopes is required: [bitable:app, bitable:app:readonly, base:record:retrieve]`，`Base write done: 0 inserted`。
- **原因**：飞书应用未开通 bitable API 权限。
- **解决**：飞书开放平台 → 应用 → 权限管理，添加 `bitable:app`（含 base:record:create / base:record:update），发布新版本。

## 7. CI 幂等保护会跳过手动触发

- **症状**：`workflow_dispatch` 手动触发回填/补跑时被 `✅ 今日日报已于 X 完成，跳过本次触发` 拦截，任务 12 秒结束。
- **原因**：`.last_run` 幂等保护判断"今天已跑过"。
- **解决**：手动触发必须同时勾选 `force`（`-f force=true`），backfill 同理需带 force。

## 8. 本地时区与 BJT 日期差一天

- **症状**：本地产物文件名带「下一天」日期，排查半天找不到。
- **原因**：本机 macOS 时区为 +05，日报按 BJT(+08) 算日期；本地 21:00 后等于 BJT 次日凌晨。
- **解决**：非问题，属正常现象。涉及日报日期时按 BJT 判断（`date -u` 前先 `TZ=Asia/Shanghai date`）。

## 9. 飞书消息长度上限

- **症状**：单条消息超长被拒收。
- **解决**：`processors/format.py` 的 `split_markdown_by_bytes` 按分类 block 边界按字节切分（`feishu.max_post_bytes: 28000`，为 JSON 结构膨胀留余量），单 block 超限再按段落原子切。消息1（五层）+ 消息2（政策/安全/其他/研报）各自独立切分，切多条均正常。

## 10. CI 里 git push 报 403

- **症状**：workflow 的 "Mark today as completed" 步骤 `git push` 报 403。
- **原因**：Actions token 无仓库写权限。需在 workflow 的 job 上声明 `permissions: contents: write`（v4.0 已加）。
- **影响**：push 失败仅告警，非致命——`.last_run` 幂等标志由脚本内 git 提交承载，workflow 收尾步骤的 push 只是兜底。

## 11. 跨天去重失效：Base 历史记录写不进去（DatetimeFieldConvFail）

- **症状**：`feishu-base: Failed to insert record for '...': DatetimeFieldConvFail`，`Base write done: 0 inserted`；跨天去重只剩残缺历史，同一事件隔天重复推送。
- **原因**：v4.0 把 `_date_timestamp_bjt` 从"秒级时间戳"（`int(time.mktime(...))`）误改成字符串 `"YYYY-MM-DD 00:00:00"`。多维表格**日期**字段只接受时间戳，字符串被拒。此 bug 从 v4.0 起一直静默存在（08-07 起 0 inserted），直到 08-09 追查内容重复才定位。
- **解决**：`output/feishu_base.py` `_date_timestamp_bjt` 改回 BJT 秒级时间戳（`datetime.strptime(...).replace(tzinfo=BJT).timestamp()`），v5.5 修复。注意：修复后**新**记录才带指纹，旧记录（v4.0 前）无指纹字段，跨天去重靠 URL 匹配 + LLM 语义判断兜底，需数天累积才完全恢复。

## 12. 飞书 uuid 去重窗口是 1 小时

- **症状**：双定时两次 run 都推送了消息（今天 2 条 + 3 条），uuid 去重没拦住。
- **原因**：飞书规则是"相同 uuid 在 **1 小时内**至多发送一条"。两次 run 间隔 >1 小时时 uuid 去重失效；且 v5.0 的 uuid 基于消息内容 sha256，两次内容不同 → uuid 不同 → 去重必然失效。
- **解决**：根治靠"推送成功后脚本内立即写 `.last_run`"（v5.5），把"推了"和"标记完成"绑死；保底 cron 09:45 与主推 09:00 间隔 45 分钟（< 1 小时），落在 uuid 去重窗口内。uuid 内容摘要设计本身不再作为去重主依赖。

## 13. 同一新闻跨渠道重复：跨批只做"完全一致"去重

- **症状**：同一天报告里，同一事件（多家公众号/站点报道）重复出现；`LLM Stage 1: 71 → 70`（只去掉 1 个）。
- **原因**：`run_dedup_cluster` 分批（30 条/批）LLM 聚类后，跨批只按"topic 完全一致 / URL 完全一致"确定性去重。同一事件不同渠道标题措辞不同、URL 不同，两规则都不命中 → 不合并。
- **解决**：v5.5 新增跨批 LLM 语义合并（`_semantic_merge_clusters`）：n-gram 相似度预筛候选对（阈值 0.15，上限 120 对防超时）→ LLM 判断是否同一事件 → 合并。LLM 失败时安全降级不合并。

## 14. 双定时并行 run：主推成功后 job 才被杀 → 重复推送

- **症状**：09:00 主 run 推送成功后，job 在 Base/知识库收尾阶段撞超时被杀 → job 失败 → `.last_run` 没写 → 09:45 保底误判"今天没推"又推一遍。
- **原因**：`.last_run` 只在 workflow 末尾 "Mark today as completed"（条件是整个 job `success()`）才写；从"消息推送成功"到"job 收尾"之间存在窗口，此窗口内 job 挂掉就丢标记。v5.0 把双定时间隔缩到 45 分钟但超时仍是 30 分钟，而 LLM 阶段耗时增长（今天聚类 19 分钟 + 多次 retry），正好踩雷。
- **解决**：v5.5 双保险——① 脚本内消息全部发送成功后**立即**写 `.last_run` 并 push（`daily_report.py _mark_done_in_ci`），不等 workflow 收尾；② `timeout-minutes` 30 → 60 给足运行时长。
