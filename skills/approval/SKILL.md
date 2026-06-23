---
name: approval
description: Heavy mode HITL approval gate. Human reviews critical changes (auth, billing, migration, credentials) before verification.
---
# Approval — Human Review Gate

Triggered automatically in heavy mode for sensitive changes. The human must explicitly approve, reject, or request modifications before the pipeline continues.

## When It Triggers

Heavy mode activates when changes touch sensitive keywords:
- auth, authentication, login, password, session
- billing, payment, subscription, pricing
- migration, data-migration, schema-change
- credential, secret, token, api-key
- role, permission, rbac, access-control

## Exit Paths

| Decision | Action |
|----------|--------|
| approve | Advance to VERIFY |
| reject | FAILED — task stopped |
| modify | Return to IMPLEMENT with feedback |

## Review Checklist

- [ ] Change is scoped to the task definition?
- [ ] No credential/token leakage in diff?
- [ ] Backward compatible?
- [ ] Tests cover the change?
- [ ] Migration has rollback plan?
