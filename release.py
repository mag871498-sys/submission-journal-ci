from hashlib import blake2s


VERSION = "v2"


def acknowledgement(number, key, mode):
    """Simulate a confirmation after the database commit."""
    if mode == "offline":
        return {"id": number, "error": "Confirmation channel unavailable"}, 503
    confirmation = blake2s(f"{number}:{key}".encode(), digest_size=6).hexdigest()
    return {"id": number, "confirmation": confirmation}, 201
