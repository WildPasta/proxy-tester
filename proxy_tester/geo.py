"""Batched exit-IP geolocation via the free ip-api.com batch endpoint."""

from __future__ import annotations

import asyncio

import httpx

_BATCH_URL = "http://ip-api.com/batch"
_BATCH_SIZE = 100  # ip-api hard limit
_BATCH_PAUSE = 1.1  # stay under the 15 batches/minute free-tier limit


async def lookup_countries(
    ips: list[str],
    timeout: float = 15.0,
) -> dict[str, dict[str, str | None]]:
    """Geolocate unique IPs (country + AS info).

    Returns {ip: {"country": ..., "country_code": ..., "as_name": ..., "as_registry": ...}}.

    Failures are silent: missing IPs are simply absent from the result.
    """
    unique = list(dict.fromkeys(ip for ip in ips if ip))
    found: dict[str, dict[str, str | None]] = {}
    if not unique:
        return found

    async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
        for index in range(0, len(unique), _BATCH_SIZE):
            chunk = unique[index : index + _BATCH_SIZE]
            if index:  # pause between batches, not before the first
                await asyncio.sleep(_BATCH_PAUSE)
            try:
                response = await client.post(
                    _BATCH_URL,
                    json=[
                        {
                            "query": ip,
                            "fields": "status,country,countryCode,as,asname,query",
                        }
                        for ip in chunk
                    ],
                )
                response.raise_for_status()
                entries = response.json()
            except Exception:  # noqa: BLE001 - geo is best effort
                continue
            for entry in entries if isinstance(entries, list) else []:
                if entry.get("status") == "success":
                    found[entry.get("query", "")] = {
                        "country": entry.get("country"),
                        "country_code": entry.get("countryCode"),
                        # "AS22773 Cox Communications Inc." (readable)
                        "as_name": entry.get("as"),
                        # "ASN-CXA-ALL-CCI-22773-RDC" (registry name)
                        "as_registry": entry.get("asname"),
                    }
    return found
