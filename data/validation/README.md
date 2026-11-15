# Phase 05 independent validation data

These files are annotation inputs, not automatically generated ground truth.
Reviewers must fill labels using independent evidence such as source imagery
and documented expert review. Never infer a label from the harmonization
decision or cluster membership.

## Correspondence review queue

Generate a blinded queue from an existing successful Phase 08 manifest:

```powershell
python scripts/create_phase05_review_queue.py `
  --manifest data/processed/harmonization/phase_08/<run-id>/phase08_manifest.json
```

This samples candidate edges uniformly within each platform pair. It is useful
for manual review of generated candidates, but it cannot estimate
candidate-generation recall because all rows were already generated as
candidates. Keep the queue manifest with the review file. Its sampling frame
is one date-scoped pilot, so do not present it as a full-archive validation
sample.

In `correspondence_review_queue.csv`, fill:

- `reference_label`: `same_burning_location`, `different_burning_location`,
  or `uncertain`;
- `reviewer_id`, `reviewed_at_utc`, and `evidence_reference` for each decided
  row; use `notes` to explain ambiguity.

Reviewers should not see model decision classes while labeling. A second
reviewer should adjudicate disagreements. Uncertain rows are retained but
excluded from binary metric calculations. This queue is a review artifact;
the current Phase 04A stage labels candidates `not_classified`, so these rows
do not yet produce correspondence TP/FP/FN or F1 scores.

## Candidate-generation recall references

`candidate_recall_reference_pairs.csv` is for independently discovered
positive pairs (`label=same_burning_location`), including known pairs that are
outside the candidate output. This independent positive-pair set is the
denominator needed for candidate-generation recall. Do not copy the sampled
review queue into this file as though it measured recall.

`reference_date_utc` assigns each pair to the UTC date of the earlier
acquisition. This keeps cross-midnight pairs in the daily validation partition
that owns their correspondence edge.

## Activity labels

`activity_reference_labels.csv` is one independently assigned activity label
per reviewed detection and UTC date. Detections judged to belong to the same
physical activity receive the same `activity_id` for that date. Use a separate
ID for a different activity. Include reviewer and evidence metadata.

For labeled detections, Phase 05 can report pairwise TP, FP, FN, TN, precision,
recall, F1, specificity, and accuracy for activity clustering. Correspondence
accuracy requires an explicitly defined and reviewed negative-pair universe;
otherwise its TN and accuracy are undefined.

## Current status

The label files start empty. The Phase 08 pilot can seed the review queue, but
it does not supply independent labels. Until reviewers complete labels and
the validation runner records them, report validation as pending rather than
displaying invented or zero-valued scores.

Freeze both input CSVs before starting a Phase 08 run. Their file hashes are
part of its configuration; if labels change, use a new run ID so the output
manifest cannot mix metrics from different label versions.
