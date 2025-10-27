def convert_to_uzs(value, currency):
    """
    Простая функция конвертации в сумах.
    Здесь можно реализовать реальный курс валют или заглушку.
    """
    if currency == "UZS":
        return value
    elif currency == "USD":
        return value * 12700  # примерный курс
    elif currency == "EUR":
        return value * 13500
    else:
        return value