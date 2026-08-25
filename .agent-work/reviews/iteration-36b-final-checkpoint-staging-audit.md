# Iteration 36B — Final Checkpoint & Staging Audit

## Verdict

**B — hunk-level staging required.**

The accepted Iterations 32A–37B are reconstructable from the current source,
tests, and review artifacts, but whole-file staging is not safe. `constants.py`,
`syscheck.py`, and `test_syscheck.py` contain hunks owned by several iterations;
the new `diagnostic_rules.py` also contains the Iteration 33 extraction and the
later PCIe/NVMe rule additions. `syscheck.py` additionally has an unowned mode
change (`100755 -> 100644`). `AGENTS.md` is a separate workflow-policy change.

No staging, commit, history, branch, remote, cleanup, or source/test change was
performed for this audit. The index was empty at the checkpoint.

## Checkpoint

- Repository: `<REDACTED-PATH>`
- Branch: `master`
- `HEAD`: `2385be1` (`chore: add NeuralEngine agent guidance`)
- `origin/master`: `2385be1`
- Baseline and final full suite: **594 passing tests**
- Current staged paths: none (`git diff --cached --quiet` passed)
- Current tracked worktree diff: 4 files, 1,342 insertions and 1,184 deletions
- Current tracked binary diff SHA-256: `e6b2968a35a7a6585c2834ce65bd8844a9b76e22544351860f7bb73db2f2b`

The hash above covers the current tracked worktree diff, including the mode
change. It is not a proposed commit hash and does not include untracked files.

## Inventory

### Tracked paths (24)

```text
.agent-work/reviews/deepseek-v4-flash-max-amdgpu-reset-failure-diagnostic-assessment.md
.agent-work/reviews/deepseek-v4-flash-max-evidence-payload-vs-firewall-assessment.md
.agent-work/reviews/deepseek-v4-flash-max-existing-data-activation-implementation-plan.md
.agent-work/reviews/deepseek-v4-flash-max-gpu-graphics-kernel-log-diagnostics-assessment.md
.agent-work/reviews/deepseek-v4-flash-max-nvidia-xid-diagnostic-feasibility-assessment.md
.agent-work/reviews/deepseek-v4-flash-max-oom-evidence-diagnostic-feasibility-assessment.md
.agent-work/reviews/deepseek-v4-flash-max-sensors-temperature-diagnostics-assessment.md
.agent-work/reviews/deepseek-v4-flash-max-zram-ram-pressure-diagnostics-assessment.md
.agent-work/reviews/iteration-24-collector-path-test-hardening.md
.agent-work/reviews/iteration-24-evidence-payload-integrity-hardening.md
.agent-work/reviews/iteration-25-precise-kernel-taint-detection.md
.agent-work/reviews/iteration-26-remove-misleading-temperature-warning.md
.agent-work/reviews/iteration-27-kernel-oom-evidence-diagnostic.md
.agent-work/reviews/iteration-28-i915-gpu-hang-diagnostic.md
.agent-work/reviews/iteration-29-amdgpu-reset-failure-diagnostic.md
.agent-work/reviews/iteration-30-nvidia-xid-79-diagnostic.md
.agent-work/reviews/post-migration-architecture-assessment.md
.agent-work/reviews/review-iteration-24-evidence-payload-integrity-hardening.md
.agent-work/reviews/syscheck-product-coverage-assessment.md
.gitignore
AGENTS.md
constants.py
syscheck.py
test_syscheck.py
```

Modified tracked paths are `AGENTS.md`, `constants.py`, `syscheck.py`, and
`test_syscheck.py`. `.gitignore` and the older tracked reviews are unchanged.

### Non-ignored untracked paths at audit start (15)

