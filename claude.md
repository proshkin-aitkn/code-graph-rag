# Claude Integration & Branch Maintenance Guide

This document explains how to use Claude with your Max subscription and maintain local customizations while tracking upstream updates.

## Branch Structure

```
upstream/main  →  vitali87/code-graph-rag (original repo)
       ↓
     main      →  tracks upstream/main
       ↓
    custom     →  your local customizations (rebase onto main)
```

| Branch | Purpose |
|--------|---------|
| `main` | Mirror of upstream, never commit directly |
| `custom` | Your local changes, rebased onto main when updating |

## Local Customizations on `custom` Branch

| Commit | Type | Will go upstream? |
|--------|------|-------------------|
| Claude CLI wrapper | LOCAL | No |
| semantic_search MCP tool | LOCAL | No |
| update_repository MCP tool | LOCAL | No |
| Anthropic provider (PR #285) | PR | Likely yes |

## Using Claude with Max Subscription

The Claude CLI wrapper exposes an OpenAI-compatible API that routes through your Max subscription.

### Start the wrapper

```bash
cd /home/proshkin/proj/code-graph-rag
.venv/bin/python claude_api_wrapper.py
```

The wrapper runs on `http://localhost:8000` and supports parallel requests.

### Configuration (.env)

```bash
# Claude via local CLI wrapper (uses Max subscription)
ORCHESTRATOR_PROVIDER=openai
ORCHESTRATOR_MODEL=claude-opus-4-5-20251101
ORCHESTRATOR_ENDPOINT=http://localhost:8000/v1
ORCHESTRATOR_API_KEY=dummy

CYPHER_PROVIDER=openai
CYPHER_MODEL=claude-sonnet-4-5-20250929
CYPHER_ENDPOINT=http://localhost:8000/v1
CYPHER_API_KEY=dummy
```

### Model Recommendations

| Role | Model | Reason |
|------|-------|--------|
| Orchestrator | Opus | Complex reasoning, multi-step planning |
| Cypher | Sonnet | Query generation is formulaic, faster |

## Updating from Upstream

### Regular Update (no conflicts expected)

```bash
# 1. Fetch and update main
git checkout main
git pull upstream main

# 2. Rebase custom onto updated main
git checkout custom
git rebase main

# 3. Force push custom (rebase rewrites history)
git push origin custom --force-with-lease
```

### When PR #285 Gets Merged Upstream

Once the Anthropic provider PR is merged into upstream, you'll have duplicate commits. Use interactive rebase to drop them:

```bash
# 1. Update main
git checkout main
git pull upstream main

# 2. Interactive rebase to drop PR #285 commits
git checkout custom
git rebase -i main

# 3. In the editor, delete (or mark 'd') these commits:
#    - feat: add Anthropic Claude provider support with flexible authentication
#    - fix: update codebase_rag/utils/claude_settings.py to create generic method
#    - fix: Update codebase_rag/config.py
#    - merge: add Anthropic Claude provider support from PR #285

# 4. Save and close editor, resolve any conflicts

# 5. Force push
git push origin custom --force-with-lease
```

### Handling Rebase Conflicts

If conflicts occur during rebase:

```bash
# 1. See which files have conflicts
git status

# 2. Edit conflicted files, then:
git add <resolved-files>
git rebase --continue

# 3. To abort and start over:
git rebase --abort
```

## Adding New Local Customizations

Always commit to `custom` branch:

```bash
git checkout custom
# make changes
git add <files>
git commit -m "feat: your new feature"
git push origin custom
```

## Checking Upstream for Updates

```bash
# See what's new in upstream
git fetch upstream
git log main..upstream/main --oneline

# See commits in custom that aren't in upstream
git log upstream/main..custom --oneline
```

## Quick Reference

| Task | Command |
|------|---------|
| Update from upstream | `git checkout main && git pull upstream main` |
| Rebase custom | `git checkout custom && git rebase main` |
| Push after rebase | `git push origin custom --force-with-lease` |
| Start Claude wrapper | `.venv/bin/python claude_api_wrapper.py` |
| Check upstream changes | `git fetch upstream && git log main..upstream/main --oneline` |
