import base64
import json
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from config import settings
from utils.time_utils import IST


class DhanCredentialsMissing(RuntimeError):
    pass


class DhanCredentialsExpired(RuntimeError):
    pass


class DhanHTTPError(RuntimeError):
    def __init__(self, message, status_code=None, url=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.body = body


def credentials_available():
    return bool(settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN)


def decode_access_token_payload():
    require_credentials()
    try:
        payload = settings.DHAN_ACCESS_TOKEN.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception as exc:
        raise DhanCredentialsMissing(
            "Dhan access token is not a valid JWT. Generate and export a fresh token."
        ) from exc


def access_token_expiry():
    payload = decode_access_token_payload()
    exp = payload.get("exp")
    if not exp:
        return None
    return datetime.fromtimestamp(int(exp), tz=timezone.utc).astimezone(IST)


def access_token_is_expired(buffer_seconds=300):
    expiry = access_token_expiry()
    if expiry is None:
        return False
    now = datetime.now(IST)
    return expiry.timestamp() <= now.timestamp() + buffer_seconds


def validate_credentials_or_raise():
    require_credentials()
    expiry = access_token_expiry()
    if expiry and access_token_is_expired():
        raise DhanCredentialsExpired(
            f"Dhan access token is expired or expires too soon. Expiry IST: {expiry.isoformat()}"
        )
    return True


def require_credentials():
    if not credentials_available():
        raise DhanCredentialsMissing(
            "Dhan credentials are missing. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN "
            "before running live ingestion."
        )


def build_headers():
    require_credentials()
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "access-token": settings.DHAN_ACCESS_TOKEN,
        "client-id": settings.DHAN_CLIENT_ID,
    }


def build_url(path):
    return urljoin(settings.DHAN_BASE_URL.rstrip("/") + "/", path.lstrip("/"))


def post_json(path, payload):
    response = requests.post(
        build_url(path),
        headers=build_headers(),
        json=payload,
        timeout=settings.HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise DhanHTTPError(
            f"Dhan API HTTP {response.status_code} for {path}: {response.text[:500]}",
            status_code=response.status_code,
            url=response.url,
            body=response.text,
        )
    data = response.json()
    if isinstance(data, dict) and data.get("status") not in (None, "success"):
        raise RuntimeError(f"Dhan API returned non-success status: {data}")
    return data


def get_url(url):
    response = requests.get(url, timeout=settings.HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response
