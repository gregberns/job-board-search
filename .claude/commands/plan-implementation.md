# Plan Implementation

Break specs into implementation beads, review the breakdown, and prepare for execution.

## When to Use

After specs exist in `specs/` and a plan exists in `plans/{name}/`, use this procedure to create the implementation task breakdown before writing any code.

## Step 1: Read All Relevant Specs

Read every spec referenced by the plan's `_plan.md`. Build a mental model of:
- Data types and their relationships (what depends on what)
- Package/module boundaries
- Cross-cutting concerns (behaviors that span multiple components)

## Step 2: Draft the Bead Breakdown

Create `plans/{name}/beads.md` with this structure:

### Dependency Graph
ASCII art showing which beads block which. Group into layers (L0, L1, L2...) where all beads in a layer can run in parallel once the previous layer completes.

### Inter-Package Import Map
Show which packages import which. Verify no import cycles. Identify leaf packages (no internal deps) — these are the foundation layer.

### Cross-Cutting Concerns
List behaviors that span multiple beads. For each:
- What it does
- Which beads must implement it
- Which spec section defines it

### Per-Bead Specification
Each bead gets:

```markdown
### Bead {N}{letter} — {title}
**Specs:** {spec files this bead implements}
**Package:** {Go package or file path}
**Deliverables:**
- Concrete list of types, functions, files to create
- Include function signatures where precision matters
**Tests:** What to test — spec compliance, not just code correctness
```

### Parallelization Plan
Table showing phases, which beads run in each phase, how many workers needed, and dependencies.

## Step 3: Bead Design Principles

- **One bead = one package or one command** — never split a package across beads, never combine unrelated packages
- **Leaf packages first** — types with no internal dependencies form L1
- **Engines before commands** — business logic packages (L2) before CLI commands (L3)
- **Test infra is its own bead** — shared test helpers are a prerequisite for command-level tests
- **Each bead is independently testable** — if it can't be tested in isolation, the boundaries are wrong
- **Explicit file ownership** — every source file belongs to exactly one bead. No two beads modify the same file.

## Step 4: Review the Breakdown

Spawn 3 review agents (via ntm), each with a different focus. Send each the full `beads.md` plus relevant specs.

### Reviewer 1: Spec Coverage
> "Review this bead breakdown against the specs. For each spec section, verify at least one bead covers it. Flag any spec requirements that no bead addresses. Flag any bead deliverable not backed by a spec."

### Reviewer 2: Architecture
> "Review this bead breakdown for architectural soundness. Check: no import cycles, correct dependency ordering, appropriate package boundaries, cross-cutting concerns properly assigned. Flag any structural issues."

### Reviewer 3: Parallelization
> "Review the parallelization plan. Check: dependency graph is correct (no bead runs before its deps), load is balanced across workers, no unnecessary serialization. Suggest improvements."

### Process the Reviews
- Collect all findings
- Fix legitimate issues in `beads.md`
- Document reviewer disagreements and resolve them
- Note the review happened: "Revised after 3-agent review (spec coverage, architecture, parallelization)"

## Step 5: Create Beads in Tracker

```bash
# Create each bead as an issue
bd create "Bead 0: {title}" --label layer-0,scaffold

# Set up dependency chains
bd dep kerf-XXX --blocks kerf-YYY
```

Verify with `bd ready` that only the correct beads (L0) are unblocked.

## Step 6: Update the Plan

Add to `_plan.md`:
```markdown
## Implementation Beads

See [beads.md](beads.md) for the full implementation task breakdown — {N} beads across {M} layers, with dependency graph and parallelization plan.
```

## Output

After this procedure:
- `plans/{name}/beads.md` exists with full breakdown
- Beads are created in `bd` with dependency chains
- `bd ready` shows only L0 beads as unblocked
- Ready to proceed with `implement-beads` procedure
