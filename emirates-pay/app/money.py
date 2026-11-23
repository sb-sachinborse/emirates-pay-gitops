"""Money helpers.

All amounts are stored and calculated as integer fils (1 AED = 100 fils).
Never use floats for money: 0.1 + 0.2 != 0.3.
"""
from decimal import Decimal, InvalidOperation

FEE_BPS = 50          # 0.50% transfer fee ...
MIN_FEE_FILS = 100    # ... with a minimum of AED 1.00
VAT_PERCENT = 5       # UAE VAT, charged on the fee

TOPUP_MAX_FILS = 10_000 * 100
TRANSFER_MAX_FILS = 20_000 * 100


class AmountError(ValueError):
    pass


def parse_amount(value, max_fils):
    """Parse a user-supplied AED amount into fils. Raises AmountError."""
    if value is None or isinstance(value, bool):
        raise AmountError("Amount is required.")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation:
        raise AmountError("Amount must be a number.")
    if not d.is_finite() or d <= 0:
        raise AmountError("Amount must be greater than zero.")
    if d.as_tuple().exponent < -2:
        raise AmountError("Amount can have at most 2 decimal places.")
    fils = int(d * 100)
    if fils > max_fils:
        raise AmountError(f"Amount exceeds the limit of AED {fmt_aed(max_fils)}.")
    return fils


def fee_and_vat(amount_fils):
    """Return (fee_fils, vat_fils) for a transfer. Integer maths, half-up rounding."""
    fee = max(MIN_FEE_FILS, (amount_fils * FEE_BPS + 5000) // 10000)
    vat = (fee * VAT_PERCENT + 50) // 100
    return fee, vat


def fmt_aed(fils):
    sign = "-" if fils < 0 else ""
    fils = abs(fils)
    return f"{sign}{fils // 100}.{fils % 100:02d}"
