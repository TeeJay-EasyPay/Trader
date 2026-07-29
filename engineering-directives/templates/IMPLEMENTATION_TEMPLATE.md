# [Directive Title] — Implementation Directive Template

## Project

AI Trader

## Directive Title

[Short, specific title for this implementation session]

## Objective

[One or two sentences describing what this session must accomplish and why it
matters to the platform's mission.]

## Current State

[What has already been built, verified, or completed. What this session
builds upon. Reference the implementation log and relevant reports rather
than restating them.]

## Governing Documents

- Constitution:
  `architecture/AI_TRADER_FOUNDING_PRINCIPLES_ARCHITECTURE_CONSTITUTION_v1.0.md`
- Governance documents: [list relevant files in `governance/`]
- Architecture documents: [list relevant files in `architecture/`]
- Implementation log: `governance/IMPLEMENTATION_LOG.md`

## Scope

[What is explicitly in scope for this session. What is explicitly out of
scope. Be precise about boundaries.]

## Required Review

Before modifying any code, review:

- [ ] Constitution
- [ ] Relevant governance documents
- [ ] Relevant architecture documents
- [ ] Implementation log / implementation history
- [ ] Current Git status and current branch
- [ ] [Any additional systems or documents specific to this directive]

## Implementation Requirements

[Concrete list of what must be implemented, integrated, or changed. Be
specific enough that completion is verifiable.]

## Safety Boundaries

Preserve:

- Constitution and governance;
- auditability;
- production safety;
- existing safety mechanisms (timeouts, guardrails, risk limits, broker
  permissions, etc.);
- evidence lineage;
- deterministic behaviour.

Never:

- replace production logic with mocks;
- hide failures;
- remove or weaken safety mechanisms;
- weaken testing.

## Testing Requirements

- [ ] Unit tests
- [ ] Integration tests
- [ ] Build validation / type checking / linting
- [ ] Regression tests
- [ ] Document passed / failed / skipped / blocked results

## Completion Criteria

[What "done" looks like for this directive. What must be true for the
session to be considered complete rather than partially done.]

## Required Deliverables

- Updated implementation log entry
- Updated architecture documentation (if applicable)
- Testing summary
- Completed work summary
- Remaining blockers (external dependencies, Founder decisions, production
  approvals only)
- Git branch, commits, and files modified

## Final Instruction

[Any closing instruction specific to this directive — e.g., stopping
conditions, autonomy expectations, or explicit approval gates.]
