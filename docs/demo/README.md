# Terminal demos

Two recordings of the two things a new user does first.

| GIF | The workflow it shows |
|-----|------------------------|
| `byod.gif` | Point E2ER at a folder of your own data and your own references, and confirm it can run. |
| `quickstart.gif` | Install the package, run the guided setup, confirm the environment, see the command surface. |

## The rule these recordings follow

Every command runs for real and everything on screen after the prompt is the
program's own output. Nothing is simulated and no take is stitched together
from several runs. A project whose central claim is that its outputs trace back
to the artifacts that produced them cannot stage its own demo — one fabricated
line here would discredit the thing being demonstrated. The only theatre is the
typing delay in the session scripts, so a reader can follow the line being
entered.

Two consequences worth stating plainly:

1. **`e2er` resolves to the working-tree build during recording.** `record.sh`
   puts a one-line shim on `PATH`. This runs the real code and prints its real
   output; it only saves reinstalling between takes. Drop the shim once the
   published package is the thing under test.

2. **`quickstart` will not record until 0.9.0 is on PyPI.** It opens with a
   real `pip install e2er` into a throwaway virtualenv, and the published 0.8.1
   predates `doctor`, `verify`, `rq`, `compare` and `run-matrix` — so that
   install would not produce the CLI the rest of the session demonstrates.
   `record.sh` checks PyPI and skips the session with an explanation rather
   than recording something untrue. Cut the release, then re-run; it needs no
   other change.

Do not link either GIF from the top-level README until the release is out.

## Regenerating

```bash
brew install asciinema agg
docs/demo/record.sh            # every session that can be recorded honestly
docs/demo/record.sh byod       # just one
```

`record.sh` rebuilds the demo project first: two years of real daily prices for
SPY and BTC-USD pulled through the same yfinance library the pipeline uses, and
a 33-entry bibliography of genuine published references taken from
`examples/e2er_v1_bitcoin_institutionalization/`.

Appearance is tunable without editing anything:

```bash
E2ER_DEMO_WINDOW=112x38 E2ER_DEMO_FONT=18 E2ER_DEMO_THEME=dracula docs/demo/record.sh
```

## Why not vhs

vhs is the obvious tool and does not work on this machine: it reports
`Creating ….gif` and then writes no file, with Chrome, ttyd and a compatible
ffmpeg all present and working, and it prints no error. asciinema drives a real
PTY and agg renders the GIF in-process, so neither a browser nor ffmpeg is in
the path at all. The `.tape` files were removed when the recorder changed.
