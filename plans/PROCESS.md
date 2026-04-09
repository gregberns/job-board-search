# Development Process

Every feature follows this pipeline. Each stage produces an artifact that is reviewed before the next stage begins.

## Commands

| Command | When | What it does |
|---------|------|-------------|
| `/spec <idea>` | Starting a new feature | Guides through problem space → decomposition → research → detailed spec → assembly |
| `/plan-implementation` | After specs exist | Breaks specs into implementation beads with dependency graph |
| `/implement-beads` | After beads are created | Executes beads with worker pairs (implementer + reviewer) in worktrees |
| `/spawn-workers` | Reference for orchestrator | How to spawn/manage ntm workers, agent-mail, monitoring |

## The Pipeline

```
/spec <idea>
  → Phase 1: Problem Space (conversational)
  → Phase 2: Decompose & Requirements (iterative)
  → Phase 3: Research (agent-driven)
  → Phase 4: Detailed Spec (per component)
  → Phase 5: Integration & Assembly
  → Commit spec

/plan-implementation
  → Read all specs
  → Draft bead breakdown (dependency graph, per-bead specs)
  → Review with 3 agents (spec coverage, architecture, parallelization)
  → Create beads in bd

/implement-beads
  → Spawn worker pairs (implementer + reviewer)
  → Execute beads layer by layer
  → Review loop per bead (implementer ↔ reviewer)
  → Merge to main, run tests
```

## When to Skip Stages

- **Bug fixes:** Skip /spec. Write a bead directly, implement, test.
- **Trivial changes (< 20 lines):** Skip everything. Just implement and commit.
- **Spec-only changes:** Skip implementation. Edit the spec, review, done.
- **Small features (1-2 beads):** /spec is still valuable but can be lighter — fewer research questions, combine phases.
