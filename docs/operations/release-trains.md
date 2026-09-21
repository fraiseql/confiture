# Release Trains

Confiture spends a version number when a change is **whole**, not when a pull
request merges. Every change still lands on `main` as its own pull request with
every gate green; what the train decides is when those merged changes become a
release a consumer can resolve.

## Why trains

confiture's consumers upgrade on purpose. fraisier lifts its confiture cap in a
release of its own, on a green suite; printoptim_backend pins a minor line and
moves it after measuring the build it produces. A version every few days asks
each of them to re-verify a moving target, and a release that carries half of a
restructuring ships two models of the same thing at once.

So a release is cut when a **train's thesis is whole**: when the one sentence the
train exists to make true is true of the code on `main`. A train is a sequence of
pull requests with that one thesis; the last pull request whose gates were green
is where the train is cut. Unfinished work does not block the tag — it moves to
the next train.

## The current trains

| Train | Version | Ships when |
|-------|---------|------------|
| One model | 1.15.0 | the parse side and the live side of a schema produce the same model, and drift on a freshly built database is empty by construction |
| One pipeline | 1.16.0 | the migrator applies every migration through one layered pipeline, and every command's success JSON carries the envelope its published schema declares |
| One platform | 1.17.0 | the model and the change set are one public, versioned seam that downstream tools build on, pinned by a contract test |

Between trains, `main` may carry merged work that no release contains. A fix a
consumer needs sooner ships as a patch on the previous minor, cut from its tag.

## What a train may change

**JSON envelopes only grow.** A key a consumer reads is never removed, renamed or
retyped within 1.x; a train may add keys. Additive is not free: most published
schemas declare `additionalProperties: false` at the root, so a new top-level key
is an edit to the schema, to its copy under `docs/reference/json-schemas/`, and
to the schema tests — in the same pull request that emits it.

**Exit codes stay 0..8.** The integers and their semantic classes are frozen
(see [Exit codes](../reference/exit-codes.md)). A new symbolic error code maps onto
an existing integer, and changes the `--exit-codes-json` payload that
fraisier-core vendors; the pull request that adds it says so.

**A published enum does not shrink.** A member that cannot be emitted yet is kept,
documented and filed.

**The consumer surface is a test.** The symbols fraisier and printoptim_backend
import, the call shapes they rely on, and the command lines they run are pinned
in `tests/contract/`, each row naming the consumer file that depends on it.
Removing one is a deliberate edit that names who it breaks.

## Rollback

A train that has to be withdrawn is withdrawn **as a tag**, never by reverting
pull requests on `main`:

1. yank the release on PyPI;
2. delete the GitHub release;
3. if a consumer needs a fix meanwhile, ship the previous minor as a patch from
   that minor's tag.

Reverting is never the tool, because the pull requests inside a train are not
independently revertible: a later one routinely deletes what an earlier one
introduced. The consumers' version floors are what make a yank safe — a range
that pins a floor and a cap resolves, after the yank, to exactly what it resolved
to before the release.
