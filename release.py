VERSION = "v1"


def acknowledgement(number, key, mode):
    """Accept submission immediately in the first release."""
    return {"id": number}, 201
