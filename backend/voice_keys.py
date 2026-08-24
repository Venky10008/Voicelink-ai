"""Shared voice-key scheme for both cloning engines.

OmniVoice and XTTS v2 used to mint different key prefixes ("ov_" vs "v_")
depending on which engine happened to be installed when the user recorded.
That made the DB's cloned_voice_key ambiguous, so synthesis could silently
resolve through a different engine than expected.

Both engines now derive keys through THIS module, so a profile created under
either engine resolves to exactly one canonical key and reference WAV path.

The canonical prefix is "v_" (the original XTTS-era scheme) because existing
profiles and files on disk already use it — unifying on it requires no data
migration for XTTS-era profiles.
"""

from __future__ import annotations

import hashlib


def voice_key_for(voice_name: str) -> str:
    """Stable local key derived from the voice name (e.g. VoiceLink_<user_id>).

    Same digest for both engines — only ONE canonical key per profile.
    """
    digest = hashlib.sha256(voice_name.encode("utf-8")).hexdigest()
    return f"v_{digest[:24]}"
