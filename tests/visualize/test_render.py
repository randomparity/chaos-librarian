"""HTML renderer tests, including the hostile-string escaping contract."""

from __future__ import annotations

import json

from chaos_librarian.visualize import render_html


def test_payload_island_present_and_parses() -> None:
    payload = {"meta": {"scenario_id": "s"}, "snapshots": [], "events": [], "diffs": []}
    html = render_html(payload)
    assert '<script type="application/json" id="cl-payload">' in html
    start = html.index('id="cl-payload">') + len('id="cl-payload">')
    end = html.index("</script>", start)
    island = html[start:end]
    assert json.loads(island) == payload


def test_hostile_string_does_not_break_island() -> None:
    payload = {
        "meta": {"scenario_id": "</script><img onerror=alert(1)>"},
        "snapshots": [],
        "events": [],
        "diffs": [],
    }
    html = render_html(payload)
    start = html.index('id="cl-payload">') + len('id="cl-payload">')
    end = html.index("</script>", start)
    island = html[start:end]
    # The real guarantee: no '<' survives inside the island, so no payload
    # string can terminate the <script> tag or inject markup.
    assert "</script>" not in island
    assert "<" not in island
    assert json.loads(island)["meta"]["scenario_id"] == "</script><img onerror=alert(1)>"


def test_token_replaced() -> None:
    html = render_html({"meta": {}, "snapshots": [], "events": [], "diffs": []})
    assert "__CL_PAYLOAD__" not in html
