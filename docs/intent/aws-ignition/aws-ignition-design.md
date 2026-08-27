---
parent: high-level-design
prefix: IGNITE
---

# AWS Ignition

## Context and Design Philosophy

The ignition switch is the on-demand trigger for `aws-deploy`'s stopped EC2 instance: an AWS Lambda function, exposed via a Function URL, that starts the instance and optionally resizes it first. Its whole job is turning an HTTP hit into a safe `ec2:StartInstances` (and optional `ec2:ModifyInstanceAttribute`) call — it owns no application logic beyond that and no state of its own.

This leaf owns only that request-handling logic (`ignition/handler.py`). The Lambda's deployment mechanics — IAM role/policy, the function resource itself, the Function URL — are provisioned by `aws-infra`'s Terraform, which packages this leaf's `ignition/handler.py` unmodified.

## Request Handling

The function reads `size` from the request's query string, defaulting to `t4g.small` when absent. The allowed set is a strict whitelist — `t4g.small`, `t4g.medium`, `t3.small`, `t3.medium` — validated **before** any AWS call. An invalid size returns HTTP 400 immediately; the function never attempts to start the instance with an unvalidated size.

## Resize-then-Start

For a valid size, the function attempts `modify_instance_attribute` first, then unconditionally calls `start_instances`. The resize call is expected to fail in two ordinary cases — the instance is already running (AWS rejects instance-type changes on a running instance), or the requested size crosses the `t3`/`t4g` architecture boundary from the instance's current family — and both are caught and treated as "size unchanged," not aborted. The instance still starts. This mirrors `aws-deploy`'s architecture-lock constraint: the Lambda's whitelist prevents an obviously-wrong request from a client, but the actual `t3`↔`t4g` boundary enforcement is AWS's own (the call fails server-side); this function's whitelist and AWS's own rejection are two independent layers, not one relying on the other.

## Response Contract

A valid request returns HTTP 200 with a body naming the outcome (resized-and-booting, or unchanged-and-booting). An invalid `size` returns HTTP 400 naming the allowed values.

## Decisions & Alternatives

| Decision | Chosen | Alternatives Considered | Rationale |
|---|---|---|---|
| Size whitelist enforcement point | Server-side, in the Lambda, before any AWS call | Trust the caller / let AWS reject invalid types | AWS's own rejection for cross-architecture resize is a generic API error, not a clear "here are your valid choices" message; validating first turns a silent/cryptic failure into an explicit 400. |
| Resize failure handling | Swallow and proceed to start | Abort on resize failure | A resize failure (already running, or same-family no-op) is not a request failure — the user's actual goal ("get the server up") is still achievable. |
| Instance identification | `INSTANCE_ID` environment variable | Hardcoded in function body | Keeps the deployed instance ID out of source control; the function code itself is instance-agnostic. |

## Open Questions & Future Decisions

### Resolved

1. ✅ `docs/gemini/sample/switch_instance_type.py` is an earlier draft (small/medium-only sizing, hardcoded instance ID, no `t3` option) — superseded by the `MasterGuide` version this leaf specs against. It is left in `docs/gemini/sample/` as historical reference, not implemented.

## References

- `docs/high-level-design.md`
- `docs/gemini/initial-survey.md` § 6 (The Auto-Scaling "Ignition Switch")
- `docs/intent/aws-deploy/aws-deploy-design.md` — the `t3`/`t4g` family lock this leaf's whitelist is derived from
- `docs/intent/aws-infra/aws-infra-design.md` — provisions this leaf's IAM role, Lambda function, and Function URL, packaging `ignition/handler.py` unmodified
