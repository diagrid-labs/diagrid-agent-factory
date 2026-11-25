---
name: "Demo 1: Short positions show the wrong sign in P&L"
about: "The PR flips the sign for sell positions in position_pnl and adds a test."
title: "Short positions show the wrong sign in P&L"
---

`position_pnl` returns a profit when a short (`side="sell"`) position is losing money, and a loss when it is winning.

Example: sell 10,000 EURUSD at 1.1000, current quote 1.1050/1.1052. Closing a short buys at the ask (1.1052), so the result should be -52.00, but `position_pnl` returns 52.00.