```text
.agent-work/reviews/codex-post-refactor-audit-iteration-33.md
.agent-work/reviews/codex-repository-wide-audit-before-iteration-32.md
.agent-work/reviews/iteration-31-architecture-boundary-and-workflow-hardening-assessment.md
.agent-work/reviews/iteration-32a-baseline-correctness-remediation.md
.agent-work/reviews/iteration-32b-kernel-package-portability.md
.agent-work/reviews/iteration-33-extract-diagnostic-rule-runtime.md
.agent-work/reviews/iteration-33a-import-boundary-hardening.md
.agent-work/reviews/iteration-34-pcie-aer-diagnostic.md
.agent-work/reviews/iteration-35a-fix-pcie-nvme-control-flow.md
.agent-work/reviews/iteration-35b-complete-and-audit-nvme-diagnostic.md
.agent-work/reviews/iteration-37-threat-model-security-boundary-assessment.md
.agent-work/reviews/iteration-37a-security-boundary-hardening.md
.agent-work/reviews/iteration-37b-security-verification.md
.codex/environments/environment.toml
diagnostic_rules.py
```

This review file is the only additional path created by this audit; after its
creation the non-ignored untracked count is 16.

### Ignored inventory (78 entries)

The ignored entries are all accounted for by these groups:

- `.agent-work/prompts/`: 44 prompt files. They include the Iteration 31–37A
  task prompts, earlier DeepSeek feasibility/implementation prompts, and the
  two security prompts. They are provenance inputs, not release files.
- `.agent-work/reviews/`: 8 superseded review files:
  `iteration-17-btrfs-device-error-evidence-migration.md`,
  `iteration-18-segfault-evidence-migration.md`,
  `iteration-19-kernel-taint-evidence-migration.md`,
  `iteration-20-boot-delay-evidence-migration.md`,
  `iteration-21-runtime-compatibility-removal.md`,
  `iteration-22-contract-simplification.md`,
  `iteration-23-boot-time-collector-payload.md`, and
  `review-syscheck-diagnostic-accuracy-20260727.md`.
- `.pytest_cache/`, `.ruff_cache/`, and `__pycache__/`: 20 generated cache
  files.
- Repository-root generated/backup files (6):
  `syscheck-<REDACTED-HOST>-<TIMESTAMP>.md`,
  `syscheck-<REDACTED-HOST>-<TIMESTAMP>.md`, `syscheck.py.broken`,
  `syscheck.py.clean`, `syscheck.py.v2.bak`, and `syscheck.py.v9.bak`.

The prompt and ignored-review counts were obtained from the filesystem and
`git check-ignore`; no ignored file was deleted or altered.

## Hunk ownership map

The following is a logical map of the current diff. Current line anchors are
for orientation; `git add -p` must be used because several adjacent hunks need
to be split interactively.

