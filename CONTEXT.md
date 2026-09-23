# Context

Glossary for this repository. Terms only. No implementation detail.

## Marketplace

A listing of packages that a user adds once, then installs from by name. A user
adds one with `apm marketplace add <source>`. The registration is per user and
per machine.

A marketplace is a discovery surface. It answers "what can I install?".

## Registry

An Artifactory-style or npm-style server that serves package artefacts. A project
declares one in its own manifest.

A registry is a resolution source. It answers "where do the bytes come from?".

This repository publishes a marketplace. It is not a registry. The two words are
not interchangeable, and APM's own documentation uses both.

## Package

The unit a user installs. Each package has its own manifest with a name and a
version. A package holds one or more primitives.

## Primitive

One piece of agent capability inside a package. The kinds are instructions,
agents, skills, prompts, commands, hooks, and MCP servers.

Not every agent supports every primitive.

## Target

An agent that a package can be delivered to, such as Claude Code or Codex. A
package declares which targets it supports.

## Compile

Turning the instructions primitive into the agent's root context file. It
produces `CLAUDE.md` for Claude Code and `AGENTS.md` for Codex. It touches no
other primitive.

## Install

Deploying every primitive other than instructions into the agent's own
directories.

Compile and install are separate steps with separate outputs. Saying "install"
when you mean "compile" hides which files change.

## Plugin

Claude Code's word for what APM calls a package.

Avoid this word in this repository. It names one agent's idea of the unit, and
this repository serves more than one agent. Use "package".

## Orchestrator

The role the main agent thread takes. It hands work to workers, keeps the
judgement, and checks what comes back.

## Worker

An agent that the orchestrator hands a piece of work to. It reports back to the
orchestrator, never to the user.

## Delegation

The act of the orchestrator handing one piece of work to a worker.

_Avoid_: dispatch, spawn

## Subagent

Claude Code's mechanism for running a worker.

Use this word only when you talk about Claude Code itself. For the concept, use
"worker".
