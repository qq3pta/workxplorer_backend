from decimal import Decimal

RATES = {
    "UZS": Decimal("1"),
    "USD": Decimal("12152"),
    "EUR": Decimal("14330"),
    "RUB": Decimal("159"),
    "KZT": Decimal("25"),
}


def convert_to_uzs(value, currency):
    if value is None:
        return None

    currency = currency.upper().strip()

    rate = RATES.get(currency)
    if not rate:
        raise ValueError(f"Unsupported currency: {currency}")

    return Decimal(value) * rate