| Path / current area | Ownership | Staging decision |
| --- | --- | --- |
| `AGENTS.md` (all 19 changed lines) | Repository workflow/NeuralEngine policy; pre-existing and outside the product iterations | Keep out of code commits; either defer or make a separate explicitly authorized policy commit. |
| `constants.py:31–43` | Iteration 34 PCIe AER and Iteration 35A/35B NVMe matchers | Stage with the corresponding diagnostic feature commit, not with security changes. |
| `constants.py:83–91` | Iteration 37A status-preserving Arch package pipeline | Stage only with the security-boundary commit. |
| `syscheck.py` import/re-export areas | Iteration 32A baseline cleanup, Iteration 33/33A rule-runtime boundary, Iterations 34–35 compatibility exports, and the Iteration 37A minimal `import sys` repair | Hunk-level selection required. |
| `syscheck.py:98–150` (`CmdResult`) | Iteration 37A bounded capture, truncation markers, and timeout partial-output visibility | Stage with Iteration 37A. |
| `syscheck.py:165–180`, classification policy additions | Iteration 34 AER and Iteration 35 NVMe classifications, with Iteration 32A completeness work | Split by feature ownership. |
| `syscheck.py:290–448` (`run_cmd`, `_capture_payload`, `_write_new_text`) | Iteration 37A bounded subprocess drains, timeout process-group handling, incomplete evidence metadata, and exclusive no-follow destination creation | Stage with Iteration 37A. |
| `syscheck.py:663–713` (`_count_kernel_packages`) | Iteration 32B Debian/RPM package-output portability | Stage with Iteration 32B. |
| `syscheck.py:788–832` journal helpers | Iterations 34–35 status-aware kernel/AER/NVMe collection, extended by Iteration 37A source-status handling | Split the feature collector additions from the hardening changes. |
| `syscheck.py` rule-runtime block removal/re-exports around the 33-era line shift | Iteration 33 extraction and Iteration 33A import-boundary compatibility | Stage with `diagnostic_rules.py` and the matching import tests. |
| `syscheck.py` kernel collector around the current `collect_kernel_hw()` | Iteration 34 AER, Iteration 35A branch independence, Iteration 35B NVMe contract, and Iteration 37A capture-completeness propagation | Split AER, NVMe, and security hunks. |
| `syscheck.py:2977–3270` report path and `:3846–3854` snapshot writer, plus compare output | Iteration 37A exclusive report/snapshot/compare writes | Stage with Iteration 37A. |
| `syscheck.py` mode | `100755 -> 100644`; no Iteration 32A–37B review claims this ownership | Do not silently stage. Decide explicitly whether to restore executable mode or record it as an intentional separate change. |
| `test_syscheck.py` import/re-export fixtures | Iterations 33A–35 compatibility and feature tests | Split by adjacent test class/hunk. |
| `test_syscheck.py` classification/hash tests | Iteration 32A | Stage with Iteration 32A. |
| `test_syscheck.py` package fixtures | Iteration 32B | Stage with Iteration 32B. |
| `test_syscheck.py` AER/NVMe collector and pipeline classes (around current lines 5968–7066) | Iterations 34, 35A, and 35B | Split AER from NVMe/control-flow tests. |
| `test_syscheck.py` bounded/status/write tests (around current lines 783–984 and snapshot updates) | Iteration 37A | Stage with Iteration 37A. |
| `diagnostic_rules.py` (49,591-byte untracked file) | Iteration 33 extraction plus later Iteration 34 AER and Iteration 35 NVMe rules/registry entries | Do not treat as a single Iteration 33 whole-file hunk if strict ownership is required; use intent-to-add then `git add -p`, or deliberately make one consolidated runtime/rules commit. |
| `.agent-work/reviews/iteration-*`, `codex-*.md` | Review provenance for Iterations 31–37B and prerequisites | Optional separate review-doc commit; never mix with production hunks. |

The source/test diff is therefore attributable, but not whole-file stageable.

## Review, prompt, `.codex`, and policy classification

| Artifact class | Classification | Action |
| --- | --- | --- |
| Tracked older reviews | Historical repository documentation | Leave untouched; already in `HEAD`. |
| Untracked Iteration 31–37B reviews, plus the two pre-32/33 codex reviews | Current checkpoint provenance | Prefer one separate review-doc commit after code, if publication of these artifacts is intended. |
| `.agent-work/prompts/` | Ignored agent inputs and historical prompt archive | Do not stage or delete. The `(1)` repository-wide-audit prompt is an exact duplicate of the non-suffixed file (SHA-256 `97c5cc13b8c3717dd8e16200124604c3e52a217531fdc60ee546784ef7506571`); it is a cleanup candidate only with explicit approval. |
| `.codex/environments/environment.toml` | Local agent environment configuration | Keep local; exclude from release commits unless separately authorized. |
| `AGENTS.md` | Tracked governance/policy file, not product implementation | Defer or isolate in its own explicit policy commit; do not fold into Iteration 32A–37B code commits. |
| `diagnostic_rules.py` | Required product source for the accepted runtime extraction | Include in the code sequence with hunk-level ownership. |
| Ignored caches, generated reports, `.bak`/`.broken`/`.clean` files | Ephemeral or superseded artifacts | Do not stage; do not remove during this audit. |

## Accidental or superseded items

1. The duplicate prompt described above is confirmed byte-for-byte identical;
   it is a deferred cleanup candidate, not a release input.
2. The root `syscheck.py.*` files and generated Markdown are backups/output,
   not source candidates.
