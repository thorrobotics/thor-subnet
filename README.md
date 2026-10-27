# THOR subnet

> **Illustrative only.** This repository is a simplified example of the basic loop in THOR's
> Bittensor subnet (SN112): a miner takes a job, labels a video and submits it, and a validator
> scores it. Some rules here are simplified and differ from the planned design; where they
> differ, the [docs](https://thormachines.ai/docs/start/how-sn112-works/) describe how SN112 will
> work. Not shown: the private beta for qualified firms, leased assignments, cross-checks, buyer
> acceptance and two-stage payment. The network is not live, no weights are set and nothing
> here earns rewards yet. The full miner and validator will replace this code, and starter
> repositories for new miners will follow when they do.

THOR runs a Bittensor subnet that labels first-person video of people doing hands-on tasks,
for robotics training. For each video the network splits the task into steps, marks exactly
when each step starts and ends, and writes a short caption per step saying what was done, to
which object, with which hand. V1 uses open-source footage only. Its goal is to publish an
open dataset that proves the network can do this work well.

## How it works

**Miners** take a video from the job queue, return the steps, timings and captions, and
submit before the deadline. Late or badly formed work scores zero. How the work is done is up
to the miner: fully automated, human, or a mix. The network pays for the quality of the
output, not the method. Miners fetch work; the network does not push it. A miner asks for a
job when it is ready, so slow or human workflows still fit and a miner needs no open server.

**Validators** score submissions against an answer key. A share of all jobs, 15 to 20
percent, are test videos whose correct labels are already known, and are meant to be
indistinguishable from normal jobs (in this prototype they are not yet: only test jobs return
a score on submission). A submission is scored on how close its steps, timings and captions
are to the answer key, and validators run vision language models to fact check miner work.
Validators are themselves scored on whether they catch labels the network deliberately broke
and pass labels it knows are correct. Always saying yes, or always saying no, scores badly.

## Read more

- [Protocol](docs/protocol.md): the pull model, the three documents and the rules a submission must follow.
- [Scoring](docs/scoring.md): how a submission is scored against an answer key.
- [Validators](docs/validators.md): answer keys, fact checking and how validators are scored.

## Layout

```
thor/          shared by both roles: the job, submission and answer-key schemas, the scorer,
               and the client that fetches and submits work
miner/         the reference miner: fetch a job, label it, validate, submit
validator/     the validator: score against answer keys, fact check, calibrate, set weights
mock_server/   a local job queue with sample clips, so the loop can be tried end to end
docs/          the protocol, the scoring rules and how validators are scored
examples/      a sample job, submission and answer key
```

## Try it

Python 3.12 or later. Run everything from this checkout: the mock server and the example
pipeline read its `examples/` folder.

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Start the local job queue in one terminal and leave it running:

```
thor-mock-server --port 8787
```

In a second terminal (activate the venv there too), run the miner once. It fetches the
example job, labels it, checks the work against the protocol and the deadline, hands it in
and prints the score the queue sends back:

```
thor-miner --pipeline example --once
```

Then run the validator once. It collects what was submitted, scores it against the answer
key, measures its own calibration on planted cases and prints the weights it would set:

```
thor-validator --once
```

Worth trying next: `thor-miner --pipeline manual --once` writes a template under `./work`
for a person to fill in and submits it on the next pass; `thor-validator --backend stub
--once` swaps in a fact checker that accepts everything and shows why that calibrates at
0.5. Your own labeller plugs in with `--pipeline your.module:function`; the one function a
miner replaces is in [miner/pipeline.py](miner/pipeline.py).

## Status

The loop runs end to end on one machine: the mock server hands out the example job, the
miner labels and submits it, the validator scores it against the answer key, checks its own
calibration and prints the weights it would set. Everything in the requirements is either
implemented or represented by a documented stub:

| Piece | State |
| --- | --- |
| Protocol: schemas, examples, validation | done |
| Scorer, with the examples' scores pinned in tests | done |
| Mock job server on the protocol's paths | done |
| Reference miner with pluggable pipelines | done |
| Validator: scoring, fact-check interface, calibration, weights | done |
| Request signing | header documented; V1 sends `unsigned` |
| Vision language model fact checks | interface and a stub backend |
| Setting weights on chain | logged, not set |
| Answer-key mixing at 15 to 20 percent | documented; the mock queue holds one keyed job |
| Open-source footage | example job points at a placeholder clip address |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE).
