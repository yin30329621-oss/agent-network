# Evaluation

## Scope

This evaluation compares the deterministic mock pipeline against the real
multi-provider pipeline for `reports/sample.md`.

## Commands

```powershell
uv run agent-network doctor
uv run agent-network review reports/sample.md --mode mock --output outputs/mock
uv run agent-network review reports/sample.md --mode real --output outputs/real
```

## Mock Result

Mock mode completed successfully and generated:

- `outputs/mock/review.md`
- `outputs/mock/review.json`

The mock baseline produced 4 findings:

| Agent | Severity | Location | Issue |
| --- | --- | --- | --- |
| fact | medium | Reliability Claim | RollingUpdate is described as guaranteeing zero downtime. |
| security | high | Summary | The application service account is granted cluster-admin access. |
| security | medium | Container Configuration | The container runs as root and lacks resource limits. |
| logic | medium | Container Configuration | Autoscaling is used as a reason to omit resource limits. |

## Real Provider Result

Real mode did not run in the current environment because required API keys are
not configured.

`agent-network doctor` reported:

| Agent | Provider | Model | API Key |
| --- | --- | --- | --- |
| fact | siliconflow | openai/deepseek-ai/DeepSeek-V3.2 | `SILICONFLOW_API_KEY` missing |
| security | siliconflow | openai/deepseek-ai/DeepSeek-R1 | `SILICONFLOW_API_KEY` missing |
| logic | siliconflow | openai/Pro/zai-org/GLM-4.7 | `SILICONFLOW_API_KEY` missing |
| merge | siliconflow | openai/deepseek-ai/DeepSeek-V3.2 | `SILICONFLOW_API_KEY` missing |

The real-mode command failed fast with:

```text
Missing API key for agent(s): fact, security, logic, merge
```

## Comparison

| Dimension | Mock | Real |
| --- | --- | --- |
| Runs without credentials | Yes | No |
| Deterministic | Yes | No |
| Uses provider models | No | Requires DeepSeek and ZAI keys |
| Suitable for tests | Yes | Only for opt-in integration runs |
| Suitable for production review | No | Yes, after credentials are configured |

## Next Real Run

Create `.env` from `.env.example` and set:

```text
SILICONFLOW_API_KEY should be set in `.env`
```

Then run:

```powershell
uv run agent-network doctor
uv run agent-network review reports/sample.md --mode real --output outputs/real
```
