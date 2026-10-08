# nixkeeper-hydra

A digest of [Hydra](https://hydra.nixos.org)'s builds of nixpkgs master, for
[nixkeeper](https://github.com/iedame/nixkeeper): every job of the newest
evaluation with its newest finished build, its status, and the last time it
built successfully, in one small file kept up to date by a workflow.
nixkeeper reads it instead of asking Hydra about each of its packages' jobs
one at a time.

## The digest

On the `data` branch:

- [`data/builds.csv.gz`](https://raw.githubusercontent.com/iedame/nixkeeper-hydra/data/data/builds.csv.gz):
  one row per job on x86_64-linux, aarch64-linux and aarch64-darwin, sorted
  by attribute and platform:

  | Column | Meaning |
  |---|---|
  | `attr`, `system` | the job (`wesnoth`, `x86_64-linux`) |
  | `build` | its newest finished build: `https://hydra.nixos.org/build/<build>`. From the newest evaluation, or while its build there is still queued, from an earlier one (what Hydra's latest builds of the job say) |
  | `status` | `ok`, `failed` (the package's own failure), `dependency` (a dependency failed), `unfinished` (aborted, timed out, a limit exceeded, ...) or `queued` (a job new to the digest, not built yet) |
  | `finished` | when it finished (ISO 8601, UTC); empty when queued |
  | `name` | what it builds (`wesnoth-1.18.8`): master's version |
  | `lastSuccessBuild`, `lastSuccessAt`, `lastSuccessName` | for a build that isn't ok, the job's last successful build, when it finished, and its name; `lastSuccessAt` is `never` (the others empty) when Hydra says the job never succeeded; all empty while it isn't known yet (below) |
  | `blockedBy` | for a `dependency` build, which dependency failed: the nixpkgs attribute of its job (`python314Packages.python-ldap`), or its derivation's name when no job of that platform builds it (`source`, a download; `python3.12-anyio-4.14.2`); several space-separated; empty until its page is read (below) |

- [`data/meta.json`](https://raw.githubusercontent.com/iedame/nixkeeper-hydra/data/data/meta.json):
  which evaluation it is (`eval`), the nixpkgs commit Hydra evaluated
  (`revision`), when its page was read (`fetchedAt`), and how many jobs
  have each status (`counts`); `blocked`: how many dependency failures'
  blockers are known, and how many are still to read; `lastSuccess`: of
  the jobs that aren't ok, how many have a known last success, never
  succeeded, and are still to ask (below). A reader can compare `eval` with the newest
  on Hydra's [list of evaluations](https://hydra.nixos.org/jobset/nixpkgs/unstable/evals)
  to know whether the digest is current. (Not with `latest-eval`: that's the
  newest evaluation whose builds have all finished, often a day or more
  behind.)

- [`data/haskell-updates.json.gz`](https://raw.githubusercontent.com/iedame/nixkeeper-hydra/data/data/haskell-updates.json.gz)
  (about 125 KB): the same for the `haskell-updates` branch, where the
  Haskell team updates `haskellPackages` before merging into master (about
  every two weeks): its jobset's newest evaluation, each job's build there,
  status and name (the branch's version), with which evaluation and commit
  it is:

  ```json
  {"format": 1, "jobset": "nixpkgs/haskell-updates", "eval": 1829685,
   "revision": "4e9d3032...", "fetchedAt": "...", "builds": 8709,
   "counts": {"ok": 7777, "failed": 437, ...},
   "columns": ["attr", "system", "build", "status", "name"],
   "jobs": [["haskellPackages.Agda", "x86_64-linux", "347795412", "ok", "Agda-2.8.0.2"], ...]}
  ```

  Read on the same terms as master's (below); its page is small (about 350
  KB), and the jobset is evaluated when the branch changes, every few days.
  A run that can't read it keeps the last.

The `data` branch is `main` plus one commit with the digest: each run replaces
it, so no history piles up.

## How it's kept up to date

The "Digest" workflow runs hourly. It asks Hydra which evaluation is the
newest, one small request, and reads that evaluation's full page (all of
nixpkgs, a big one that takes Hydra a few minutes to make) only when it can
bring something new:

- a new evaluation;
- builds of the current one still queued: every 6 hours, for their results;
- otherwise once a day, for builds Hydra restarted.

Hydra evaluates master every 8 hours or so, and its builds take a day or
more to finish, so the page is read about four times a day. Each job is read
from every table of builds on the page (newly failing, still failing,
aborted, newly succeeding, new, still succeeding, unfinished).

A page with far fewer builds than nixpkgs has (cut short, or changed by
Hydra) isn't published: nixkeeper then asks Hydra itself, as it does without
the digest.

**Which dependency failed.** Hydra's "Dependency failed" doesn't say which;
the build's own page does, in its build steps, as
[zh.fail](https://zh.fail/) reads it. Each run reads the pages of the
dependency-failed builds it doesn't know yet, one a second, at most 1,500
and 40 minutes a run (about 1,300 the first time, then only the new ones a
new evaluation brings: a build Hydra doesn't redo keeps its id), whether
or not there's a new evaluation. `data/blocked.json` keeps what each
build's page said. A step's derivation is named by the job that builds it:
the build Hydra says the failure came from, when that job builds the same
derivation (it may be another package that needed it), else a job of the
same platform building a derivation of that name.

**When it last built.** The digest learns a job's last success by seeing
it succeed and then fail, so a job already failing when it started
(2026-10-04), or failing from its first build, had none: 4,805 jobs then.
Each run asks Hydra about those it doesn't know yet
(`/job/nixpkgs/unstable/<job>/latest`, the job's latest successful build),
one a second, at most 1,500 a run within the same 40 minutes, whether or
not there's a new evaluation. The answer goes into the row, which later
digests carry on, so each job is asked once; one that never succeeded says
`never`, so readers needn't ask Hydra either, and is remembered in
`data/last-success.json`, asked again only when Hydra builds it again.

## Running it

```bash
nix run . -- data
```

brings the digest in `data/` up to date (it reads the page only when due,
as above). `nix flake check` runs the tests and lint, `nix fmt` formats.

The idea, reading Hydra's evaluation page instead of asking about each job,
comes from
[nixpkgs-failure-notify](https://github.com/Sigmanificient/nixpkgs-failure-notify).

## License

MIT