3. The `100755 -> 100644` `syscheck.py` mode change has no cited iteration
   owner. It is the only unowned tracked diff item found and requires an
   explicit staging decision.
4. The modified `AGENTS.md` is real tracked work, but Iteration 31 and the
   later security reviews describe it as pre-existing/out of application scope;
   it must not be smuggled into a product commit.

## Recommended logical commit sequence

This is a staging design, not an operation performed by this audit:

1. **Iteration 32A baseline correctness** — selected `syscheck.py` and
   `test_syscheck.py` hash/classification/renderer hunks.
2. **Iteration 32B package portability** — `_count_kernel_packages()` and its
   focused fixtures.
3. **Iterations 33 + 33A runtime boundary** — selected extraction/import
   hunks, the relevant `diagnostic_rules.py` portions, and import-boundary tests.
4. **Iteration 34 PCIe AER** — AER constants, collector/evidence/classification
   hunks, the AER rule additions, and AER tests.
5. **Iterations 35A + 35B NVMe** — NVMe constants, independent control-flow,
   severity/evidence/classification/rule hunks, and NVMe tests.
6. **Iteration 37A security hardening** — bounded capture and incomplete
   evidence, source-status handling, exclusive report/snapshot/compare writes,
   and the 23 focused tests. Include the minimal `import sys` repair here only
   because the 37A review records it as the baseline-compatibility repair.
7. **Review provenance** — the untracked Iteration 31–37B and prerequisite
   codex review files, including this 36B artifact, in a documentation-only
   commit if these reviews are intended to be published.
8. **AGENTS.md policy** — separate and optional; defer unless explicitly
   authorized. Never include `.agent-work/prompts/`, `.codex/`, caches, or
   generated/backup files.

If exact ownership of `diagnostic_rules.py` cannot be split cleanly, combine
steps 3–5 into one explicitly named runtime/rules commit rather than pretending
that a whole-file add belongs only to Iteration 33.

## Exact manual backup and staging commands

The following commands are provided for the operator to run once. They were not
run by this audit:

```sh
backup_dir="$(mktemp -d /tmp/linux-diagnostic-engine-checkpoint.XXXXXX)"
git diff --binary HEAD -- AGENTS.md constants.py syscheck.py test_syscheck.py > "$backup_dir/worktree.patch"
git status --short --untracked-files=all > "$backup_dir/status.txt"
cp -a -- AGENTS.md constants.py syscheck.py test_syscheck.py diagnostic_rules.py .agent-work .codex "$backup_dir/"
printf 'Backup: %s\n' "$backup_dir"
```

Starting from an empty index, each logical commit should use interactive
hunk selection. At every prompt, split (`s`) or manually edit (`e`) a mixed
hunk and accept only the iteration listed for that commit:

```sh
# For each of steps 1, 2, 4, 5, and 6:
git add -p -- constants.py syscheck.py test_syscheck.py
git diff --cached --name-status
git diff --cached --stat
git diff --cached --check
```

For the new rule-runtime file, make it patch-visible before selecting its
sections; do not blindly add the whole mixed-ownership file:

```sh
git add -N -- diagnostic_rules.py
git add -p -- diagnostic_rules.py syscheck.py test_syscheck.py
git diff --cached --name-status
git diff --cached --check
```

For the optional review-doc commit, use an explicit path list (after this file
exists):

```sh
git add -- \
  .agent-work/reviews/codex-post-refactor-audit-iteration-33.md \
  .agent-work/reviews/codex-repository-wide-audit-before-iteration-32.md \
  .agent-work/reviews/iteration-31-architecture-boundary-and-workflow-hardening-assessment.md \
  .agent-work/reviews/iteration-32a-baseline-correctness-remediation.md \
  .agent-work/reviews/iteration-32b-kernel-package-portability.md \
  .agent-work/reviews/iteration-33-extract-diagnostic-rule-runtime.md \
  .agent-work/reviews/iteration-33a-import-boundary-hardening.md \
  .agent-work/reviews/iteration-34-pcie-aer-diagnostic.md \
  .agent-work/reviews/iteration-35a-fix-pcie-nvme-control-flow.md \
  .agent-work/reviews/iteration-35b-complete-and-audit-nvme-diagnostic.md \
  .agent-work/reviews/iteration-37-threat-model-security-boundary-assessment.md \
  .agent-work/reviews/iteration-37a-security-boundary-hardening.md \
  .agent-work/reviews/iteration-37b-security-verification.md \
  .agent-work/reviews/iteration-36b-final-checkpoint-staging-audit.md
git diff --cached --name-status
git diff --cached --check
```

