# trkfile

The TR-series loggers export their logs as `.trk` files. The vendor has gone and so has
the description of the format, but we still have their desktop tool, which shows what a
file holds. `samples/` has 24 exports, each with a `.json` beside it: what the vendor's tool
shows for that file. That is all the documentation there is.

```python
from trkfile import decode

log = decode(open("samples/01-morning-run.trk", "rb").read())
log["device"]      # "TR-200"
log["records"][0]  # {"type": "fix", "t": 1718003600, "lat": 47.376887, "lon": 8.541694, "alt": 408.0}
```

`decode(data)` returns `{"version": ..., "device": ..., "records": [...]}` in exactly the
shape of the samples' `.json`: the same keys, times `t` in whole seconds, `lat` and `lon`
in degrees, `alt` in metres, lap `seconds` as a number.

## Where it stands

`trkfile/decode.py` reads the simplest files (the first three samples) and refuses the
rest. The loggers have several firmware versions and export settings, and the samples cover
all of them we know of, in various combinations. **The goal is a decoder that reads any
file these loggers can write**, not just the 24 here: files in the field mix the settings
freely and hold whatever the device recorded.

## Files it must refuse

The vendor's tool refuses damaged files, and so must `decode`, by raising `TrkError`:

- a file that is cut short, or has bytes left over after its last record;
- a file whose checksum doesn't match (some exports carry one);
- a version, an export setting or a kind of record that none of the samples have.

`samples/bad/` has four files the vendor's tool refuses, each with a `.error` beside it
saying what the tool reported.

## Tests

```
python -m pytest -q
```

`tests/test_samples.py` checks the samples the decoder already reads.
