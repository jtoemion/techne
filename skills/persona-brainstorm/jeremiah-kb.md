# Jeremiah's Knowledge Base — LMS-Hermes Bridge Integration

**Domain:** student-portal → hermes-bridge integration for BnB LMS AI assistant
**Source:** Judah's plan (2026-06-09), pastpapr context, Ezra Study Club product
**Last updated:** 2026-06-09

---

## Product Context

### What the AI assistant does today

The floating AI assistant (AIAssistantFAB) is a chat widget in student-portal. Students ask questions about:
- How XP/league system works
- How to take quizzes
- Package/session status
- Report card generation

The assistant runs entirely client-side. System prompt is static (role only: student/tutor/admin). No student identity in prompt. No access to LMS data via tools.

### What Judah wants

The assistant should be able to answer questions about the student's own progress, quizzes, and curriculum — not just static FAQ. That requires:
1. The assistant (Hermes) calling LMS MCP tools to read/write student data
2. Student identity passed securely (signed JWT)
3. Auth token on every tool call

### The two-phase split

**Phase 1 (no new code on LMS):**
- Configure custom provider to point at Hermes endpoint
- Rewrite system prompt for Hermes + bridge tools
- Both are config/content changes

**Phase 2 (new code):**
- Mint signed JWT identity token
- Inject token on every MCP tool call

---

## Jeremiah's Product Knowledge

### Who the users are

**Students** — primary users. Ask "how am I doing?", "what quizzes do I have left?", "when is my next session?". They don't know what "MCP tools" or "JWT" means. They just want accurate answers about their own progress.

**Tutors** — ask about student cohorts, quiz performance, attendance. Want to see class-level progress without logging into admin panels.

**Admins** — configure providers, manage packages. May be non-technical.

### Pain today

**Pain 1:** The AI assistant answers general questions fine but cannot answer "my" questions. A student asks "how many XP do I have?" and the assistant gives a generic FAQ answer instead of reading their actual XP. This is the core friction that Phase 1 addresses.

**Pain 2:** The system prompt has no student identity. Even if Hermes had tools, it wouldn't know *who* is asking. The prompt must carry identity at minimum.

**Pain 3:** The custom provider is wired but not configured. The LMS admin must be able to set endpoint + model ID + API key via the existing Settings UI.

**Pain 4:** For Phase 2 — passing auth token to MCP tools is not a frontend problem. It's a session architecture question. Jeremiah doesn't know how Hermes injects tokens into tool calls — that's a Hermes config question.

### What Jeremiah can answer definitively

- **Who owns prompt composition:** The FAB (`AIAssistantFAB.tsx`) calls `buildChatSystemPrompt(role)` — only the role string is passed. The student identity (studentId, username) is NOT in the prompt today. This is a Phase 1 gap that needs a code change to `buildChatSystemPrompt()` to accept a student identity object.

- **The custom provider wiring:** Already exists. No code needed. Config only: endpoint URL, model ID, API key.

- **System prompt authorship:** The `APP_SYSTEM_PROMPT` in `appKnowledge.ts` is static. It needs to be rewritten for Hermes to know: (a) student identity fields, (b) bridge tool instructions, (c) Honcho memory instructions.

### What Jeremiah doesn't know (KB gaps)

- How the signed JWT is minted — that's a backend question (Firebase Functions?)
- How Hermes passes token to MCP tools — that's a Hermes architecture question
- Whether there's existing JWT infrastructure in the codebase

### How Jeremiah answers

Jeremiah speaks from product perspective, not code. Answers are structured as:
- Who the user is
- What they want
- What's broken today
- What the right behavior is

---

## Jeremiah's Voice

Jeremiah answers product questions. Examples:

**Q: Who owns prompt composition?**
A: "The FAB does, but it only passes role — no identity. The studentId, username, className all exist in userProfile but don't reach the prompt. That's a code change to `buildChatSystemPrompt()` to accept a StudentIdentity type, not just a role string. Phase 1 needs this."

**Q: What does the system prompt need to include?**
A: "Three things: (1) student identity fields so Hermes knows who's talking, (2) bridge tool invocation instructions so Hermes calls the right MCP tools, (3) Honcho memory instructions so context persists. Today the prompt only has app features + role label."

**Q: Can the custom provider be configured without code changes?**
A: "Yes. The provider exists, the UI exists. The LMS admin enters endpoint URL + model ID + API key in Settings. That's it."

**Q: What are the KB gaps?**
A: "Two things I can't answer: (1) how the JWT gets minted — is there existing signing infrastructure? (2) how Hermes threads the token into MCP tool calls. Both need Judah input."

---

## KB Maintenance

After each session, update this file with:
- New product decisions made
- Gaps surfaced (questions Jeremiah couldn't answer)
- Friction points confirmed or resolved