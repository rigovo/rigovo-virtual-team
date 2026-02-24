# Rigovo Teams — Product Specification

## Overview

Rigovo Teams is a composable AI engineering team platform. Users describe a task in plain English. The Master Agent classifies the task, assembles the right team of specialized agents, and delivers production-ready code — with every step verified through deterministic quality gates powered by Rigour.

## Core Value Proposition

Every task makes the system smarter. Not through fine-tuning an LLM — through accumulated structured knowledge via flat semantic memory that compounds across projects.

## Architecture Summary

- **@rigovo/cli** runs locally on the user's machine — reads/writes code, calls LLMs with user's API key, runs Rigour gates locally
- **Rigovo Cloud** hosts the brain — Master Agent orchestration, shared memory with semantic search, team management, audit trail, dashboard
- **@rigour-labs/core** runs locally as npm dependency — quality gates execute on user's machine, results sent to cloud as metadata

## Key Differentiators

1. Inter-agent quality gates — 24+ deterministic gates, structural verification not prompt tricks
2. Hallucination detection — hallucinated imports across 8 languages, phantom APIs, deprecated APIs
3. Agent isolation — Reviewer never inherits Coder's context or biases
4. Flat semantic memory — cross-project learnings surface by relevance, not scope rules
5. Full audit trail — every agent action logged, enterprise compliance ready

## Target Users

- Engineering teams using AI code generation who need verification
- Teams managing multiple projects who want institutional knowledge retention
- Enterprise teams requiring audit trails and compliance

## Phase 1 Scope (MVP)

- Master Agent: task classification, team assembly, memory retrieval
- Coder Agent: LLM code generation with Rigour self-check
- Reviewer Agent: full Rigour gate runner with Fix Packet generation
- CLI: `rigovo run`, `rigovo init`, `rigovo login`
- Memory: store and retrieve cross-project learnings
- Dashboard: live task view with agent conversation
