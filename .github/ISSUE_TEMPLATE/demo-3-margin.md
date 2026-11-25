---
name: "Demo 3: Add margin_required(units, price, leverage)"
about: "The PR adds margin_required to sample-app/pricing.py with tests."
title: "Add margin_required(units, price, leverage)"
---

We need the margin a position ties up: `units * price / leverage`, rounded to 2 decimals.

- `leverage` must be greater than 0, otherwise raise `ValueError`.
- `units` and `price` must not be negative, otherwise raise `ValueError`.

Add it to `sample-app/pricing.py` with tests.
