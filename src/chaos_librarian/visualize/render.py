"""Render the visualizer payload into the self-contained HTML template."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
_TEMPLATE = Path(__file__).resolve().parents[3] / "scripts" / "visualize_template.html"
_TOKEN = "__CL_PAYLOAD__"  # payload injection marker, not a secret
_SIZE_WARN_BYTES = 50 * 1024 * 1024


def render_html(payload: Mapping[str, object], template_path: Path | None = None) -> str:
    """Embed ``payload`` into the HTML template as an escaped JSON island.

    Every ``<`` in the serialized JSON is escaped to ``\\u003c`` so no
    payload string (e.g. a path or corrupt tag containing ``</script>``)
    can terminate the island. The viewer renders all payload strings via
    ``textContent``, so the data is inert markup either way; this guards the
    serialization layer.

    Args:
        payload: The mapping from ``build_payload``.
        template_path: Override for the template (defaults to
            ``scripts/visualize_template.html``).

    Returns:
        Complete HTML document text.
    """
    template = (template_path or _TEMPLATE).read_text(encoding="utf-8")
    serialized = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    html = template.replace(_TOKEN, serialized)
    size = len(html.encode("utf-8"))
    if size > _SIZE_WARN_BYTES:
        _LOGGER.warning(
            "visualizer payload is %.1f MB (scaling ~ (events+1) x manifest size); "
            "consider exporting a step-limited run",
            size / (1024 * 1024),
        )
    return html
