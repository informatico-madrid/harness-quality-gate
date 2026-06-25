# Step 00: Install Tools (LLM-driven, no subcommand)

**Goal:** Ensure the tools required by the quality gate are available before
running any layer. The LLM is the installer — there is no `install-tools`
subcommand. This step is a guide for the agent, not a script.

**Why no subcommand?** The skill is consumed by an LLM agent (per
`specs/php-support/decisions.md` §1), not a human at a terminal. A
subcommand would couple the install logic to a single package manager and
a single fallback path. The agent reads the environment and picks the
right approach. If a strategy fails, the agent can try the next one.

## 0.8 Disambiguation — when multiple candidates exist

Some environments have a tool installed in more than one place:

- `.venv/bin/ruff` (project-local, version X)
- `/usr/local/bin/ruff` (system, version Y)
- `tools/bin/ruff` (custom company install)
- `vendor/bin/phpstan` (composer dep, PHP)

The LLM must NOT silently pick one. The skill exposes a structured API
for this — use it before asking the user.

### Detection (no install needed)

```python
# In the agent's Python execution, or via shell:
from harness_quality_gate.bootstrap import find_tool_candidates
candidates = find_tool_candidates("ruff", Path("/path/to/repo"))
for c in candidates:
    print(f"  {c.provenance:8s}  {c.path}")
# Example output:
#   .venv     /path/to/repo/.venv/bin/ruff
#   PATH      /usr/local/bin/ruff
```

Each candidate carries a **provenance** (`.venv`, `vendor`, `PATH`,
`override`) so the user knows *where* each option came from. The list
is ordered by precedence: override > .venv > vendor > PATH.

### Resolution rules

1. **The agent must present the candidates to the user** when more than
   one exists AND the user has not already configured an override
   (see §0.9). Ask explicitly which to use.
2. If the user picks one, persist the choice via the override
   mechanism (next section) so subsequent runs do not re-ask.
3. If the user does not pick (or there is only one), the agent
   continues with the highest-precedence candidate and logs the
   decision in the agent's conversation trace.

### Inspecting exception `tried` list

When `resolve_tool(name, repo)` raises `ToolNotAvailable`, the exception
exposes `exc.tried` — the ordered list of paths the LLM should have
considered. Use it to give the user a complete picture, not just the
first failure:

```python
from harness_quality_gate.bootstrap import resolve_tool, ToolNotAvailable
try:
    resolve_tool("ruff", Path("/path/to/repo"))
except ToolNotAvailable as exc:
    print(f"ruff not found. Looked in:")
    for p in exc.tried:
        print(f"  {p}")
```

### What NOT to do

- Do not assume the highest-precedence candidate is the right one. The
  user may prefer a system-wide install (e.g., the corp-mandated
  version) over a stale venv.
- Do not skip candidates silently. If the user wants `PATH` and we
  picked `.venv`, the user will be confused later.
- Do not write code that "always uses `.venv`" — that breaks the
  moment the user installs a tool elsewhere.

---

## 0.9 Persistent overrides — `_quality-gate/quality-gate.yaml`

For choices the user wants to persist across runs, write to
`_quality-gate/quality-gate.yaml` in the project (or in
`~/.config/harness-quality-gate/config.yaml` for user-global):

```yaml
schema_version: 2

tool_overrides:
  python:
    ruff: /opt/company/bin/ruff        # absolute
    pyright: vendor/python/pyright     # relative to repo root
  php:
    infection: vendor/bin/infection   # composer's default location
```

The schema is **language → tool_name → path string**:

- `path` may be absolute or relative to the repo root (resolved by
  `resolve_tool`).
- A path that does not exist or is not executable is silently
  dropped — the LLM will fall through to other candidates and can
  surface the issue via the `tried` list.

The CLI / adapters consume overrides transparently: the LLM loads
the config and passes `preferred=cfg.get_tool_override("python", "ruff")`
to `resolve_tool`. See `harness_quality_gate/config.py` and
`harness_quality_gate/bootstrap.py` for the public API.

---

## 0.1 Detect the environment

```bash
# Python interpreter and venv
{project-root}/.venv/bin/python --version 2>/dev/null || python3 --version

# Package managers
which uv 2>/dev/null && echo "uv=YES"
which pip 2>/dev/null && echo "pip=YES"
which pipx 2>/dev/null && echo "pipx=YES"
which npm 2>/dev/null && echo "npm=YES"
which composer 2>/dev/null && echo "composer=YES"

# OS family (for system packages)
uname -s   # Linux / Darwin

# Linux distro (Debian / RHEL / Arch family)
[ -f /etc/debian_version ] && echo "distro=debian"
[ -f /etc/redhat-release ] && echo "distro=rhel"
[ -f /etc/arch-release ]   && echo "distro=arch"
```

The agent uses the result of §0.1 to pick the strategy in §0.3. Do not
hard-code it.

---

## 0.2 Required tools by layer

| Layer | Python | PHP |
|-------|--------|-----|
| L3A   | `ruff`, `pyright` | `phpstan`, `phpmd`, `php-cs-fixer` |
| L1    | `pytest`, `mutmut` | `phpunit`/`pest`, `infection` (MSI 100/100) |
| L2    | (reuses L1) | (reuses L1) |
| L3B   | (uses L3A; Tier B is LLM-driven via `steps/step-04-layer3b*.md`) | `deptrac` (architecture) |
| L4    | `bandit`, `safety`/`pip-audit`, `gitleaks`, `semgrep`, `checkov`, `deptry`, `vulture`, `trivy` | `psalm --taint-analysis`, `composer audit`, `local-php-security-checker`, `shipmonk/dead-code-detector`, `shipmonk/composer-dependency-analyser` |

