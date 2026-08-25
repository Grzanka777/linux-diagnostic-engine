# Iteration 37 — Threat Model / Security Boundary Assessment

## Verdict

**B — minor hardening before more features.**

The application has a coherent read-only diagnostic boundary and no demonstrated
command-injection, automatic privilege-escalation, GitHub, or NeuralEngine
runtime path. One low-severity availability weakness is directly confirmed:
subprocess output is captured without a byte budget. Two related observability
gaps (status masking and filesystem write hardening) should be addressed before
the next feature expansion, but the source does not establish a cross-user or
remote boundary that would make them release-blocking on its own.

This is an assessment only. No application code, tests, `AGENTS.md`, Git
history, or NeuralEngine Brain state was modified.

## Scope and evidence

Reviewed the current worktree after the Iteration 36 staging/checkpoint state,
including:

- `syscheck.py`, `diagnostic_rules.py`, `constants.py`, and `test_syscheck.py`;
- `AGENTS.md`, `.gitignore`, `.codex/environments/environment.toml`, and
  `.git/config` for workflow and external-boundary context;
- the complete CLI, collector, parser, diagnostic-rule, snapshot, and report
  paths relevant to this request;
- independent read-only baseline and architecture reviews.

The worktree was already dirty. Existing changes were preserved and were not
treated as Iteration 37 edits. The only file created for this assessment is
this review artifact.

Codex Security standard scan:

- scan ID: `<UUID-LIKE-SCAN-ID>`;
- target revision: `2385be1efffa13a12936c8b1eef942936650d357`;
- required snapshot digest:
  `codex-security-snapshot/v1:sha256:9f584345f754350bb811f60479c02da8bb4f89142065b248cacd44e85c0e370d`;
- twelve security surfaces recorded; one validated low-severity finding;
- runtime capacity was degraded (3 usable worker slots versus the profile
  suggestion of 6), without a blocking scan failure;
- TAC advisory status was `not_granted`; this did not block the local
  read-only assessment. No protected finding data was required.
- Codex Security sealed results for the original snapshot and warned that the
  worktree changed while the scan was running; the change was the requested
  review artifact, not application code.

No repository `SECURITY.md` policy was resolved.

## Checkpoint

- Audit checkpoint: current worktree after the Iteration 36 staging/checkpoint
  state, with pre-existing dirty changes preserved.
- Exact path created by Iteration 37:
  `.agent-work/reviews/iteration-37-threat-model-security-boundary-assessment.md`.
- Pre-existing tracked dirty paths preserved: `AGENTS.md`, `constants.py`,
  `syscheck.py`, and `test_syscheck.py`; pre-existing untracked reviews,
  `diagnostic_rules.py`, and `.codex/` were also preserved.
- Tracked working-tree diff stat: 4 files changed, 815 insertions, 1002
  deletions.
- SHA-256 of the complete tracked `git diff --no-ext-diff` at final validation:
  `a3615459393bf7a9c8e274d2dd6d8583d402f018a9870f1bfef269a01d0f90e7`.

## Threat model

### Assets

- Host telemetry confidentiality: hostname, kernel/cmdline, processes, block
  devices, mounts, journals, systemd, package, network, and selected
  environment values.
- Provenance and integrity of `CmdResult` → `RawDiagnostic` → `Observation`
  → `Evidence`/`Finding` and their report/snapshot representations.
- Diagnostic process availability and bounded memory, CPU, and disk use.
- Report, snapshot, and comparison-output filesystem integrity.
- The invoking process identity and any capabilities it already possesses.

### Trust boundaries and capabilities

1. **CLI caller/environment → subprocess runner.** The caller controls argv
   paths and inherited environment/PATH. `run_cmd()` uses argument vectors,
   `subprocess.run()` without `shell=True`, timeouts, and captured output
   (`syscheck.py:255-340`). The process retains the caller's UID/capabilities.
2. **Fixed shell pipeline → parser.** Selected collectors invoke static
   `bash -c` pipelines and constant regular expressions
   (`syscheck.py:631-656`, `1877-1950`, `2560-2566`, `2612-2620`). No CLI or
   journal value reaches those shell strings in production call sites.
