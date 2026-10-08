# GoEmotions dataset

The checked-in `train.tsv`, `dev.tsv`, `test.tsv`, and `emotions.txt` are from
Google Research's [GoEmotions data directory](https://github.com/google-research/google-research/tree/master/goemotions/data).
The dataset contains Reddit comments with one or more of 27 emotion labels or
the separate `neutral` label. The row format is comment text, comma-separated
label IDs, and Reddit comment ID; label IDs follow `emotions.txt`.

Source paper: Demszky et al., [GoEmotions: A Dataset of Fine-Grained Emotion
Classification](https://aclanthology.org/2020.acl-main.372/).
The source repository is distributed under the [Apache License 2.0](https://github.com/google-research/google-research/blob/master/LICENSE).