Tool priority (per `references/security-tools-guide.md`):
- **REQUIRED** — must install. Missing required tool blocks the gate.
- **RECOMMENDED** — install if possible. Missing recommended tool is a
  WARNING, not a failure.
- **OPTIONAL** — never blocks the gate.

Per-language REQUIRED set:
- **Python**: `ruff`, `pyright`, `pytest`, `mutmut` (L1 mutation hard gate),
  `bandit`, `safety`, `gitleaks`.
- **PHP**: `php`, `phpunit`/`pest`, `phpstan`, `infection` (L1 MSI 100/100
  hard gate), `composer audit`. Missing any of these produces exit 3
  (`INFRA_INCOMPLETE`) per `cli._missing_php_tools()`.

---

## 0.3 Install strategies (agent picks based on §0.1)

### Python — prefer project venv if present

```bash
# Detect venv
if [ -d "{project-root}/.venv" ]; then
  PY="{project-root}/.venv/bin/python"
else
  PY="python3"
fi

# Strategy 1: uv (fastest, falls back gracefully)
if command -v uv >/dev/null 2>&1 && [ -d "{project-root}/.venv" ]; then
  uv pip install --python "$PY" \
    ruff pyright pytest pytest-cov mutmut \
    bandit safety semgrep checkov deptry vulture
# Strategy 2: pip
elif "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m pip install \
    ruff pyright pytest pytest-cov mutmut \
    bandit safety semgrep checkov deptry vulture
# Strategy 3: pipx (system-wide, no venv needed)
elif command -v pipx >/dev/null 2>&1; then
  for tool in ruff bandit safety semgrep checkov deptry vulture; do
    pipx install "$tool" 2>/dev/null || true
  done
  # pytest and pyright need a venv — fall through to system install
  "$PY" -m pip install --user pytest pytest-cov mutmut || \
    sudo apt install -y python3-pytest
fi
```

### Python — tools NOT in PyPI

```bash
# pyright is npm-only.
if command -v npm >/dev/null 2>&1; then
  npm install -g pyright
else
  # Last resort: download the wheel from GitHub releases
  echo "WARN: pyright is npm-only; install Node.js or use npx"
fi
```

### PHP — composer is the entry point

```bash
cd {project-root}
if [ -f composer.json ]; then
  # Strategy 1: composer require (preferred)
  if command -v composer >/dev/null 2>&1; then
    composer require --dev \
      phpstan/phpstan phpunit/phpunit infection/infection
    # Recommended (optional but encouraged)
    composer require --dev \
      phpmd/phpmd friendsofphp/php-cs-fixer deptrac/deptrac vimeo/psalm \
      || true   # don't fail the install on a recommended-only tool
  else
    # Strategy 2: install composer first
    EXPECTED_CHECKSUM="$(curl -sS https://composer.github.io/installer.sig)"
    php -r "copy('https://getcomposer.org/installer.php', 'composer-setup.php');"
    php -r "if (hash_file('sha384', 'composer-setup.php') === '$EXPECTED_CHECKSUM') { echo 'Installer verified'; } else { echo 'Installer corrupt'; unlink('composer-setup.php'); } echo PHP_EOL;"
    php composer-setup.php --install-dir=/usr/local/bin --filename=composer
    php -r "unlink('composer-setup.php');"
  fi
fi
```

If `php` is not on PATH, the agent must surface this as a blocking
finding — the PHP path cannot proceed without it (per
`cli._missing_php_tools()` exit 3 contract).

### System packages (only if pip/composer cannot be used)

```bash
# Debian / Ubuntu
if [ -f /etc/debian_version ]; then
  sudo apt install -y python3-pytest python3-pyright bandit vulture
  sudo apt install -y gitleaks trivy   # security tools
fi

# macOS
if [ "$(uname -s)" = "Darwin" ]; then
  brew install gitleaks semgrep checkov trivy
  brew install pyright                  # not in PyPI
fi
```

---

## 0.4 Verify availability

After installing, re-run the verification block in
`steps/step-01-init.md` §1.5. For each missing tool:

1. **REQUIRED tool missing** → the agent must fix it before proceeding
   (try another strategy from §0.3, or surface as a blocking finding).
2. **RECOMMENDED tool missing** → the agent may proceed with a WARNING
   (the layer is degraded but not blocked).
3. **OPTIONAL tool missing** → the agent proceeds without it.

Per `specs/php-support/decisions.md` §2, Python keeps its
graceful-degradation behaviour (skip + warning, never exit 3). PHP exits
3 with a `missing_tools` list if any critical tool is absent.

---

## 0.5 Do not silently fall back

- Do not skip a REQUIRED tool and continue.
- Do not pretend a tool is installed when it is not.
- Do not invoke a layer whose REQUIRED dependencies are missing.
- If installation genuinely fails after exhausting §0.3, surface the
  failure as a blocking finding for the human to resolve.

---

## 0.6 Next step

When all REQUIRED tools are present, proceed to
`steps/step-01-init.md`. The PYTHON_RUNNER resolution in step-01 §1.5.5
depends on whether a `.venv/` exists and whether the tools are visible
from that interpreter.

---

## 0.7 References

- `references/security-tools-guide.md` — language-agnostic index
- `references/security-tools-guide-python.md` — Python installation & remediation
- `references/security-tools-guide-php.md` — PHP installation & remediation
- `references/pentest-remediation-index.md` — post-fix validation commands
