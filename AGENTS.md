# Protokflow

Protokflow is a token-driven UI prototyping toolkit with a pure Python core and dual MCP/ASGI adapters based on the `DESIGN.md` standard.
It enables AI agents and engineers to batch-generate UI candidates, hot-reload token tweaks in sub-16ms browser previews, and export production-ready React/Tailwind components.

## Agent Source of Truth

- `AGENTS.md` is the repository instruction source of truth. `CLAUDE.md` is a symlink to it; never edit `CLAUDE.md` directly.
- `.agents/skills/` is the skill source of truth. `.claude/skills/` is a symlink to it; never edit the Claude path directly.

## Release Status: Pre-release

This project has not shipped a public release yet — there are no external API consumers and no production data to preserve. Until this section is removed at v1.0 launch:

- **No backward compatibility required.** Do not add deprecated aliases, compatibility shims, feature flags for old behavior, or versioned API paths just to preserve old call signatures/schemas/endpoints. Rename, restructure, or delete freely when it improves the code.
- **Prefer the correct shape over the incremental one.** If a refactor reveals a better structure (module boundaries, function signatures, DB schema), make the change directly rather than layering a compatibility path around the old one.
- **Still non-negotiable:** write/update tests for changed behavior, keep `ruff check`/`ruff format` clean, maintain database schema consistency and indexing logic, and confirm the blast radius of a change (callers, related tests) before landing it.
- Scope changes to what the task actually needs — "pre-release" justifies removing dead weight the task touches, not unrelated opportunistic rewrites.

## Language Set
- Language: Python >= 3.14
- Package Manager: `uv` (with `pyproject.toml` and `uv.lock`)
- Protocols & Frameworks: MCP (Official Python SDK / FastMCP stdio & SSE), FastAPI & Starlette, Pydantic 2.x
- Database & ORM: SQLite (`aiosqlite`) via SQLAlchemy 2.x (asyncio)
- CLI & Templating: Cappa (CLI commands), Jinja2 (template rendering), PyYAML
- Styling & Linter: Ruff (for linting and formatting), pre-commit

## Commands

- Install dependencies: `uv sync`
- Run dev server (FastAPI): `uv run python backend/run.py`
- Run MCP server: `uv run protokflow mcp`
- Run CLI commands: `uv run protokflow <subcommand>` (e.g., `uv run protokflow --help`)
- Lint code: `uv run ruff check` (pre-commit hook configured)
- Format code: `uv run ruff format` (pre-commit hook configured)
- Run tests: `uv run pytest` (runs in parallel using `pytest-xdist` with `-n 4` by default; use `uv run pytest -n 0` to run sequentially/serial)

## Documentation
- Knowledge Store: A searchable database of documented solutions exists in `docs/solutions/`, organized by categories (e.g. `architecture-patterns/`, `best-practices/`) with frontmatter metadata (`module`, `problem_type`, `tags`). Relevant when implementing features, debugging issues, or making technical decisions in previously documented areas.
- Shared Vocabulary: `CONCEPTS.md` (repo root) defines the project's domain vocabulary (entities, named processes, status concepts with project-specific meaning). Relevant when orienting to the codebase or discussing domain concepts.
