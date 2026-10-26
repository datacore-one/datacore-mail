"""Every third-party package the Gmail adapter imports is declared.

The Google client was installed by hand on the box and declared nowhere; when
Winston moved into a pod, the 03:30 triage failed on `import google` for both
accounts. A missing declaration fails where nobody is looking.
"""
from pathlib import Path

REQ = Path(__file__).resolve().parents[1] / "requirements.txt"


def declared() -> set[str]:
    names = set()
    for line in REQ.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line.split(">")[0].split("=")[0].split("<")[0].strip().lower())
    return names


def test_the_gmail_client_libraries_are_declared():
    assert {"google-api-python-client", "google-auth", "google-auth-oauthlib"} <= declared()
