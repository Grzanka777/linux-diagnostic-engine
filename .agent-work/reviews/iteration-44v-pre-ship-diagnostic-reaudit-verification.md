# LDE Iteration 44V — Pre-Ship Diagnostic Re-Audit / Verification

Date: 2026-08-29  
Repository: `<REDACTED-PATH>`  
Checkpoint: `HEAD == origin/master == 63dd1e9`  
Baseline: `839/839 PASS`

## Verdict

**PASS — the Iteration 44R remediation is independently verified for the frozen
diagnostic scope.** No product code or tests were modified, no defect was fixed,
and no real-machine diagnostic capture was run.

The eight named I44 controls are present in the live checkout, are covered by
the 839-test regression suite, and passed fresh source, focused-probe, and full
suite review. The only additional observation is a non-gating presentation-order
hardening item described below; it does not change the semantic compatibility of
snapshot comparison or the I44 release gates.

## I44-01..I44-08 re-audit

| Item | Result | Independent evidence |
|---|---|---|
| I44-01 — storage ID uniqueness/determinism | **PASS** | `syscheck.py:493-506` preserves the historical root IDs and uses an injective percent-encoded mount suffix for other qualifying mounts. Source, the I44R regression at `test_syscheck.py:11181-11217`, and an additional mount corpus probe confirmed unique and repeatable IDs, observations, findings, and raw records. |
| I44-02 — bounded capture completeness / no authoritative absence | **PASS** | `run_cmd()` drains both streams concurrently with a per-stream byte limit and a `truncated` bit (`syscheck.py:340-416`). Every relevant current-boot result is passed to `_record_truncated_capture()` (`syscheck.py:2772-2774`), which records that absence is not authoritative (`syscheck.py:2224-2235`). The no-match truncated OOM regression passed; an additional runtime probe retained the older prefix and marked truncation. |
| I44-03 — legacy completeness propagation | **PASS** | Btrfs/storage (`syscheck.py:2521-2633`), systemd/boot (`syscheck.py:3522-3633`), and kernel-count (`syscheck.py:3664-3764`) all use `_raw_from_result()`. `_capture_payload()` carries truncation into RAW, and `_raw_to_observation()` maps it to incomplete data (`syscheck.py:460-490`, `syscheck.py:4047-4179`). The five I44R parameterized regressions and an additional mocked collector probe reached partial Evidence and `Guessing` confidence. |
| I44-04 — taint over 50 lines / no lossy tail dependency | **PASS** | `kernel_errors` is built without `tail -50` (`syscheck.py:2648-2654`); bounded capture retains the prefix and exposes truncation. The I44R regression at `test_syscheck.py:11290-11312` and the additional >50-line runtime probe retained an older `Tainted:` line. |
| I44-05 — snapshot lineage and legacy schema-3 compatibility | **PASS** | Current snapshot construction persists Finding→Evidence→Observation→RawDiagnostic references (`syscheck.py:5426-5532`); validation resolves references when current collections are present (`syscheck.py:5228-5307`). Current lineage round-trip and a schema-3 snapshot without lineage both loaded and validated in tests and an additional direct probe. |
| I44-06 — non-causal taint wording | **PASS** | `KernelTaintRule` states that the cause is unresolved and explicitly says not to infer it without additional evidence (`diagnostic_rules.py:288-332`). The I44R wording regression passed; no unsupported out-of-tree/open-driver cause was found in the taint finding text. |
| I44-07 — Btrfs inactive vs never-run scrub | **PASS** | `_classify_btrfs_status()` distinguishes no history from an inactive scrub (`syscheck.py:686-739`). Inactive status produces informational report text and no scrub Finding; no-history status produces the explicit `never_run` payload (`syscheck.py:2578-2601`). The I44R regression and an additional classification probe passed. |
| I44-08 — RawDiagnostic collection metadata | **PASS** | All production RawDiagnostic construction routes through `_raw_from_result()` (`syscheck.py:480-490`); `collected_at`, command/status metadata, optional-dependency state, and truncation are preserved in raw snapshot models (`syscheck.py:5022-5049`). The I44R provenance regression and an additional lineage round-trip probe passed. |

## Cross-cutting audit

### Architecture boundaries

**PASS.** The stages remain separated: collectors produce `RawDiagnostic`,
`_derive_observations()` consumes only RAW, and `_interpret()` delegates from
Observation to the rule engine (`syscheck.py:4035-4045`, `syscheck.py:4399-4405`).
RAW has no severity, confidence, interpretation, or recommendation. The rule
runtime is isolated in `diagnostic_rules.py`, with the existing lazy boundary
preserved.

### Rule and policy consistency

