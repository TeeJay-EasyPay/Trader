"""Small provider failure receipts: no response prose, prompts or credentials."""
import json
import re
from urllib.error import HTTPError


def details(exc):
    result = {'error_type': type(exc).__name__}
    if isinstance(exc, HTTPError):
        result['http_status'] = exc.code
        try:
            error = json.loads(exc.read(16384)).get('error', {})
            for key in ('code', 'type', 'param'):
                value = error.get(key)
                if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,100}', value):
                    result['provider_' + key] = value
        except (ValueError, TypeError, AttributeError):
            pass
    return result
