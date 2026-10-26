# Protocol

How a miner gets work and hands it back. The network is not live; this is the shape the
full version will keep, so a miner built against it keeps working.

## Pull, not push

Miners fetch work. The network never connects to a miner, so a miner needs no open port, no
fixed address and no uptime guarantee. A miner asks for a job when it is ready for one, which
is what lets slow, human or mixed workflows fit beside fully automated ones.

```
GET  /v1/jobs/next                          one job, or 204 when the queue is empty
POST /v1/jobs/{job_id}/submissions          the miner's answer, as a submission document
GET  /v1/jobs/{job_id}/submissions/latest   what the network holds for this miner and job
```

Every request carries three headers. The signature is the miner's hotkey signing the
timestamp and the request body, so the network knows who did the work without a login.

```
X-Thor-Hotkey:     the miner's SS58 hotkey
X-Thor-Timestamp:  the request time, ISO 8601
X-Thor-Signature:  sr25519 signature, hex, over "<timestamp>\n<body>"
```

## Documents

Three JSON documents make up the protocol. Their schemas are in `thor/schemas/`, one
example of each in `examples/`, and `thor.models` loads and checks them.

**Job** (`job.schema.json`): what the queue hands out. The video to label (a URL, its
length, a digest and its source and licence), the task (a title and the labelling
instructions), the limits (how many steps, how long a caption) and two times: when the job
was issued and the deadline.

**Submission** (`submission.schema.json`): the miner's answer. The job it answers, the
miner's hotkey, when it was submitted, and the steps. Each step has a start and an end in
seconds from the start of the clip and a caption with three parts: the action (a present
tense verb phrase such as "pick up" or "fold in half"), the object acted on, and the hand
("left", "right" or "both"). Steps are listed in time order, may leave gaps, and must not
overlap. The optional `method` field says whether the work was automated, human or mixed;
it is never scored.

**Answer key** (`answer_key.schema.json`): the known-correct steps for a test video, in the
same shape as a submission's steps. Miners never see one.

## Rules a submission must follow

Checked by `thor.models` before anything is scored, each with a message naming the field:

- It follows its schema: required fields present, no unknown fields, hands from the fixed
  set, captions under the length limit.
- Steps are in time order and do not overlap. Each ends after it starts.
- Every step ends inside the clip, and there are no more steps than the job allows.
- It answers the job it was submitted to.

A submission that fails any of these is malformed and scores zero. A submission that
arrives after the deadline is accepted but also scores zero. The last submission a miner
sends before the deadline is the one that counts.

## Trying it locally

`thor-mock-server` serves the sample jobs from `examples/` on the same paths, accepts
submissions and returns a score, so `thor-miner` can run the whole loop against it.
