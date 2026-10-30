# corpus-example

A complete, valid corpus ready to copy and run.

## How to run

1. Copy this folder anywhere under `content/` — e.g. `content/my-corpus/`.
2. Copy `shapes/corpus/config/capabilities.example.yaml` to the 018 root as `capabilities.yaml` (it is gitignored).
3. Edit `capabilities.yaml`: replace each `run:` with the actual binary paths on your machine.
4. Drop files into `dropbox/general/` or `dropbox/private/`.
5. Run: `mo corpus watch <path-to-corpus>`.

The engine refuses to start until every capability name the flow uses is bound and present in `capabilities.yaml`. No fallbacks.
