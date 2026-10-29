# Real HDFS incident fixture

A small cut of a real Hadoop cluster's log, with the label Hadoop experts gave each block.

- **Source.** loglizer's `HDFS_100k.log_structured.csv` and `anomaly_label.csv`
  (https://github.com/logpai/loglizer, commit ac67f9727acb660687a77b9c8042553aaa185cd3): the
  first 104,815 lines of HDFS_v1, logged by a Hadoop cluster of more than 200 Amazon EC2 nodes
  on 9 November 2008.
- **The cut.** Every line of one block in eight, chosen by a hash of the block ID, over minutes 2
  to 12 of the sample, plus the lines that name no block. Sampling whole blocks keeps each block's
  life intact and keeps the share of failed blocks as it was in the cluster. Rows are unmodified.
  Regenerate it with `uv run python -I scripts/make_real_fixtures.py`.
- **Labels.** `anomaly_label.csv` keeps the experts' label (Normal or Anomaly) for every block the
  cut mentions.
- **Use.** Unit tests of the real-log evaluation, and the console's real incident to replay. It
  is too small to measure ARIA on; `docs/evaluation.md` uses the full sample.

Cite: W. Xu, L. Huang, A. Fox, D. Patterson, M. I. Jordan. Detecting Large-Scale System Problems
by Mining Console Logs. SOSP 2009. And: Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael
R. Lyu. Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics. ISSRE 2023.
The datasets are freely available for research or academic work; the full license notice is in
`LICENSE`.
