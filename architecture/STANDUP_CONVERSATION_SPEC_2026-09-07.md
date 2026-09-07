# Three-way standup: the Founder, the trading AI, and Claude — spec, 2026-09-07

Founder-directed. Written before building so we are building the same thing.

## What he asked for, in his words

* "a morning stand up call daily to talk about what chatgpt needs, and gaps or items that need
  fixing. real time troubleshooting of issues through dialogue"
* "happy for Claude and chatgpt to speak to each other as well"
* "I would want to be able to interrupt as well if needed. the conversation should basically be
  free flowing"
* "there may be times I explore a topic or item in the conversation with Claude for example
  while chatgpt listens after which it also joins in if asked, and likewise for me with chatgpt"
* "there needs to be a separate button or way of triggering the conversation with both chatgpt
  and Claude and then also ending it"
* "maybe have a way of just chatting with chatgpt or Claude separately as well"
* Writes hand over to Claude Code (me, in the terminal) once a path is agreed.

## The one correction that shapes the whole design

The Claude in the app is NOT the Claude in the terminal. It is an API call: it will have the
conversation and whatever tools we give it, and none of this session's context, no repo
checkout, no deploy access.

That matters because on 2026-09-06 the trading AI raised four defects and THREE were artefacts
of the census it had been handed rather than real faults. It hedged them correctly and was
right to. A participant that cannot check anything contributes plausible guesses, which is the
exact failure mode this project keeps having to correct.

So the split is not "Claude is trusted, ChatGPT is not". It is:

| | Who | Why |
|---|---|---|
| **Read** — search code, read a file, query the database | Both, in-conversation | Without it neither can check a claim, and the conversation is opinions |
| **Write** — edit code, deploy | Claude Code only, after the conversation | Not because a second Claude double-checks: because the write path carries tests, a production check, and a deploy confirmation that a flowing conversation does not |

The handoff is only worth anything if the implementer VERIFIES THE PREMISE rather than typing
up what was agreed. Stated here so it can be held to.

## Modes

Three, chosen before the conversation starts and endable at any time:

1. **Ask the trader** — the existing behaviour, unchanged.
2. **Ask Claude** — same shape, Claude instead.
3. **Standup** — both present. Both receive the full transcript including each other's answers.

## Turn-taking

* **Addressed by name.** "Claude, why is that slow?" routes to Claude. No name: whoever spoke
  last continues, or both answer a fresh topic.
* **One may listen while the other is explored**, and join when invited. Falls out of both
  always receiving the transcript while only the addressed one replies.
* **They may talk to each other**, bounded by a turn budget and a stop rule: stop when you have
  agreed, or when you have stated clearly where you disagree. Do not fill silence. Disagreement
  is a good outcome -- it says where to look.
* **The Founder can interrupt at any point.** Speaking cuts playback.

## What the read tools are

The Render container already holds both halves, so this is small:

* `COPY src ./src`, `governance`, `knowledge` are on disk at `/app`
* the process already has the production Postgres connection

So: search the code for a pattern; read a file; run a READ-ONLY query. The same three things
Claude Code used all day on 2026-09-06.

NOTE, and it is a real limit: the container carries `src`, `governance` and `knowledge` only.
No `tests/`, no `architecture/`, no git history. So app-Claude can read the code as deployed
but cannot read the test suite, the plans, or why a line was written. Worth fixing later by
copying more into the image; worth stating now so nobody assumes otherwise.

## Interruption, honestly

Interrupting by TAPPING works with what exists: a tap stops playback and starts recording.
Talking OVER a reply without touching the phone needs the realtime speech-to-speech API, which
means a native WebRTC module and a full rebuild rather than an over-the-air update.

The Founder has unlimited data and home wifi, so the ~8 MB/minute is not the obstacle it was.
Sequence: build the conversation first on tap-to-interrupt; if waiting for a turn to end proves
annoying in practice, the realtime path is then a known, costed change rather than a guess.

## Cost

Claude Opus 5 is $5/1M input, $25/1M output. A standup with tool calls that read a few files is
plausibly 30-60K input tokens, so pennies per conversation. Prompt caching applies to the
stable system prompt. Not a constraint at this volume; worth re-measuring if standups become
long or frequent.

## Blocker

**There is no ANTHROPIC_API_KEY.** The Founder must create one at console.anthropic.com and it
must live on the server, never in the app -- the same rule the OpenAI key already follows.

## Build order

1. Read tools on the server (search / read file / read-only query). Without these the
   conversation is opinions, so this is first, and it is useful to the existing trader too.
2. A Claude endpoint on the server, key server-side, tool loop wired to (1).
3. Routing and modes; both receive the transcript, the addressed one replies.
4. Mobile: mode selector, start/end, interrupt.
5. The agreed-actions write-out that Claude Code picks up.