3. **Host command/journal output → diagnostic model.** Raw records are mapped
   deterministically to observations and then evaluated by the registered rule
   engine (`syscheck.py:2813-3049`, `diagnostic_rules.py:1005-1073`).
4. **CLI paths → filesystem artifacts.** `--output-dir`, `--snapshot`, and
   `compare --output` are caller-selected paths
   (`syscheck.py:3093-3101`, `3696-3707`, `4270-4279`).
5. **Agent/developer workflow → Git/GitHub and NeuralEngine.** These are
   external workflow boundaries. Production modules contain no Git command,
   GitHub client, HTTP client, or NeuralEngine client.

Attacker capabilities established by source are local: a caller can influence
argv, PATH/environment, readable command output, and snapshot input. A local
actor can run the process as root only if it already has that authority. No
remote attacker, tenant model, service wrapper, or automatic publication path
is established.

## Findings and boundary decisions

### F-01 — Unbounded subprocess output can exhaust diagnostic resources

- **Severity:** Low; **confidence:** High; **CWE-400**.
- **Source:** `run_cmd()` calls `subprocess.run(..., capture_output=True)` and
  stores complete stdout/stderr (`syscheck.py:272-299`).
- **Reachability:** broad current-boot journal collectors and other host
  commands can produce large streams (`syscheck.py:1877-1950`, `2612-2620`).
  `safestr()` truncates only after capture and `--full` disables selected report
  truncation (`syscheck.py:343-347`). Up to eight workers can capture output
  concurrently (`syscheck.py:1487-1532`).
- **Impact:** a local workload or actor able to generate sufficiently large
  readable output can cause memory/CPU pressure, oversized reports, disk
  pressure, severe slowdown, or process termination. Timeouts and worker limits
  do not cap bytes already captured.
- **Required hardening:** impose per-command and aggregate byte/line budgets,
  stream or truncate while preserving exit status, and add explicit journal
  output limits. This is the reason for verdict B.

### Source failure versus no-match

Finding-producing `_oom_collector_command()` preserves both upstream
`journalctl` and `grep` statuses through `PIPESTATUS` and treats grep's ordinary
no-match status separately (`syscheck.py:631-656`). The NVMe and PCIe AER
branches therefore do not turn an unavailable journal into a Finding; the
existing NVMe-only, AER-only, and combined-independence regressions passed.

There is a control gap outside those status-aware paths. Several display
pipelines append `|| true`, and `auth_fails` appends `|| echo 0`
(`syscheck.py:1881`, `1890`, `1899`, `2564-2565`, `2616`). A failed journal
query can consequently look like no matches, including a displayed zero failed
login count. In addition, `run_cmd()` globally maps any return code 1 with empty
stdout to `empty_ok` (`syscheck.py:283-289`), although only one package query is
documented as needing that behavior. This is a low-confidence observability
hardening item, not a demonstrated privilege bypass or release-blocking issue.

### CLI paths, overwrite, and symlinks

The report writer creates the requested directory and writes a hostname/time
filename; snapshot and comparison writers use ordinary `open(..., "w")` or
`Path.write_text()`. These operations follow symlinks and may truncate an
existing destination. Same-second report names can also collide
(`syscheck.py:3093-3100`, `3696-3700`, `4276-4278`). The path is explicitly
chosen by the local caller, and no privileged wrapper or cross-user service is
present in source, so this is not classified as an externally actionable
arbitrary-write vulnerability in the current boundary. If deployments use a
shared or privileged output directory, atomic exclusive creation, ownership
checks, and no-follow semantics become a prerequisite.

Snapshot input is schema/type validated after `json.load()` but has no file-size
budget (`syscheck.py:3703-3763`), which is a secondary resource-hardening gap.

### Command injection, shell, PATH, environment, and locale

