---
name: Never skip requested agents
description: When user requests multiple agents or phases, execute ALL of them. Never skip or shortcut.
type: feedback
---

When the user provides a multi-phase spec with explicit instructions to use agents, execute EVERY phase with agents as requested. Do not skip phases, summarize them as "already done," or shortcut the work. If the user asks for 7 phases, deliver 7 phases.

**Why:** User gave a detailed Fix 4 spec with phases 4A-4G and was frustrated that not all agents were launched and not all phases were fully built. Skipping work the user explicitly requested breaks trust.

**How to apply:** When a large spec is provided, launch parallel agents for independent work. If some phases are already partially done, fill the gaps — don't mark them complete without verifying and building what's missing.
