"""Open the demo issues on TARGET_REPO.

    uv run python scripts/seed_issues.py            # open them, unlabelled
    uv run python scripts/seed_issues.py --label    # and hand them to the implementer at once
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory import config  # noqa: E402
from factory.github import GitHub  # noqa: E402

ISSUES = [
    (
        "Short positions show the wrong sign in P&L",
        "`position_pnl` returns a profit when a short (`side=\"sell\"`) position is losing money, "
        "and a loss when it is winning.\n\n"
        "Example: sell 10,000 EURUSD at 1.1000, current quote 1.1050/1.1052. "
        "Closing a short buys at the ask (1.1052), so the result should be -52.00, "
        "but `position_pnl` returns 52.00.",
    ),
    (
        "Spread and pip value are 100x off for JPY pairs",
        "For pairs quoted in JPY (USDJPY, EURJPY, ...) a pip is 0.01, not 0.0001.\n\n"
        "`spread_in_pips(Quote(\"USDJPY\", 150.100, 150.115))` returns 150.0 and should return 1.5. "
        "`pip_value` has the same problem. Use a pip size of 0.01 when the quote currency "
        "(the last three letters of the pair) is JPY.",
    ),
    (
        "Add margin_required(units, price, leverage)",
        "We need the margin a position ties up: `units * price / leverage`, rounded to 2 decimals.\n\n"
        "- `leverage` must be greater than 0, otherwise raise `ValueError`.\n"
        "- `units` and `price` must not be negative, otherwise raise `ValueError`.\n\n"
        "Add it to `sample-app/pricing.py` with tests.",
    ),
]


def seed(gh: GitHub, label: bool) -> None:
    for title, body in ISSUES:
        issue = gh.create_issue(title, body)
        if label:
            gh.add_labels(issue["number"], config.LABEL_IMPLEMENT)
        print(f"#{issue['number']} {title}  {issue['html_url']}")


def main() -> None:
    rt = config.load()
    seed(GitHub(rt.github_token, rt.settings.repo), "--label" in sys.argv)


if __name__ == "__main__":
    main()