Do not use a broad `git add .` or `git add -A`; it would include the local
`.codex` file and could make ignored/provenance decisions implicit.

## Per-commit validation and final push gate

Before each manual commit, inspect the staged path set and run:

```sh
git diff --cached --check
git diff --cached --stat
ruff format --check .
ruff check .
python3 -m pytest --collect-only -q
python3 -m pytest -q
git diff --check
```

Because later accepted hunks may remain unstaged in the same worktree, a test
run before an intermediate commit exercises the complete working tree, not an
isolated historical commit. If isolated per-commit evidence is required, test
from a clean temporary copy made from that commit and the recorded backup
patch; do not infer isolation from a green run in a dirty combined tree.

After the last code and optional review commit, the final gate is:

```sh
git status --short --untracked-files=all
git diff --check
git diff --cached --check
git diff --cached --name-status
ruff format --check .
ruff check .
python3 -m pytest --collect-only -q
python3 -m pytest -q
git log --oneline --decorate -n 8
```

The push is a separate, explicit operator decision. Only after the final gate,
clean-tree review, and authorization should the operator run
`git push origin master`, followed by a remote ref check such as
`git ls-remote --heads origin master`. No push was attempted here.

## Validation performed for this audit

- `ruff format --check .` — PASS (`4 files already formatted`).
- `ruff check .` — PASS (`All checks passed!`).
- `python3 -m pytest --collect-only -q` — PASS (`594 tests collected`).
- `python3 -m pytest -q` — PASS (`594 passed in 2.58s`).
- `git diff --check` — PASS.
- `git diff --cached --quiet` — PASS; no staged changes.
- Remaining-pattern audit: no production `capture_output=True`, `|| true`,
  `|| echo 0`, or `returncode == 1` sites. The remaining `capture_output=True`
  matches are test subprocesses. Production writes route through
  `_write_new_text()` (`os.open(...O_EXCL|O_NOFOLLOW...)`); snapshot/compare
  read paths use `open(..., encoding=...)`, not write mode.

## Scope audit

This audit created only
`.agent-work/reviews/iteration-36b-final-checkpoint-staging-audit.md`.
It did not modify production code, tests, `AGENTS.md`, `.gitignore`, Git
history, index/staging, NeuralEngine state, or remote state. Existing dirty
work was preserved.

## Blockers and deviations

- Whole-file staging is rejected by the mixed ownership map; hunk-level
  selection is required.
- The executable-mode change on `syscheck.py` is unowned and must be decided
  before any commit containing that file.
- `AGENTS.md`, `.codex/environments/environment.toml`, prompts, caches, and
  generated/backup artifacts require explicit exclusion or separate policy;
  none should enter a product commit implicitly.
- The final source is green and the ownership map is actionable, so the
  worktree is not classified as ambiguous (`D`) and no cleanup/remediation is
  required before the operator can begin manual hunk staging (`C`).

## NeuralEngine usage

`neural status`:

```text
Neural Engine 1.1.0
Resolved home: <REDACTED-PATH>
Brain state: Initialized
Brain Trust state: TRUSTED_CURRENT
```

NeuralEngine search used: **YES**

Query:

- `Iteration 36B final checkpoint staging audit`

Returned records: none (`No matching knowledge found.`). No exact records were
inspected. The search did not change the candidate actions or verdict; it only
confirmed that current repository evidence and the supplied iteration reviews
were the authoritative checkpoint sources.

Brain writes: **NONE**
