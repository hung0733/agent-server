# Hong Kong Chinese Q&A Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update `AGENTS.md` so all user-facing Q&A replies are explicitly required to use Hong Kong Chinese (`zh-HK`).

**Architecture:** This is a documentation-only change in the agent instruction layer. Add one dedicated communication-language rule near the front of `AGENTS.md`, keep the existing i18n section focused on product/system strings, and verify the new wording is unambiguous.

**Tech Stack:** Markdown, repository instruction files

---

### Task 1: Add the global communication-language rule

**Files:**
- Modify: `AGENTS.md`
- Reference: `docs/superpowers/specs/2026-03-28-hk-chinese-qa-design.md`

- [ ] **Step 1: Review the current instruction placement**

Read `AGENTS.md` and identify a position near the front of the document where a new language rule will be seen before lower-level implementation guidance. Keep the existing section order stable unless a small insertion is enough.

- [ ] **Step 2: Add the new section and rule text**

Insert a short section after `## Language and Framework Requirements` using wording equivalent to the following:

```md
## Communication Language
- All user-facing questions, answers, explanations, and general replies must use Hong Kong Chinese (`zh-HK`) by default.
- Only switch to another language when the user explicitly requests it.
```

Keep the wording direct and imperative so it reads as a hard rule rather than a preference.

- [ ] **Step 3: Verify the existing i18n section still has a separate purpose**

Re-read the `## Internationalization (i18n) Requirements` section and confirm it still describes application/system localization rather than conversational reply language. Do not duplicate the new communication rule there unless the document becomes ambiguous without it.

- [ ] **Step 4: Verify the final document content**

Confirm all of the following are true by reading the final `AGENTS.md`:

```text
1. The new `## Communication Language` section exists.
2. The rule explicitly applies to user-facing questions, answers, explanations, or replies.
3. The default locale is stated as `zh-HK`.
4. An explicit user request is the only stated reason to switch languages.
```

- [ ] **Step 5: Check git diff for the exact change**

Run:

```bash
git diff -- AGENTS.md
```

Expected: a small documentation-only diff showing the new communication-language section and no unrelated edits inside `AGENTS.md`.

## Self-Review

- **Spec coverage:** The plan covers the chosen approach from `docs/superpowers/specs/2026-03-28-hk-chinese-qa-design.md`, including insertion location, explicit `zh-HK` wording, separation from i18n rules, and final verification.
- **Placeholder scan:** No `TODO`, `TBD`, or undefined follow-up work remains.
- **Type consistency:** Terminology is consistent across the plan: `AGENTS.md`, `Communication Language`, and `zh-HK`.