No CLI-controlled command injection was found. Normal commands are argument
lists and production shell fragments contain repository constants only. The
`_oom_collector_command()` helper interpolates its two arguments into a shell
string, so it should remain private to trusted constants; a future public or
untrusted caller would change this conclusion. All executable names are bare
(`journalctl`, `bash`, `grep`, package managers, etc.) and PATH is inherited
from `os.environ` (`syscheck.py:265-277`). A malicious PATH can replace tools,
but the source establishes no stronger privilege boundary; root/service
deployment is an unresolved operational question. Selected environment values
and locale are displayed in the report, not executed.

### Crafted logs and Raw → Observation → Evidence → Finding integrity

Kernel/journal text is treated as evidence, not as a proof of permanent device
failure. Restrictive patterns, own-entry filtering, status-aware collectors,
stable observation IDs, explicit classifications, and evidence/source IDs keep
the stages separated. NVMe rules match explicit timeout/reset/controller-down
events, map reset failure to P1 and timeout/reset to P2, and retain the highest
severity; they do not claim permanent SSD failure or data corruption. A crafted
line that reaches the kernel journal can intentionally trigger a matching
diagnostic, but no remote log-injection route or automated remediation consumer
is present. This is expected evidence sensitivity, not a command-injection
finding.

Generated Markdown interpolates some untrusted command, journal, mount, unit,
hostname, and environment text without Markdown escaping
(`syscheck.py:354-355`, `2751-2787`). Treat reports as untrusted data. If a
future renderer or agent consumes them, escaping and a non-executable content
boundary are required; no such consumer exists in this repository.

### Privilege, sudo, distro, and package-manager boundaries

No collector invokes `sudo`, installs/removes packages, changes services, or
mutates configuration. Permission failures are represented as restrictions.
Remediation strings containing `sudo` are static display text only and are not
executed. Distro detection selects static read-only package commands; unknown
distros fall back to the Arch configuration, which can produce incomplete
evidence but does not create an attacker-controlled command vector.

### Agent, Git, GitHub, and NeuralEngine boundaries

`AGENTS.md`, prompts, and prior review artifacts are workflow instructions/data;
the product does not read or execute them. No production code runs Git, pushes
to GitHub, calls a GitHub API, or publishes reports. `.git/config` contains the
SSH origin, but that is repository metadata, not an application network sink.
There is no runtime NeuralEngine import or Brain read/write path. The external
Brain was checked only through `neural status` (TRUSTED_CURRENT); targeted
security-history searches found no relevant record. Current repository source
remains authoritative, and no Brain write was performed. Unexpected Git
mutation and poisoned knowledge therefore remain operator/workflow risks, not
application findings.

## Validation

Fresh read-only validation completed on the current worktree:

| Check | Result |
|---|---|
| `ruff format --check .` | PASS — 4 files already formatted |
| `ruff check .` | PASS — all checks passed |
| `python3 -m pytest --collect-only -q` | PASS — 571 tests collected |
| `python3 -m pytest -q` | PASS — 571 passed in 0.55s |
| `git diff --check` | PASS |

The tracked working-tree delta at audit start was 4 files, 815 insertions, and
1002 deletions. Existing dirty paths were preserved; no staging, commit, push,
reset, restore, stash, checkout, branch, rebase, merge, or tag operation was
performed.

## Scope audit and blockers

- **Changed path:** `.agent-work/reviews/iteration-37-threat-model-security-boundary-assessment.md`
  only.
- **No fixes:** the resource, status, and filesystem concerns above are
  findings/recommendations only.
- **No blockers:** the degraded Codex Security worker capacity and TAC
  `not_granted` advisory status were recorded as limitations, not hidden.
- **Follow-up before new features:** bound subprocess/snapshot input, preserve
  failure status in all security-relevant collectors, and define output-path
  ownership/atomicity for any shared or privileged deployment.

## NeuralEngine usage

- `neural status`: `TRUSTED_CURRENT` at
  `<REDACTED-PATH>`.
- Targeted searches for `linux diagnostic security Iteration 37` and
  `security diagnostic`: no relevant records.
- Brain writes: none.
