# Balanced development subsets for the three-hour preset

The four `*-balanced-N.txt` files per domain are disjoint development panels of three
questions each. All candidates, the original skill, and controls use all four panels.
These are development inputs, never final held-out tests. The existing Health and HLE
holdout files are unchanged and excluded from sampling.

HLE panels each contain one Chemistry, Computer Science/AI, and Engineering question.
Health panels each contain one context-seeking, emergency-referral, and health-data
question. Health candidates were drawn from `health-dev.txt`; HLE candidates were
drawn from available task directories outside `hle-holdout.txt`.

Selection used sorted task IDs within each group, shuffled with Python's
`random.Random(f"42:{domain}:{group}:balanced")`, taking four tasks per group and
placing one in each panel. Group labels came exclusively from HLE's `category` and
Health's `theme:` tags. No answer or rubric scores were used for selection. The
checked-in group JSON files contain only task IDs and these labels.

Promotion uses mean raw reward over the union of the panels. Balanced panels give
equal weight to the three groups; their score is not a population-weighted estimate
of the full benchmark. Per-group and per-panel reports expose tradeoffs, while the
separate final holdout provides the unused evaluation sample.
