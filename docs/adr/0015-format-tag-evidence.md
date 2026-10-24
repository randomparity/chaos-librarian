# 0015: Supported format-tag evidence

## Status

Accepted, operator-approved on 2026-10-24 for #246.

## Context

Metadata-edit journals preserve requests, but ProbedMedia omits retained format
tags. Consumers need actual evidence without mistaking an omitted measurement
for an absent tag, or tool-generated encoder strings for authored metadata.

## Decision

Add optional `format_tags` to ProbedMedia. The owned probe emits lowercase
`title` and `year` keys with exact string values; an empty map means neither
exists, null means unreported. Compare these two keys only when both sides
supply evidence. Preserve empty strings separately from absent keys.

## Consequences

Embedding schemas are versioned and regenerated. Existing generic edits remain
available, but only the documented bounded MKV corpus claims retained-output
proof. New supported keys require their own evidence and contract decision.

## Considered & rejected

- Dedicated title/year attributes. judgment: a map represents key absence and
  present-empty naturally without multiplying fields.
- Compare every raw format tag. judgment: encoder/tool metadata is outside the
  authored metadata criterion and adds unstable comparisons.
- Journal requests alone. verified: `sed -n '232,249p'` on probe.py at commit
  62451dff shows format tags are discarded; requests cannot prove retained bytes.
