"""CBR (RAR) extractor — download-only (BL-005).

The container deliberately ships no unrar/unar/bsdtar, so a real RAR archive
can never be extracted. Instead of the old silent zero-pages cataloguing, we
raise an explicit ExtractError so the pipeline quarantines the file with
NO_RAR_TOOL.
"""


def extract_cbr(filepath):
    from . import ExtractError

    raise ExtractError(
        "CBR (RAR) is download-only: the container has no unrar tool; "
        "extraction is disabled.",
        code="NO_RAR_TOOL",
    )