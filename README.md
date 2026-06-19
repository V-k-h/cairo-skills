# cairo-skills

Claude Code / Claude Agent skills for Cairo development.

## Skills

### [`cairo-coding`](cairo-coding/SKILL.md)

Rules and patterns for writing efficient **and** safe Cairo — loops, modular
arithmetic, limb splitting/assembly, modular reduction, storage packing, Poseidon
hashing, `felt252`/`u128`/`u256` conversions, and `BoundedInt` bounds. Every
optimization is gated behind explicit *equivalence invariants* so rewrites improve
gas/step cost without changing semantics.

Bundled tooling: [`scripts/bounded_int_calc.py`](cairo-coding/scripts/bounded_int_calc.py)
computes `BoundedInt` result bounds for `add`/`sub`/`mul`/`div`.

## Installing a skill

A skill is a directory whose entry file is `SKILL.md`. Drop it under either:

- **Personal (all projects):** `~/.claude/skills/`
- **Project-scoped:** `<project>/.claude/skills/`

```bash
# Personal install of cairo-coding
git clone https://github.com/V-k-h/cairo-skills.git
cp -R cairo-skills/cairo-coding ~/.claude/skills/
```

Claude discovers the skill by its frontmatter `description` and invokes it when the
task matches.
