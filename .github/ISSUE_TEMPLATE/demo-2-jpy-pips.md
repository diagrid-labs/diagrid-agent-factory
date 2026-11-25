---
name: "Demo 2: Spread and pip value are 100x off for JPY pairs"
about: "The PR uses a 0.01 pip for JPY pairs in spread_in_pips and pip_value and adds tests."
title: "Spread and pip value are 100x off for JPY pairs"
---

For pairs quoted in JPY (USDJPY, EURJPY, ...) a pip is 0.01, not 0.0001.

`spread_in_pips(Quote("USDJPY", 150.100, 150.115))` returns 150.0 and should return 1.5. `pip_value` has the same problem. Use a pip size of 0.01 when the quote currency (the last three letters of the pair) is JPY.
