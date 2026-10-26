# THOR subnet

> **Illustrative only.** This repository shows how THOR's Bittensor subnet (SN112) will work.
> The network is not live, no weights are set and nothing here earns rewards yet. The full
> miner and validator will replace this code, and starter repositories for new miners will
> follow when they do.

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
percent, are test videos whose correct labels are already known, and miners cannot tell them
apart from normal jobs. A submission is scored on how close its steps, timings and captions
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

Python 3.12 or later.

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The protocol's three documents live in `thor/schemas/` with one example of each in
`examples/`. `thor.models` loads and checks them; a document that breaks a rule raises
`ProtocolError` naming the field:

```python
from thor.models import load_job, load_submission

job = load_job("examples/job.json")
submission = load_submission("examples/submission.json", job)
```

The miner, validator and mock server entry points are registered (`thor-miner`,
`thor-validator`, `thor-mock-server`) and will fill in feature by feature.

## Status

| Piece | State |
| --- | --- |
| Repository, notice, packaging, CI | done |
| Protocol: schemas, examples, validation | done |
| Docs: protocol, scoring, validators | done |
| Scorer | done |
| Mock job server | next |
| Reference miner | planned |
| Validator | planned |

## Licence

MIT. See [LICENSE](LICENSE).
