"""UK sorting code and account number modulus checking (Vocalink, for the Bacs and Faster Payments schemes).

The sorting code and the eight-digit account number form one fourteen-digit
number ``uvwxyz abcdefgh``. The modulus weight table names, for ranges of
sorting codes, one or two checks: ``MOD10`` and ``MOD11`` multiply each digit
by its weight and require the sum to be divisible by 10 or 11; ``DBLAL``
(double alternate) adds the individual digits of the products and requires
divisibility by 10. A sorting code outside every range cannot be checked and
is presumed valid. Numbered exceptions vary the checks:

1. add 27 to the double alternate total;
2 and 9. Lloyds euro accounts: when ``a`` is not 0 the first check uses one of
   two substitute weight sets (chosen by whether ``g`` is 9); if it fails the
   second check is made with the euro sorting code;
3. skip the double alternate check when ``c`` is 6 or 9;
4. the modulus 11 remainder must equal the two-digit number ``gh``;
5. substitute the sorting code from the substitution table, then check digit
   ``g`` against the modulus 11 remainder and ``h`` against the double
   alternate remainder;
6. a foreign currency account (``a`` in 4 to 8 with ``g`` equal to ``h``)
   cannot be checked;
7. when ``g`` is 9, zero the weights of ``u`` to ``b``;
8. check against a fixed substitute sorting code;
10 and 11. either check may pass; for the first, when ``ab`` is 09 or 99 and
   ``g`` is 9 the weights of ``u`` to ``b`` are zeroed;
12 and 13. either check may pass;
14. Coutts accounts: if the first check fails and ``h`` is 0, 1 or 9, drop
   ``h``, prefix a 0 and repeat the modulus 11 check.

Two checks for one sorting code must otherwise both pass. The weight table is
carried as ``rows``, one string per VALACDOS.txt line.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

Row = tuple[str, str, str, list[int], int | None]
EITHER_PASSES = {(10, 11), (12, 13)}


def parse_row(line: str) -> Row:
    """One weight table row, written as in VALACDOS.txt: start, end, method, fourteen weights, optional exception."""
    fields = line.split()
    exception = int(fields[17]) if len(fields) > 17 else None
    return fields[0], fields[1], fields[2], [int(w) for w in fields[3:17]], exception


def _rows(parameters: Mapping[str, Any], sort_code: str) -> list[Row]:
    code = int(sort_code)
    rows = (parse_row(line) for line in parameters["rows"])
    return [row for row in rows if int(row[0]) <= code <= int(row[1])]


def _total(number: str, weights: Sequence[int], double_alternate: bool) -> int:
    total = 0
    for digit, weight in zip(number, weights):
        product = int(digit) * int(weight)
        total += sum(int(c) for c in str(product)) if double_alternate else product
    return total


def _check(sort_code: str, account: str, row: Row, parameters: Mapping[str, Any], *, weights: Sequence[int] | None = None) -> bool:
    method, exception = row[2], row[4]
    weights = list(row[3] if weights is None else weights)
    a, c, g, h = (int(account[i]) for i in (0, 2, 6, 7))
    if exception == 3 and method == "DBLAL" and c in (6, 9):
        return True
    if exception == 6 and a in (4, 5, 6, 7, 8) and g == h:
        return True
    if exception == 8:
        sort_code = parameters["exception_8_sort_code"]
    if exception == 5:
        sort_code = parameters["substitutions"].get(sort_code, sort_code)
    if exception == 7 and g == 9:
        weights[:8] = [0] * 8
    if exception == 10 and account[:2] in ("09", "99") and g == 9:
        weights[:8] = [0] * 8
    number = sort_code + account
    total = _total(number, weights, method == "DBLAL")
    if exception == 1:
        total += parameters["exception_1_addend"]
    modulus = 11 if method == "MOD11" else 10
    remainder = total % modulus
    if exception == 4:
        return remainder == int(account[6:8])
    if exception == 5:
        digit = g if method == "MOD11" else h
        if remainder == 0:
            return digit == 0
        if method == "MOD11" and remainder == 1:
            return False
        return modulus - remainder == digit
    return remainder == 0


def _exception_2_weights(account: str, row: Row, parameters: Mapping[str, Any]) -> Sequence[int]:
    if account[0] == "0":
        return row[3]
    return parameters["exception_2_weights"]["g_is_9" if account[6] == "9" else "g_not_9"]


def is_valid(sort_code: str, account: str, parameters: Mapping[str, Any]) -> bool:
    """Whether ``account`` (eight digits) passes the modulus checks for ``sort_code`` (six digits)."""
    sort_code = sort_code.replace("-", "").replace(" ", "")
    if not (sort_code.isdigit() and len(sort_code) == 6 and account.isdigit() and len(account) == 8):
        return False
    rows = _rows(parameters, sort_code)
    if not rows:
        return True
    first = rows[0]
    if len(rows) == 1:
        if first[4] == 14:
            return _check(sort_code, account, first, parameters) or _coutts(sort_code, account, first, parameters)
        return _check(sort_code, account, first, parameters)
    second = rows[1]
    if first[4] == 2:
        if _check(sort_code, account, first, parameters, weights=_exception_2_weights(account, first, parameters)):
            return True
        return _check(parameters["exception_9_sort_code"], account, second, parameters)
    if (first[4], second[4]) in EITHER_PASSES:
        return _check(sort_code, account, first, parameters) or _check(sort_code, account, second, parameters)
    return _check(sort_code, account, first, parameters) and _check(sort_code, account, second, parameters)


def _coutts(sort_code: str, account: str, row: Row, parameters: Mapping[str, Any]) -> bool:
    if account[7] not in "019":
        return False
    return _check(sort_code, "0" + account[:7], row, parameters)


def evaluate(parameters: Mapping[str, Any], value: Any) -> Any:
    return is_valid(str(value["sort_code"]), str(value["account"]), parameters)
