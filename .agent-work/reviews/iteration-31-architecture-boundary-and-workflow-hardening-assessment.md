# Iteration 31 — Architecture Boundary and Workflow Hardening Assessment

## Scope and repository authority

This is a read-only architecture and workflow assessment. No production code,
tests, Git references, branch, HEAD, or NeuralEngine Brain records were modified.

**PRECONDITION VIOLATION:** a clean worktree was required at task start, but
Git recorded ` M AGENTS.md` before this review artifact existed. The task
therefore did not meet its clean-tree entry condition. This is established by
Git state, not by an agent declaration; the pre-existing file remains out of
scope and unmodified.

Verified repository state at assessment start:

```text
repository : <REDACTED-PATH>
expected   : 2385be1 chore: add NeuralEngine agent guidance
HEAD       : 2385be1efffa13a12936c8b1eef942936650d357
branch     : master
HEAD reflog: 2385be1efffa13a12936c8b1eef942936650d357 commit: chore: add NeuralEngine agent guidance
```

The expected checkpoint matched `HEAD`, `master`, `origin/master`, and the tip
of `HEAD` reflog. `AGENTS.md` was already modified in the worktree before this
assessment; it is explicitly out of scope and was not changed. This review is
the only artifact created. Git state overrides this review's declarations at
every point.

## 1. Should decomposition precede further diagnostics?

**Yes. Pause new diagnostics for one small structural extraction.**

Current `syscheck.py` is 5,036 lines and contains the CLI, collectors,
normalisation helpers, domain data types, Evidence runtime, the diagnostic
rule runtime, `SysCheckEngine`, recommendation generation, snapshot schema and
comparison. The direct extension point has grown materially: fifteen concrete
`DiagnosticRule` classes plus `DiagnosticRuleRegistry`, `DiagnosticRuleEngine`,
and `build_default_rule_engine()` occupy the contiguous region from lines
1251–2186. Each of the four latest feature commits before the agent-guidance
commit added a new diagnostic (OOM, i915 hang, AMDGPU reset failure, NVIDIA Xid
79), so this is the active growth seam, rather than speculative cleanup.

The existing architecture remains sound: collectors produce `RawDiagnostic`,
observations are evaluated into `DiagnosticRuleResult` (Finding plus Evidence),
and recommendations consume Findings. The proposed step preserves that
contract; it does not redesign collectors, Evidence, snapshots, reports, or
recommendations.

## 2. Exactly one smallest extraction boundary

Extract **only the diagnostic rule runtime** into `diagnostic_rules.py`:

- `DiagnosticRuleResult`, rule exceptions, `DiagnosticRule`, the 15 concrete
  rules, `DiagnosticRuleRegistry`, `DiagnosticRuleEngine`, and
  `build_default_rule_engine()` (current lines 1251–2186).
- Keep `CmdResult`, `Observation`, `Finding`, classification policy, Evidence
  types/builder, collectors, `SysCheckEngine`, renderer, recommendations,
  snapshots, CLI, and public compatibility imports in `syscheck.py`.
- Have `syscheck.py` import/re-export the rule-runtime public symbols so the
  present test and consumer import surface remains valid during this one step.

Why this is the smallest justified boundary: a single rule class is too small
to reduce the recurring integration cost, while extracting snapshots or
recommendations does not isolate the location every forthcoming diagnostic
must modify. Extracting classification or Evidence separately first would
create a second artificial module boundary without removing the growing rule
cluster. The selected boundary has one orchestration caller in production
(`SysCheckEngine._interpret`) and a stable input/output contract
(`Observation` to `DiagnosticRuleResult`), despite broad test coverage of its
public classes.

Required acceptance criteria for that later, separately authorised change:

1. Rule registration order, supported categories, finding IDs, Evidence IDs,
   reports, snapshots, and CLI output remain unchanged.
