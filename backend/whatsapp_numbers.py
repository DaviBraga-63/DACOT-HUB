"""Brazilian telephone formatting; validity is not proof of ownership.

This module does not authorize a destination. Authorization is the audited
binding performed by a super administrator after external verification.
"""

import re


_BRAZILIAN_DDDS = frozenset(
    "11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 "
    "41 42 43 44 45 46 47 48 49 51 53 54 55 61 62 63 64 65 66 67 "
    "68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 "
    "94 95 96 97 98 99".split()
)


def normalize_brazilian_number(value: str) -> str:
    """Return an E.164-format Brazilian number, or raise ValueError.

    This checks number structure, not assignment, WhatsApp availability, or
    the identity of its owner. Both mobile and landline numbers are accepted.
    """
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9 ()\-.]+", value.strip()):
        raise ValueError("Número de WhatsApp inválido")
    number = value.strip()
    digits = re.sub(r"\D", "", number)
    if number.startswith("+"):
        if not digits.startswith("55"):
            raise ValueError("Informe um número brasileiro")
        digits = digits[2:]
    elif len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    if len(digits) not in (10, 11) or digits[:2] not in _BRAZILIAN_DDDS:
        raise ValueError("Número de WhatsApp inválido")
    subscriber = digits[2:]
    if (len(subscriber) == 9 and subscriber[0] != "9") or (
        len(subscriber) == 8 and subscriber[0] not in "2345"
    ):
        raise ValueError("Número de WhatsApp inválido")
    return "+55" + digits


def mask_brazilian_number(value: str) -> str:
    """Mask an already normalized number without revealing the full number."""
    number = normalize_brazilian_number(value)
    return f"+55 ({number[3:5]}) {'*' * (len(number) - 9)}{number[-4:]}"
