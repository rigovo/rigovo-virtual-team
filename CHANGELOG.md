# Changelog

All notable changes to this project will be documented in this file.

This project uses [Semantic Versioning](https://semver.org/) and [Conventional Commits](https://www.conventionalcommits.org/).

## [0.1.0] - 2026-02-24

### Added

- Multi-agent pipeline with LangGraph orchestration (plan, code, review, gate)
- 6 agent roles: planner, backend, frontend, reviewer, security, devops
- Rigour integration with 23 AST quality gates + Fix Packet auto-retry
- Intelligent project detection (`rigovo init`) — language, framework, monorepo
- Budget controls with per-task and monthly cost limits
- Human-in-the-loop approval gates (after planning, before commit)
- SQLite persistence for tasks, costs, audit trail, memory
- 16 CLI commands via Typer (run, init, doctor, teams, agents, history, costs, etc.)
- Layered configuration: built-in defaults → rigovo.yml → rigour.yml → .env → env vars → CLI flags
- CI mode with JSON output (`rigovo run --ci`)
- 261 tests across domain, application, infrastructure, and CLI layers
- Rigour score: 73/100 (AI Health 75, Structural 98)
