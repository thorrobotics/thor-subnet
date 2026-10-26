# Validators

What a validator does, and how the network knows whether to trust it.

## Scoring against answer keys

A share of all jobs, 15 to 20 percent, are test videos: clips the network has already
labelled, by its own annotators or by agreement between several independent labellers.
They come from the same footage pool, in the same job format, in random order, so a miner
cannot tell a test job from a normal one and has no reason to treat the two differently.

For a test job the validator scores the submission against the answer key with the rules
in [scoring.md](scoring.md). Those scores are the backbone of a miner's reputation.

## Fact checking with vision language models

For the other jobs there is no answer key, so the validator runs a vision language model
over the clip with the submitted steps and asks, for each step, whether the caption
describes what happens between its start and end. The model's verdicts, together with
the step's agreement with other miners' submissions for the same job where they exist,
score the submission. The model backend is pluggable (`validator/vlm_check.py`); V1 ships
an interface and a stub.

## Calibration: scoring the validators

Validators are scored too. Mixed into each validator's work are submissions whose truth
the network already knows: labels taken from answer keys and deliberately broken (a third of
the steps dropped, every boundary moved past the tolerance, every hand swapped, every object
changed) and labels known to be correct. The validator does not know which are which.

A validator holding the answer key judges labels with the scorer, and passes them only when
each part of the score clears its bar: segmentation 0.9, timing 0.75 and captions 0.9. One
part cannot hide another: swapping every hand costs only a tenth of the total but drops the
caption score below its bar.

A validator's calibration is its balanced accuracy over those planted cases: the mean of
the share of broken labels it caught and the share of correct labels it passed. Always
saying yes catches nothing; always saying no passes nothing; either way the balanced
accuracy is 0.5, the same as guessing, and the validator's weight falls accordingly. A
validator that catches broken labels and passes correct ones scores towards 1.

## Weights

A validator turns scores into on-chain weights: each miner's recent scores (test jobs and
fact checks) are averaged over a window and normalised, and the validator's own weight
in the network follows its calibration. While the network is not live, the validator in
this repository logs the weights it would set and sets nothing.
