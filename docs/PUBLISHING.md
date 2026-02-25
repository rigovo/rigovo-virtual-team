# Publishing Rigovo to PyPI — Step-by-Step Guide

This guide walks you through setting up automated publishing to PyPI using GitHub Actions, python-semantic-release, and PyPI Trusted Publishing (no API keys needed).

## Prerequisites

- GitHub repository: `github.com/rigovo/rigovo-virtual-team`
- PyPI account: https://pypi.org (your account: `erashu212`)
- TestPyPI account: https://test.pypi.org (same credentials work)

---

## Step 1: Create the PyPI Project

### Option A: First-time manual upload (recommended)

Build and upload once manually to "claim" the package name:

```bash
cd rigovo-virtual-team/cli

# Build
pip install build twine
python -m build

# Upload to TestPyPI first
twine upload --repository testpypi dist/*
# Username: erashu212
# Password: your TestPyPI API token

# Verify it works
pip install --index-url https://test.pypi.org/simple/ rigovo

# Upload to real PyPI
twine upload dist/*
# Username: erashu212
# Password: your PyPI API token
```

### Option B: Create an API token

1. Go to https://pypi.org/manage/account/token/
2. Create token → scope: "Entire account" (first time) or project-scoped after first upload
3. Save the token (starts with `pypi-`)

---

## Step 2: Set Up Trusted Publishing (OIDC)

This is the industry-standard way — no API tokens stored in GitHub Secrets.

### On PyPI:

1. Go to https://pypi.org/manage/project/rigovo/settings/publishing/
   - (If project doesn't exist yet, go to https://pypi.org/manage/account/publishing/ to set up a "pending publisher")
2. Add a new publisher:
   - **Owner**: `rigovo` (your GitHub org or username)
   - **Repository**: `rigovo-virtual-team`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
3. Click "Add"

### On TestPyPI:

1. Go to https://test.pypi.org/manage/project/rigovo/settings/publishing/
   - (Or https://test.pypi.org/manage/account/publishing/ for pending publisher)
2. Add a new publisher:
   - **Owner**: `rigovo`
   - **Repository**: `rigovo-virtual-team`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `testpypi`
3. Click "Add"

---

## Step 3: Configure GitHub Environments

1. Go to your repo → Settings → Environments
2. Create environment: **`pypi`**
   - Optional: Add deployment protection rules (require reviewer approval)
   - Optional: Restrict to `main` branch only
3. Create environment: **`testpypi`**
   - Same optional protections

No secrets needed — Trusted Publishing handles authentication via OIDC tokens.

---

## Step 4: Push and Verify CI

```bash
git add .
git commit -m "ci: add GitHub Actions CI/CD and semantic-release"
git push origin main
```

The CI workflow (`.github/workflows/ci.yml`) will run:
- Tests across Python 3.10, 3.11, 3.12, 3.13
- Ruff lint + format check
- Rigour quality gates
- Build verification

---

## Step 5: Your First Automated Release

The publish workflow triggers on every push to `main`. It uses [python-semantic-release](https://python-semantic-release.readthedocs.io/) to:

1. Analyze commit messages since last release
2. Determine version bump (major/minor/patch) based on Conventional Commits
3. Update version in `pyproject.toml`
4. Generate/update `CHANGELOG.md`
5. Create a git tag (`v0.2.0`)
6. Build wheel + sdist
7. Publish to TestPyPI → PyPI
8. Create GitHub Release with assets

### Commit message format:

```bash
# Patch release (0.1.0 → 0.1.1)
git commit -m "fix: correct budget overflow in execute_agent"

# Minor release (0.1.0 → 0.2.0)
git commit -m "feat: add Groq LLM provider support"

# Major release (0.1.0 → 1.0.0) — breaking change
git commit -m "feat!: redesign pipeline state schema"

# No release (these don't trigger version bumps)
git commit -m "docs: update README"
git commit -m "chore: clean up unused imports"
git commit -m "ci: fix test matrix"
git commit -m "test: add edge case for budget limits"
```

---

## Step 6: Verify the Release

After a `feat:` or `fix:` commit is pushed to main:

1. Check GitHub Actions → "Release & Publish" workflow
2. Verify TestPyPI: https://test.pypi.org/project/rigovo/
3. Verify PyPI: https://pypi.org/project/rigovo/
4. Verify installation:

```bash
pip install rigovo
rigovo version
```

---

## How End Users Install

Once published, users install with a single command:

```bash
pip install rigovo
```

Then:

```bash
cd their-project
rigovo init
rigovo doctor
rigovo run "Build the feature"
```

Optional extras:

```bash
pip install rigovo[embeddings]    # Semantic memory with sentence-transformers
pip install rigovo[groq]          # Groq LLM provider
```

---

## Ongoing Release Workflow

```
Developer writes code
    ↓
Commits with Conventional Commits (feat:, fix:, etc.)
    ↓
Push to main (or merge PR)
    ↓
CI runs tests + Rigour gates
    ↓
semantic-release analyzes commits
    ↓
Version bumped → CHANGELOG updated → Tag created
    ↓
Published: TestPyPI → PyPI → GitHub Release
    ↓
Users get update: pip install --upgrade rigovo
```

---

## Troubleshooting

**"Package name already exists"** — Someone else claimed `rigovo` on PyPI. Use `rigovo-virtual-team` instead and update `pyproject.toml`.

**"Trusted publisher not configured"** — Go to PyPI project settings → Publishing and add the GitHub publisher. Make sure workflow name matches exactly: `publish.yml`.

**"Environment not found"** — Create `pypi` and `testpypi` environments in GitHub repo settings → Environments.

**"No new version"** — semantic-release only bumps version for `feat:` and `fix:` prefixed commits. Commits like `docs:`, `chore:`, `ci:` don't trigger releases.

**"GITHUB_TOKEN permissions"** — The workflow has `contents: write` permission. If using a protected branch, you may need a PAT instead of `GITHUB_TOKEN`.
