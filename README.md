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
  | `lastSuccessBuild`, `lastSuccessAt`, `lastSuccessName` | for a build that isn't ok, the job's last successful build, when it finished, and its name; empty when the digest hasn't seen one (it only knows those since it started) |

- [`data/meta.json`](https://raw.githubusercontent.com/iedame/nixkeeper-hydra/data/data/meta.json):
  which evaluation it is (`eval`), the nixpkgs commit Hydra evaluated
  (`revision`), when its page was read (`fetchedAt`), and how many jobs
  have each status (`counts`). A reader can compare `eval` with the newest
  on Hydra's [list of evaluations](https://hydra.nixos.org/jobset/nixpkgs/unstable/evals)
  to know whether the digest is current. (Not with `latest-eval`: that's the
  newest evaluation whose builds have all finished, often a day or more
  behind.)

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
