"""Shared audio recipe scenario payloads for materializer tests."""

from __future__ import annotations

AUDIO_NOISE_SCENARIO = """\
schema_version: 20
scenario_id: audio-noise-capability-test
seed: 133
duration_scale: short
library:
  roots:
    - id: music
      path: Music
movies: []
series: []
artists:
  - id: artist_noise
    name: Noise Artist
    layout: artist_album_disc
    track_naming: track_number_title
    albums:
      - id: album_noise
        title: Noise Album
        release_year: 2026
        discs:
          - id: disc_one
            disc_number: 1
            tracks:
              - id: track_noise
                track_number: 1
                title: Brown Noise
                performers: []
                variants:
                  - id: variant_noise
                    label: flac
                    bundle:
                      id: bundle_noise
                      assets:
                        - id: asset_noise
                          role: main
                          container: flac
                          duration_seconds: 1.0
                          audio:
                            - source: noise
                              noise_color: brown
                              codec: flac
                              channels: stereo
                              language: zxx
                              sample_rate: 48000
                          subtitles: []
timeline: []
"""

AUDIO_NOISE_SCENARIO_BYTES = AUDIO_NOISE_SCENARIO.encode()