**PASS.** Rule registration is unique; category-based classification does not
depend on storage-ID prefixes; system and user systemd rules are mutually gated
by scope; inactive scrub yields no Finding; and the engine rejects duplicate
Finding/Evidence IDs. The existing policy and architecture guard regressions
passed in the 839-test suite.

### Mixed-family false positives and overlap

**PASS.** Dedicated current-boot queries use family-specific regexes and then
re-check the matching family before producing RAW (`syscheck.py:2972-3477`).
The existing coexistence/isolation tests passed. An additional corpus probe
covered representative AMDGPU, filesystem, MCE/EDAC, thermal, IOMMU, firmware,
lockup, hung-task, RCU, NVMe, PCIe, ACPI, USB, i915, and NVIDIA Xid lines; each
matched its intended specialized family without an unexpected sibling match.

### Snapshot/report/compare compatibility

**PASS for the I44 contract.** Schema 3 remains the current schema; current
lineage and raw provenance survive round-trip; legacy schema-3 snapshots without
lineage continue to load; and report, snapshot, and compare outputs route through
the exclusive `_write_new_text()` sink (`syscheck.py:509-527`, `syscheck.py:4463`,
`syscheck.py:5143-5149`, `syscheck.py:5834-5841`). Existing typed snapshot,
migration, comparison, and destination-integrity tests passed.

Non-gating observation: `_environment_changes()` iterates sets for multi-entry
storage and failed-unit differences (`syscheck.py:5693-5724`). Separate processes
with different `PYTHONHASHSEED` values produced the same semantic changes but
different Markdown ordering. This is outside the I44 remediation contract and
does not alter finding/environment meaning, but strict byte-identical compare
reports would need a later deterministic-order hardening change.

### Iteration 37A/37B security invariants

**PASS.** Fresh source tracing found one production subprocess launch in
`run_cmd()` (`syscheck.py:359-365`), concurrent bounded stream drains, process
group termination on timeout, and status-preserving pipelines. No production
`capture_output=True`, `shell=True`, `os.system`, direct text-write sink,
`Path.replace()`, `|| true`, or `|| echo 0` path was found. The only production
`open()` outside the exclusive writer is read-only snapshot loading. Final
destination creation retains `O_EXCL`/`O_NOFOLLOW` and raced-cleanup inode checks.
The historical AER/NVMe independence and source-status regressions remain in the
passing suite. No privilege escalation, package/service mutation, Git mutation,
or NeuralEngine runtime path was introduced.

### Adequacy of 839-test regression coverage

**PASS for the frozen release gate.** Collection confirmed exactly 839 tests;
the I44R class contains direct regressions for all eight named controls, with the
I44-03 completeness case parameterized across five legacy producer categories.
The wider suite covers architecture separation, classification policy, mixed
native/legacy rule coexistence, destination safety, source status handling,
family isolation, snapshot migration, and AER/NVMe invariants.

Residual test-depth limits are recorded rather than hidden: there is no branch
coverage report; some I44-03 assertions exercise the common RAW→Observation path
directly while collector routing is source-reviewed and additionally probed; and
the existing compare stability test is same-process only. These limits do not
invalidate the frozen I44 gate because the relevant source paths, direct tests,
and independent probes agree.

## Validation

All requested commands were run against the checkpoint. No command modified
product code, tests, Git history, or `.codex/`.

| Command | Result |
|---|---|
| `ruff format --check .` | **PASS** — `4 files already formatted` |
| `ruff check .` | **PASS** — `All checks passed!` |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest --collect-only -q` | **PASS** — `839 tests collected in 1.01s` |
| `PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp python3 -m pytest -q` | **PASS** — `839 passed in 7.89s` |
| `git diff --check` | **PASS** — no output |

Additional read-only probes passed for storage-ID injectivity, bounded capture
prefix retention, Btrfs status semantics, all five legacy completeness routes,
current lineage round-trip, legacy schema-3 loading, and specialized-family
overlap.

## Safety and state

- Before creating this artifact, `git status --short` was exactly `?? .codex/`.
- After artifact creation, the only additional repository path is this required
  review file; `.codex/` was not touched.
- `HEAD` and `origin/master` both resolved to
  `63dd1e97753ab71445bc4818f467fc1198e4a2e9`.
- No add, commit, push, reset, restore, stash, branch, merge, rebase, tag, or
  clean action was run.
- `neural status` and a read-only generic knowledge listing were performed as
  required; no relevant LDE record was used and no NeuralEngine Brain write was
  performed.
- No real-machine E2E, package installation, service mutation, or production
  data mutation was performed.

## Final gates

```text
PRE_SHIP_REAUDIT = PASS
READY_FOR_REAL_MACHINE_E2E = YES
FEATURE_EXPANSION_REMAINS_FROZEN = YES
```

Next step: **Iteration 45 — Real-Machine End-to-End Validation.**
