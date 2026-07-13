# Agent Network v0.3 Phase 2A: Official CVE Evidence Sources

## 目标

Phase 2A 为 Evidence Verification 增加两个可替换的官方数据源：

- NVD CVE API
- GitHub Global Security Advisories API

它们继续实现 `search(claim) -> list[Evidence]`，不接入 Fact、Security、Logic、Merge，不调用 LLM，也不读取报告文件。真实网络只会在用户显式执行 `fetch-evidence` 时发生。

## NVD Source

`NvdEvidenceSource` 按 CVE ID 请求：

```text
https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=<CVE-ID>
```

Evidence 映射保留：

- CVE ID
- 英文原始 description 片段
- published / lastModified
- CVSS version、base score、severity、vector string
- references
- configurations / CPE affected data
- source identifier
- NVD 详情 URL
- API 响应 SHA-256

NVD 返回零条记录时 Source 返回空列表。空列表只表示没有取得 Evidence，不表示 CVE 不存在。

可选 `NVD_API_KEY` 通过 `apiKey` 请求头发送。缓存键和审计均排除该请求头。

## GitHub Advisory Source

`GitHubAdvisoryEvidenceSource` 按 CVE ID 请求 GitHub Global Security Advisories：

```text
https://api.github.com/advisories?cve_id=<CVE-ID>&per_page=100
```

Evidence 映射保留：

- CVE ID 与 GHSA ID
- severity
- CVSS score 与 vector
- CWE
- description
- published / updated
- ecosystem、package、vulnerable version range、first patched version
- references
- GitHub Advisory URL
- API 响应 SHA-256

未配置 `GITHUB_TOKEN` 时使用未认证请求，并从响应头记录 rate limit remaining/reset。配置 Token 时使用 Authorization Header，但 Token 不进入缓存键、审计、错误或输出。

## HTTP Client 抽象

`HttpTransport` 定义单次请求接口，生产实现使用标准库 `urllib`，测试注入 Fake Transport。`EvidenceHttpClient` 负责：

- HTTPS 和域名白名单
- 请求与重定向最终 URL 校验
- timeout
- 最小请求间隔
- 本地缓存
- ETag / Last-Modified 条件请求
- HTTP 状态和错误分类
- 脱敏 Source audit

统一审计字段：

- `source_name`
- `request_url`
- `request_started_at`
- `request_completed_at`
- `http_status`
- `cache_status`
- `etag`
- `last_modified`
- `response_hash`
- `retry_count`
- `error_type`
- `error_message`
- `rate_limit_remaining`
- `rate_limit_reset`

Phase 2A 不做自动 HTTP retry，`retry_count` 固定为 0，避免限流或服务错误被隐藏。

## 白名单策略

网络请求和重定向仅允许：

- `services.nvd.nist.gov`
- `nvd.nist.gov`
- `api.github.com`
- `github.com`

必须使用 HTTPS。初始 URL 或重定向最终 URL 不在白名单时，返回空结果并记录 `domain_not_allowed`。GitHub 未来若需要请求外部 reference，必须先单独扩展 Source policy，不能继承页面返回的任意 URL。

## 缓存策略

默认目录：

```text
.cache/agent-network/evidence/
  nvd/
    <cache-key>.json
    <cache-key>.body
  github_advisory/
    <cache-key>.json
    <cache-key>.body
```

`.cache/` 已加入 `.gitignore`。缓存键包括 Source、查询、请求 URL 和非敏感相关请求头，不包括 Authorization/API Key。

元数据保存：

- fetched/expires 时间
- ETag
- Last-Modified
- HTTP status
- response hash
- 原始响应相对路径

缓存状态：

| 状态 | 含义 |
| --- | --- |
| `miss` | 无缓存，执行请求并写入 |
| `hit` | 缓存有效，不发送网络请求 |
| `stale` | 缓存过期，重新请求并取得新内容 |
| `revalidated` | 缓存过期，条件请求返回 304，复用原响应 |

读取缓存时重新计算响应哈希；元数据与响应体不一致时视为无效缓存。

## 限流与错误处理

| 情况 | `error_type` | 行为 |
| --- | --- | --- |
| Timeout | `timeout` | 返回空 Evidence，保留审计 |
| HTTP 429 | `rate_limit` | 记录 rate limit 响应头，返回空 Evidence |
| HTTP 5xx | `server_error` | 返回空 Evidence |
| 非白名单 URL/Redirect | `domain_not_allowed` | 拒绝请求或响应 |
| 无效 JSON/映射失败 | `response_mapping_error` | 返回空 Evidence |
| 其他 HTTP 错误 | `http_error` | 返回空 Evidence |

Source 错误和“官方 API 没有记录”都会产生空 Evidence，但审计不同。后续集成必须结合 audit 将 Provider/Source 失败标记为 `insufficient_evidence`，不能把空 Evidence 当成 `contradicted`。

## CLI

NVD pilot：

```text
uv run agent-network fetch-evidence CVE-2022-45157 --source nvd --output outputs/evidence-pilot-nvd
```

GitHub Advisory pilot：

```text
uv run agent-network fetch-evidence CVE-2022-45157 --source github --output outputs/evidence-pilot-github
```

可选参数：

- `--cache .cache/agent-network/evidence`
- `--timeout 20`

每次命令只选择一个 Source，最多产生一次实际 HTTP 请求；cache hit 时为零次。输出包括：

- `evidence.json`
- `audit.json`
- `run.json`

`run.json` 明确记录 `network_request_count` 和 `model_call_count=0`。

## 安全边界

- Pilot 只接受格式正确的公开 CVE ID。
- 不读取任何 Markdown 报告或 `reports/private/`。
- 不加载或调用 LLM。
- 不记录请求头、Authorization、NVD API Key 或 GitHub Token。
- 不自动访问 API 返回的 reference URL。
- 原始 API 响应只进入被 Git 忽略的本地缓存。
- Source 只提供 Evidence，不作为 CVE 不存在性的最终 Judge。

## 测试策略

全部测试使用 Fake Transport，不访问真实网络。覆盖 NVD/GitHub 映射、空结果、timeout、429、500、白名单、重定向、缓存四状态、ETag、响应哈希、Token 脱敏、Schema 兼容和 CLI 输出。

CLI 测试将 `socket.socket` 替换为抛错实现，同时注入 Fake Transport，以证明测试期间没有真实网络访问。

## Phase 2B

下一阶段建议实现：

1. Rancher/SUSE Security Advisory Source。
2. Rancher Release Notes Source。
3. Advisory/Release 的版本范围确定性比较。
4. Source 失败与“无记录”的聚合状态模型。
5. 官方页面快照、canonical URL 和内容清洗审计。

Phase 2B 仍应独立于四 Agent workflow；完成来源准确率和缓存稳定性验证后，再进入 Evidence-aware Agent 集成。
