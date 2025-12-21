import secrets
import string


def generate_invite_code(length: int = 4) -> str:
    """Generate a numeric invite code with the given length."""

    alphabet = string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
