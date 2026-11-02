"""Transport declaration-owned execution profile names to browser consumers."""

import json

from fastapi import FastAPI
from fastapi.responses import Response

from workflows.definition.models import (
    NATIVE_INTERPRETATION_PROFILE,
    NATIVE_LITERATURE_PROFILE,
    NATIVE_PROPOSAL_FAMILIES_PROFILE,
)


def add_profile_assets(app: FastAPI) -> None:
    @app.get("/execution-profiles.js", include_in_schema=False)
    def execution_profiles() -> Response:
        profiles = {
            "nativeInterpretation": NATIVE_INTERPRETATION_PROFILE,
            "nativeLiterature": NATIVE_LITERATURE_PROFILE,
            "nativeProposalFamilies": NATIVE_PROPOSAL_FAMILIES_PROFILE,
        }
        return Response(
            "window.executionProfiles = Object.freeze(" + json.dumps(profiles) + ");\n",
            media_type="text/javascript",
        )
