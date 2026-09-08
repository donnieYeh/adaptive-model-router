# DECISION_FLOW.md

## Minimal interaction

Ask only when missing:

1. 当前额度：吃紧 / 正常 / 宽松
2. 等待时间：可以多等 / 正常 / 尽量快

No quality-preference question.

## Semantic output

Luna XHigh chooses ARC1/ARC2/ARC3 *bands*, not exact scores.

Example:
`A0 / A3 / A0`

The router maps A3 ARC2 to `[45,65]`.

Quota pressure selects:
- tight: 45
- normal: 55
- loose: 65

## Deterministic pipeline

`Band → requirement → HOLD → CCI/time/headroom → Pareto → representative options`

### Automatic result
Use when one representative candidate remains.

### User choice
Use when Economy and Fast/Headroom are genuinely different nondominated points.

The user should see concrete trade-offs, not a hidden utility calculation.
