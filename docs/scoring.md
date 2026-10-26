# Scoring

How a submission is scored against an answer key. `thor.scoring` implements exactly this;
its tests pin the numbers for the examples. Every score is between 0 and 1.

## Zero first

A submission scores 0, with no further comparison, when it is late (submitted after the
job's deadline) or malformed (fails any rule in the protocol). The network pays for
usable work delivered on time.

## Matching steps

Submitted steps are matched one to one with answer-key steps by how much they overlap in
time: the intersection of the two intervals divided by their union. Pairs are taken
greedily, best overlap first, and a pair counts as a match only when its overlap is at
least 0.3. Steps left over on either side are unmatched: an extra step the miner invented,
or a step the miner missed.

**Segmentation** is the F1 score of that matching: precision is matched pairs over
submitted steps, recall is matched pairs over answer-key steps, and F1 is their harmonic
mean. A submission that merges two steps into one, or splits one into two, loses here.

## Scoring a matched pair

**Timing** rewards exact boundaries. Each boundary (start and end) scores
`max(0, 1 - |difference in seconds| / 2)`, so a boundary 0.5 seconds off scores 0.75 and
one 2 or more seconds off scores 0. The step's timing score is the mean of its two
boundaries.

**Caption** compares the three parts separately after normalising text (lower case,
surrounding whitespace removed, internal whitespace collapsed):

- action and object each score 1 for an exact match, otherwise the Jaccard overlap of
  their word sets, so "folded towel" against "towel" scores 0.5;
- hand scores 1 for a match and 0 otherwise.

The caption score is `0.4 x action + 0.4 x object + 0.2 x hand`.

The pair's score is `0.5 x timing + 0.5 x caption`.

## Total

```
total = segmentation F1 x mean pair score over the matched pairs
```

With no matched pairs the total is 0. The scorer returns the breakdown (segmentation,
timing, caption, total, and the pairs it matched) so a miner can see where points went.

## What the examples score

`examples/submission.json` against `examples/answer_key.json` matches all six steps with
boundaries a few tenths of a second off and one object phrased differently: segmentation 1,
timing 0.93, caption 0.97, total 0.95. `examples/broken_submission.json` has three steps
where the key has six, the wrong hand throughout and one wrong object: segmentation 0.67,
timing 0.32, caption 0.24, total 0.19.
