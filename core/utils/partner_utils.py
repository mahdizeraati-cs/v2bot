# core/utils/partner_utils.py
"""
Pure utility functions for wholesale partner pricing and validation.
No database, no handlers, no I/O.
"""



def to_persian_digits(text: str) -> str:
    """Convert Western digits to Persian/Arabic digits."""
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    return "".join(persian_digits[int(c)] if c.isdigit() else c for c in text)


class PartnerValidationError(ValueError):
    """Raised when partner validation fails."""
    pass


def discounted_price(list_price: int, percent: int) -> int:
    """
    Calculate discounted price with half-up rounding.
    
    Args:
        list_price: Original price in integer Toman (must be >= 0)
        percent: Discount percentage (0-100)
        
    Returns:
        Final price in integer Toman, minimum 1
        
    Raises:
        ValueError: If inputs are invalid
    """
    if not isinstance(list_price, int) or list_price < 0:
        raise ValueError("list_price must be a non-negative integer")
    if not isinstance(percent, int) or percent < 0 or percent > 100:
        raise ValueError("percent must be an integer between 0 and 100")
    
    if list_price == 0:
        return 0
    
    # Calculate discount amount with half-up rounding
    # Formula: discount = (list_price * percent + 50) // 100
    # This implements half-up rounding for positive numbers
    discount_amount = (list_price * percent + 50) // 100
    final_price = list_price - discount_amount
    
    # Ensure minimum price of 1
    return max(1, final_price)


def min_topup_ok(amount: int, min_topup: int) -> bool:
    """
    Check if amount meets the minimum top-up requirement.
    
    Args:
        amount: Amount to check (must be >= 0)
        min_topup: Minimum required amount (must be >= 0)
        
    Returns:
        True if amount >= min_topup, False otherwise
        
    Raises:
        ValueError: If inputs are negative
    """
    if not isinstance(amount, int) or amount < 0:
        raise ValueError("amount must be a non-negative integer")
    if not isinstance(min_topup, int) or min_topup < 0:
        raise ValueError("min_topup must be a non-negative integer")
    
    return amount >= min_topup


def validate_min_topup(value: int | str | None) -> int:
    """
    Validate and return minimum top-up amount.
    
    Args:
        value: Value to validate (must be positive integer)
        
    Returns:
        Validated integer value
        
    Raises:
        PartnerValidationError: If value is not a positive integer
    """
    if not isinstance(value, int):
        raise PartnerValidationError("Minimum top-up must be an integer")
    if value <= 0:
        raise PartnerValidationError("Minimum top-up must be a positive integer")
    return value


def validate_discount_percent(value: int | str | None) -> int:
    """
    Validate and return discount percentage.
    
    Args:
        value: Value to validate (must be integer between 1 and 90 inclusive)
        
    Returns:
        Validated integer value
        
    Raises:
        PartnerValidationError: If value is not an integer between 1 and 90
    """
    if not isinstance(value, int):
        raise PartnerValidationError("Discount percentage must be an integer")
    if value < 1 or value > 90:
        raise PartnerValidationError("Discount percentage must be between 1 and 90")
    return value