2. `DiagnosticRuleEngine.evaluate()` remains `Observation ->
   DiagnosticEvaluation(findings, evidence)` and accepts only
   `DiagnosticRuleResult` from native rules.
3. Existing imports from `syscheck` continue to work, or a separately approved
   compatibility migration changes them deliberately.
4. The full existing test suite passes; no new diagnostic is bundled with the
   extraction.

## 3. Mandatory Git/reflog verification

Git state is authoritative; agent statements such as “read-only,” “no commit,”
or “unchanged” are not evidence. Before and after every assessment or change,
capture and compare these values from Git itself:

```bash
expected=2385be1efffa13a12936c8b1eef942936650d357
git rev-parse --verify HEAD
git symbolic-ref --short HEAD
git status --porcelain=v1 -uall
git reflog -1 --format='%H %gd %gs'
git log -1 --format='%H %P %s'
git merge-base --is-ancestor "$expected" HEAD
```

For a task declared read-only, the post-task `HEAD` object ID, symbolic branch,
last `HEAD` reflog entry, and `HEAD` parent list must equal their pre-task
values. Status may differ only by the explicitly authorised review artifact;
pre-existing changes must remain byte-for-byte outside the allowlist. Any
different HEAD, branch, reflog tip/action, parent list, or unapproved path is
a **WORKFLOW VIOLATION**. Stop reporting substantive results, preserve the
observed Git output, and do not attempt `reset`, `restore`, rebase, branch, or
other corrective history mutation.

`git status` alone is insufficient: it does not prove that an intervening
commit, checkout, reset, or branch switch did not occur. Reflog plus object,
branch, and parent comparison does.

## 4. Minimal backup/checkpoint protocol for later writable work

1. Require an explicit base commit and record its full object ID, branch,
   `HEAD` reflog tip, and porcelain status before editing.
2. If the worktree is clean, the immutable Git commit is the backup; create no
   duplicate source copy.
3. If it is dirty, stop unless every pre-existing changed/untracked path is
   explicitly excluded from the task. Before editing, make one recoverable
   external checkpoint: a binary tracked diff plus copies of the named
   untracked paths in a unique user-controlled directory outside the repository
   (for example `/tmp/lde-<task>-<timestamp>/`), and record SHA-256 hashes.
   Do not use `git stash`, `reset`, `restore`, or an in-repository backup.
4. Limit edits to an explicit path allowlist. Before commit or handoff, compare
   status, `git diff --check`, the allowed-path diff, `HEAD`, branch, and
   reflog with the recorded checkpoint. Keep the external checkpoint until the
   user accepts the result.

This protocol protects dirty work without conflating a backup with an agent
declaration or producing a second source of truth inside the repository.

## 5. SysCheck → LDE naming debt

The repository is `linux-diagnostic-engine`, but the executable module,
`SysCheckEngine`, snapshot metadata field (`syscheck_version`), report names,
and test imports use SysCheck. This is real naming debt but is not currently a
functional or architectural blocker: SysCheck is the established CLI/tool
identity and LDE accurately names the repository/project.

Adopt the narrow naming rule now: **LDE is the repository/project name;
SysCheck is the CLI and Python runtime name.** Do not rename files, classes,
snapshot fields, report filenames, or imports in the extraction. Revisit a
rename only with an explicit user-facing branding requirement and a migration
plan for CLI invocation, snapshot compatibility, generated reports, and test
imports. A rename now would create high compatibility churn while obscuring the
single needed architecture boundary.

## NeuralEngine usage

neural status:

```text
Neural Engine 1.1.0; resolved NEURAL_HOME <REDACTED-PATH>;
Brain state Initialized and accessible.
```

NeuralEngine search used: YES

Queries:

- `linux diagnostic engine syscheck architecture workflow git reflog backup checkpoint`

Returned records:

- None — no matching knowledge record.

Exact records inspected:

- None.

Material effect:

No material change; current repository authority and source history controlled
the recommendation.

Brain writes: NONE

Decision B — Minimal architecture extraction first
