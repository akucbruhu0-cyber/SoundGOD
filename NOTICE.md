# Third-party notices

This project's own code is MIT (see `LICENSE`). It redistributes the following, each under its own terms.
Full texts are in `licenses/` and `models/nemotron-re-use/`.

| What | Where | License | Source |
|---|---|---|---|
| **NVIDIA NemotronLabs RE-USE** model weights (unmodified, revision `31f82f2`) | `models/nemotron-re-use/` | OpenMDW-1.1 (commercial use allowed). The agreement and NVIDIA's copyright notice are retained next to the weights, as the license requires. | https://huggingface.co/nvidia/NVIDIA-NemotronLabs-RE-USE |
| **apple-efficient-noise-reduction** command-line tool (MLX/Metal port that runs the model), commit `31a2e64` | `bin/` in the release zip; built by `scripts/build-cli.sh` | MIT | https://github.com/JacobLinCool/apple-efficient-noise-reduction |
| mlx-swift | linked into the tool above | MIT | https://github.com/ml-explore/mlx-swift |
| swift-numerics, swift-argument-parser | linked into the tool above | Apache-2.0 | https://github.com/apple |
| DeepFilterNet3 weights (embedded in the tool's resource bundle, not used by this project) | `bin/*.bundle` | MIT or Apache-2.0 | https://github.com/Rikorose/DeepFilterNet |

| **Sidon v0.1** speech restoration weights (`feature_extractor_cpu.pt`, `decoder_cpu.pt`) | `models/sidon/`, downloaded on first use by `engine/sidon.py`, not in git or the zip (about 1 GB) | MIT (code and weights) | https://huggingface.co/sarulab-speech/sidon-v0.1 |
| w2v-BERT 2.0 feature-extractor config, read by Sidon at run time | fetched from Hugging Face | MIT | https://huggingface.co/facebook/w2v-bert-2.0 |
| PyTorch, torchaudio, transformers (Sidon's environment) | installed by `uv` on first use | BSD-3 / Apache-2.0 | |

Not included, and not used:

- NVIDIA *Real-time RE-USE* weights: noncommercial license. This project does not download or use them.
- `ffmpeg` and `uv` are not bundled; install them with Homebrew.
- The web UI loads the Rubik and IBM Plex fonts (SIL Open Font License) from Google Fonts at runtime, and falls back to system fonts offline.

Audio you produce with this tool is yours; OpenMDW-1.1 imposes no restrictions on model outputs.
