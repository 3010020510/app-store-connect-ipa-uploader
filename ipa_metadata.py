from __future__ import annotations

import plistlib
import re
import zipfile
from typing import Any


MAIN_APP_INFO_PLIST = re.compile(r"^Payload/[^/]+\.app/Info\.plist$")


def find_main_app_info_plist(names: list[str]) -> str | None:
    matches = [name for name in names if MAIN_APP_INFO_PLIST.match(name)]
    if not matches:
        return None
    matches.sort(key=len)
    return matches[0]


def read_ipa_metadata(ipa_path: str) -> dict[str, Any]:
    with zipfile.ZipFile(ipa_path) as archive:
        info_path = find_main_app_info_plist(archive.namelist())
        if info_path is None:
            nested = [
                name
                for name in archive.namelist()
                if name.startswith("Payload/") and name.endswith("/Info.plist")
            ]
            hint = nested[:5]
            raise ValueError(
                "Could not find the main app Info.plist at Payload/*.app/Info.plist. "
                f"Nested plists found: {hint}"
            )

        with archive.open(info_path) as plist_file:
            plist = plistlib.load(plist_file)

    build = plist.get("CFBundleVersion")
    return {
        "bundleId": plist.get("CFBundleIdentifier"),
        "bundleName": plist.get("CFBundleName") or plist.get("CFBundleDisplayName"),
        "version": plist.get("CFBundleShortVersionString"),
        "build": "" if build is None else str(build),
        "infoPlistPath": info_path,
    }
