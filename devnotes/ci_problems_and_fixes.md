# CI problems and fixes (October 2026)

What broke in this repo's GitHub CI after the copier template update, why it broke, and how each problem was fixed. It starts with how the CI is put together, because every problem only makes sense once you know that.

Fixes are in commits `7e4b70c` and `ce61325` on branch `4_copier_template`.

## How the CI is put together

There are four layers, each one calling the next:

```
.github/workflows/ci.yml         when CI runs, and which jobs
  └─ .github/workflows/_*.yml    what each job does (reusable workflows)
       └─ tox                    named environments defined in pyproject.toml
            └─ uv + uv.lock      installs the exact package versions
```

### 1. `ci.yml`: the entry point

GitHub runs every file in `.github/workflows/`, but only the `on:` section decides *when*:

```yaml
on:
  push:
    branches:
      - main        # pushes to main
    tags:
      - '*'         # any pushed tag (a release)
  pull_request:     # any PR
  workflow_dispatch:  # the "Run workflow" button / gh workflow run
```

`jobs:` lists the jobs. Each one just calls a reusable workflow with `uses: ./.github/workflows/_something.yml`. Jobs run in parallel unless `needs:` makes one wait for another. `if:` can skip a job; for example `release` only runs on tags.

| Job | File | What it does |
|---|---|---|
| `lint` | `_tox.yml` | `tox -e pre-commit,type-checking`: ruff and other pre-commit hooks, then pyright |
| `test` | `_test.yml` | `tox -e tests` (pytest with coverage) on Python 3.11, 3.12, 3.13 and 3.14 (a `matrix`: one job per version) |
| `container` | `_container.yml` | Builds the Docker image from `Dockerfile` and runs `--version` in it; pushes to `ghcr.io` on tags |
| `docs` | `_docs.yml` | Builds the Sphinx docs (`tox -e docs`) and publishes them to GitHub Pages from `main` and tags |
| `dist` | `_dist.yml` | Builds the sdist and wheel, checks them with `twine`, installs the wheel and runs `--version` |
| `pypi` | `_pypi.yml` | Tags only: uploads the `dist` output to PyPI |
| `release` | `_release.yml` | Tags only: creates a GitHub Release with the packages and zipped docs |

### 2. `_*.yml`: reusable workflows

Files starting with `_` have `on: workflow_call`, so they never run by themselves; they only run when `ci.yml` (or `periodic.yml`) calls them. Each is a list of steps on a fresh Ubuntu machine: check out the code, install `uv`, run one command. `fetch-depth: 0` in the checkout gets the full git history, which `setuptools_scm` needs to work out the version number from the latest tag.

### 3. tox environments

`tox -e tests` doesn't mean much until you look in `pyproject.toml` under `[tool.tox.env.tests]`: that's where the actual `pytest --cov=...` command is. Same for `pre-commit`, `type-checking` and `docs`. This lets you run exactly what CI runs on your own machine, e.g. `uv run tox -e tests`.

### 4. `uv` and `uv.lock`

Every job runs `uv run --locked ...`. `--locked` means: use `uv.lock` exactly, and **fail** if it doesn't match `pyproject.toml` rather than quietly updating it. That makes CI reproducible, but it also means a wrong or stale `uv.lock` breaks every job at once.

### The Dockerfile

The image is built in three stages; each `FROM ... AS name` starts one:

| Stage | Based on | What happens |
|---|---|---|
| `developer` | epics-base developer image | Adds system packages (graphviz) |
| `build` | `developer` | `COPY . /app`, then `uv sync --locked --no-editable --no-dev` builds and installs `fastcs-gatan` into `/app/.venv` |
| `runtime` | smaller epics-base runtime image | Copies just the Python install and `.venv` from `build`; the entry point is `fastcs-gatan` |

Docker builds up to the stage named by `--target`, or all of them (ending with the last) if there's no `--target`. Remember this; it explains problem 1.

## Problem 1: container build failed in CI but worked locally

**Symptom:** the `container` job failed at `uv sync --locked --no-editable --no-dev` with "Failed to build `fastcs-gatan`". The real error was at the very end of the output, below several long setuptools deprecation warnings (those were harmless):

```
error: could not create 'build/lib/fastcs_gatan': Not a directory
```

**Cause:** the repo had a shell script called `build` (the epics-containers local build script) in its root. `COPY . /app` put it at `/app/build`. To build a wheel, setuptools writes its output into a *directory* called `build/`, and it can't create `build/lib/...` when `build` is already a *file*.

**Why it worked locally:** the `build` script defaults to `--target developer`, so Docker stopped after the first stage and never ran `uv sync`. CI uses no `--target`, so it builds all three stages. Running the script with `TARGET=runtime` would have shown the same failure locally.

**Fix:** renamed the script to `build.sh`. It also stops clashing with the `build/` entry in `.gitignore` and with the docs job, which builds into `build/html`.

**Lesson:** when local and CI results differ, compare *exactly* what each one runs: same Dockerfile, but different target, different files in the build context, different Python version.

