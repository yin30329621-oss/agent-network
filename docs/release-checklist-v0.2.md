# Agent Network v0.2 Release Checklist

- [x] `uv run pytest`
- [x] `uv run ruff check .`
- [x] `uv run ruff format --check .`
- [x] API keys are not committed
- [x] `.env` is ignored
- [x] `outputs/` is ignored by default and should generally not be committed
- [x] `docs/release-v0.2.md` exists
- [x] `docs/baseline-v0.2-release-candidate.md` exists
- [x] version is `0.2.0`
- [x] default workflow preserves the four-call constraint
- [x] three real RC runs completed
- [x] Known Compatibility Note is documented

## Git Tag Preparation

Recommended tag:

```text
v0.2.0
```

Recommended commit message:

```text
Release Agent Network v0.2.0
```

## Notes

Do not commit `.env` or generated `outputs/runs` unless a maintainer explicitly
wants to publish sanitized sample outputs.
