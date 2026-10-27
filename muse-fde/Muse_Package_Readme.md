# Muse FDE Operational Investigation Knowledge Package

**Prepared:** 2026-10-26  
**Purpose:** Ground Meta Muse Spark in the proposed Operational Investigation Assistant design. This is an independent domain reference and prompt contract, not a deployed model or an actual enterprise knowledge system.

## Contents

- `Muse_FDE_Knowledge_Base_v1.md` — **model-facing domain knowledge**; safe to read in an authorized development session; no sealed benchmark labels.
- `Muse_FDE_System_Instructions_v1.md` — **application model instruction template**; use as trusted system/developer message, not as a user attachment.
- `Muse_FDE_Response_Schema_v1.json` — **proposed structured response schema** for model output; application-side checks still mandatory.
- `FDE_Private_Evaluation_Blueprint_v1.md` — **evaluator-only**, distributed separately; **never upload to Muse or make available to the model**.

## Safe setup

1. Use `muse-spark-1.3` Standard mode after validating current provider and competition terms. Keep credentials server side.
2. Load the system instructions as trusted instructions; load the KB as contextual reference. For repeat API use, you can store the KB in your application's approved own retrieval layer or embed it directly in the context. Do not assume file upload automatically creates searchable, permanent model memory.
3. Provide only the scoped synthetic case artifacts and allowed tools for each session.
4. Enforce access checks, literal span verification, typed numeric queries, prediction locks, experiment reveal and final decision approvals in application code.
5. Validate schema **and** claim semantics after every model response. The response schema alone does not make a claim verified.
6. Keep private evaluator instructions, gold labels, sealed data and test-case answer keys on a separate server-controlled path, not in the model context or public client bundle.

## Meta API pointers (as of 2026-10-26)

- Overview: https://dev.meta.ai/docs/overview
- Tool calling: https://dev.meta.ai/docs/tool-calling
- Structured output: https://dev.meta.ai/docs/structured-output
- Files: https://dev.meta.ai/docs/file-handling

Meta documents reusable PDF/image/video uploads via Files API and `input_file` blocks, alongside structured responses and function calling. A Markdown knowledge base is best used as explicit textual context in your application; don't assume that uploading a Markdown file, by itself, provisions a retrieval service. For a PDF rendition for `input_file`, render this KB to PDF separately if needed.

## Separation of concerns

The long-term commercial thesis includes protected company workspaces, approved precedent learning, full outcome contracts and deployment integrations. Those are **roadmap**, not v0.1 implementation claims. This package does not grant use of previously authored book text, proprietary designs, private prompts, company data, or a commercial product name.

Competition acceptance, project-switch permission, waiver/license terms, repo visibility and commercial naming remain legal/administrative gating questions outside this knowledge package.
