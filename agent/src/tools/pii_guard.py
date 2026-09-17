"""Rule-based check for personal data before a query leaves the system.

Deliberately not an LLM: rules are auditable and never send anything out.
"""

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PiiRule:
    name: str
    pattern: re.Pattern[str]


# Broad on purpose: a false positive only costs one approval click,
# a false negative leaks data.
RULES: tuple[PiiRule, ...] = (
    PiiRule("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    PiiRule("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){7,11}\d(?!\d)")),
    PiiRule("hkid", re.compile(r"\b[A-Z]{1,2}\d{6}\(?[0-9A]\)?", re.IGNORECASE)),
    PiiRule("card_number", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")),
    PiiRule(
        "money_amount",
        re.compile(
            r"(?:HK\$|US\$|NT\$|\$|£|€|USD|HKD|TWD|JPY)\s?\d[\d,]*(?:\.\d+)?"
            r"|\d[\d,]*(?:\.\d+)?\s?(?:港幣|港元|美元|美金|台幣|日圓|日元|元|萬)",
            re.IGNORECASE,
        ),
    ),
)


def check(query: str, personal_terms: Iterable[str] = ()) -> list[str]:
    """Return the names of every rule that matched; empty list means clean."""
    flags = [rule.name for rule in RULES if rule.pattern.search(query)]

    lowered = query.lower()
    # Term values are never echoed back, only the fact that one matched.
    if any(term.lower() in lowered for term in personal_terms if term.strip()):
        flags.append("personal_term")

    return flags
