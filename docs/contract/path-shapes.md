# Filename and path-shape scanner corpus

`recipes/scanner/path-shapes.yaml` uses a quarter-second H.264 source, eight
byte-identical copies and one in-root relative symlink. It needs no production
media. Path identity varies while media identity stays constant. The fixture is
policy-neutral: a consumer chooses whether to follow or skip the link.

| Shape | Fixture evidence |
| --- | --- |
| UTF-8 basename and parent | `映画/日本語/雪-é.mkv`; byte count exceeds character count |
| Canonically equivalent names | `nfc/café.mkv` and `nfd/cafe\u0301.mkv` (combining accent) in separate parents |
| Near-limit component | 250 ASCII bytes including `.mkv` |
| Deep relative path | Eight long directory components; over 512 UTF-8 bytes total |
| Leading dash | `-option.mkv` and the link basename |
| Spaces and metacharacters | Two adjacent spaces, semicolon, brackets, dollar sign, ampersand, apostrophe |
| Controls | Literal newline and tab, quoted/escaped in YAML and JSON |
| Symlink | `-参照-link.mkv` points to the stable original in the same directory |

Use a UTF-8 POSIX filesystem with symlink support and ffmpeg/ffprobe >=7. The
component budget is below the common 255-byte limit; limits are filesystem
properties, not character counts. The tests record `PC_NAME_MAX`, `PC_PATH_MAX`
and actual directory entries. The deep case also consumes the absolute run-dir
prefix: choose a short output path. A filesystem with a smaller limit is an
explicit unsupported test outcome; equipped Linux CI accepts no skips.
Windows names and filesystem behavior are outside this corpus's supported arm.

NFC/NFD are intended oracle spellings, not a demand that a filesystem preserve
both byte forms. Separate parents avoid canonical-equivalence collisions.
Integration evidence records actual spellings and checks canonical equivalence
for accent-bearing components; all other names and the 250-byte component are
checked exactly. Manifest paths and parsed journal `to_path` fields retain the
intended strings, including escaped controls. Enumerate names using a structured
API such as Python's `Path.iterdir()`, rather than line-oriented shell output.

NUL cannot occur in a filesystem name. Slash is a separator, not a basename
character; backslash is excluded by existing scenario path rules. Display-derived
components reject ASCII controls and collapse whitespace. This recipe uses
existing explicit rename destinations to retain newline/tab and repeated spaces;
it changes no renderer or containment policy. Dangling links and user-authorable
escaping targets remain owned by #195.

From the repository root, use a fresh short output directory:

```sh
uv run chaos-librarian validate recipes/scanner/path-shapes.yaml --json
uv run chaos-librarian run recipes/scanner/path-shapes.yaml \
  --out /tmp/path-shapes --duration 1s --speed 1x --json
uv run chaos-librarian replay /tmp/path-shapes/replay.json \
  --out /tmp/path-shapes-replay --against /tmp/path-shapes --json
```

Point the consumer's scanner at `/tmp/path-shapes/library` after the run completes.
The replay example deliberately uses a **run-mode** bundle: this build does not
implement replay of `materialize`-mode bundles. The `run` command materializes the
same tiny synthetic media before applying the renames. Check that all nine events
were applied before accepting a duration-limited run as the complete corpus.

For seeded fuzzing, the existing `fuzz-regression/core-fs` lane now requires
`path:unicode-basename`, `path:unicode-parent` and `path:leading-dash` cells.
Coverage classifies explicit rename/move destinations independently of codecs,
content hashes or titles. The broader matrix stays in this focused recipe so
routine fuzzing does not inherit platform-sensitive near-limit/control paths.
