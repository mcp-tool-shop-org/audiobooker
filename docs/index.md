# Documentation has moved

The audiobooker documentation lives at
**<https://mcp-tool-shop-org.github.io/audiobooker/>**.

That site is built from `site/` and deployed on every push, so it is the only
copy that can be stale for less than one commit.

| What you want | Where it is |
|---|---|
| Install and first audiobook | [Getting started](https://mcp-tool-shop-org.github.io/audiobooker/handbook/getting-started/) |
| Every CLI command and flag | [Reference](https://mcp-tool-shop-org.github.io/audiobooker/handbook/reference/) |
| Casting, review, rendering | [Usage](https://mcp-tool-shop-org.github.io/audiobooker/handbook/usage/) |
| Python API | [Architecture](https://mcp-tool-shop-org.github.io/audiobooker/handbook/architecture/) |
| Something went wrong | [Troubleshooting](https://mcp-tool-shop-org.github.io/audiobooker/handbook/troubleshooting/) |
| New to all of this | [Beginners](https://mcp-tool-shop-org.github.io/audiobooker/handbook/beginners/) |

## Why this directory is nearly empty

`docs/handbook.md`, `docs/index.md` and `docs/api-reference.md` were a second
documentation tree that nothing built and nothing linked to, and it had drifted
badly behind the one that ships:

| | old `docs/` | deployed site |
|---|---|---|
| CLI subcommands documented | 9 of 34 | 22 of 34 |
| Python constructors documented | 2 of 5 | 5 of 5 |
| Roadmap | listed BookNLP, voice suggestions and emotion inference as "planned milestones" for v1.1–v1.3 | — |

All three of those "planned" features shipped; the package is on 2.x. A reader
who found that page by browsing the repository on GitHub — which renders
`docs/` perfectly well whether or not anything deploys it — got a confident,
coherent, wrong answer, with no indication a better one existed.

Duplicated documentation does not stay duplicated. One copy gets maintained and
the other becomes a trap, and the trap is indistinguishable from the real thing
until you act on it. So there is one copy now, and this page points at it.