## Problem 2: the copier template wiped the dependencies

**Symptom:** found while investigating; it would have broken every job on this branch.

**Cause:** applying the copier template replaced `pyproject.toml` sections with template defaults:

- `dependencies = []` (was `fastcs[epicsca]` and `numpy`)
- dev dependencies lost `pytest-asyncio` (needed for the `@pytest.mark.asyncio` tests), plus `copier` and `pytest-mock` (not used)
- `uv.lock` became a 3-line empty file

With `--locked`, `uv` refused to run: "The lockfile at `uv.lock` needs to be updated".

**Fix:** added back `fastcs[epicsca]`, `numpy` and `pytest-asyncio`, then ran `uv sync`, which re-resolved the dependencies and rewrote `uv.lock`.

**Lesson:** after a template update, check `git diff` on `pyproject.toml`, `uv.lock` and any `src/` files the template touched (here `__init__.py` and `__main__.py`) before anything else. A template knows nothing about your project.

## Problem 3: the template removed the container jobs

**Cause:** the template's `ci.yml` has no `container`, `debug_container` or `pypi` jobs, so on this branch the image would never be built at all. Their `_*.yml` files were still there, just not called.

**Fix:** added `container` and `pypi` back to `ci.yml`. Removed `debug_container` and its `_debug_container.yml`: it builds `--target debug`, and the Dockerfile has no `debug` stage. It only ran on tags, so it had never failed visibly, but it would have failed on the first release.

## Problem 4: CI didn't run on the branch

**Cause:** the `on:` section only covers pushes to `main`, tags and pull requests. A push to any other branch triggers nothing.

**Fix:** added `workflow_dispatch:`, which allows manual runs: `gh workflow run ci.yml --ref 4_copier_template`, or the "Run workflow" button on the Actions tab. GitHub only shows that button once the `main` branch's copy of the workflow has `workflow_dispatch`. Opening a pull request also runs CI, and re-runs it on every push to the branch.

## Problem 5: tests failed on Python 3.14 only

**Symptom:** test collection errors, only in the 3.14 job:

```
DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated and slated for removal in Python 3.16; use inspect.iscoroutinefunction() instead
```

**Cause:** the deprecated call is in `fastcs` (`fastcs/methods/method.py`), not in this repo; it runs whenever `@command` or `@scan` decorates a method, so the warning appears as soon as a controller module is imported. Python 3.14 deprecated the function; the template added 3.14 to the test matrix. On its own this would only print a warning, but `pyproject.toml` has:

```toml
[tool.pytest.ini_options]
filterwarnings = "error"
```

which turns every warning into a failure. That's deliberate: it surfaces deprecations early, like this one.

**Fix:** ignore just this one warning, keep everything else an error:

```toml
filterwarnings = [
    "error",
    # fastcs 0.14.4 still uses this on Python 3.14; drop once fastcs is fixed
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
]
```

The real fix belongs in `fastcs`; `devnotes/fastcs_issue_iscoroutinefunction.md` is a ready-made issue for it.

**Lesson:** read where a warning *comes from* (the file path in the traceback), not just what it says. The suggested fix may apply to someone else's code.

## Side note: `uv` and your venv in this devcontainer

The devcontainer sets `UV_PROJECT_ENVIRONMENT` to a shared venv under `/cache/venv-for/...`. That means `uv sync` in **any** folder, even a throwaway clone, installs into that one venv. Running the Docker step (`uv sync --no-dev --no-editable`) in a scratch clone once removed all the dev tools from it. `uv sync` in `/workspaces/fastcs-gatan` restores it. To try a CI step without touching the venv, point it somewhere else:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/ci-venv uv sync --locked --no-editable --no-dev
```

## Reproducing CI steps locally

| CI job | Local command |
|---|---|
| `test` on 3.14 | `UV_PROJECT_ENVIRONMENT=/tmp/venv314 uv run --python 3.14 --locked tox -e tests` |
| `lint` | `uv run --locked tox -e pre-commit,type-checking` |
| `docs` | `uv run --locked tox -e docs` |
| `container` | `docker build -t test .` then `docker run --rm test --version` (no `--target`, like CI) |
| lock file in sync? | `uv lock --check` |

## Still open

- **PyPI upload** (`pypi` job, tags only) needs a trusted publisher set up on PyPI for this repo, and a GitHub environment called `release` (the job uses `environment: release`).
- **`fastcs` issue** for the deprecation: drop the `filterwarnings` ignore once fixed.
- **Launcher (fixed, not yet committed):** the template had replaced `src/fastcs_gatan/__main__.py` with its stub, an `argparse` parser that only knew `--version`, so the driver couldn't be started (CI still passed, because CI only checks `--version`). Restored from `main`, so `schema` and `run <config.yaml>` work again; the template's `tests/test_cli.py` was updated to expect the launcher's `GatanController: <version>` output.
- The template also removed `fallback_version = "0.0.0"` from `[tool.setuptools_scm]`. CI checks out the full history, so it isn't needed there, but builds without git history (e.g. from a downloaded zip) will now fail to find a version.
