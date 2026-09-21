# fraiseql-confiture-pggit

pgGit branching and multi-agent coordination for [confiture](../../README.md), as a
plugin: `confiture branch …`, `confiture coordinate …`, and
`confiture generate from-branch | preview | diff`.

It lived inside confiture until 1.16. It registers through confiture's
`confiture.plugins` entry-point group, so once it is installed every spelling above
works as it did:

```bash
uv pip install -e plugins/fraiseql-confiture-pggit   # from confiture's repository
confiture branch list
```

pgGit is a PostgreSQL extension for **development and staging** databases; never
install it on production. Nothing here is published yet.

- [Multi-agent coordination guide](docs/multi-agent-coordination.md)
- [How coordination works](docs/multi-agent-coordination-architecture.md)
- [A walkthrough of two agents](examples/multi-agent-workflow/README.md)

Its tests run in confiture's CI, against confiture's test database:

```bash
uv run --no-sync pytest plugins/fraiseql-confiture-pggit/tests
```
