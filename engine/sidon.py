#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["torch", "torchaudio", "transformers", "numpy", "soundfile", "huggingface_hub"]
# ///
"""Sidon v0.1 generative speech restoration (sarulab-speech, MIT). Pipeline follows the authors' demo app.py.

  sidon.py --fetch               download the weights into models/sidon/ and prepare the environment
  sidon.py IN.wav OUT.wav        restore: output is 48 kHz mono, same length as the input

CPU only: the published TorchScript files do not run on Apple's GPU (MPS).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # the xet backend stalled mid-download on this machine
ROOT = Path(__file__).resolve().parent.parent
DIR = Path(os.environ.get("SIDON_DIR", ROOT / "models" / "sidon"))
REPO, REV = "sarulab-speech/sidon-v0.1", "b3b02d8bbd55fdbc410e6e46e76ef95ace4fbf52"
FILES = ("feature_extractor_cpu.pt", "decoder_cpu.pt")


def fetch() -> None:
    from huggingface_hub import hf_hub_download
    for f in FILES:
        if not (DIR / f).exists():
            hf_hub_download(REPO, f, revision=REV, local_dir=DIR)


def restore(src: str, dst: str) -> None:
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    import transformers

    fetch()
    fe = torch.jit.load(str(DIR / FILES[0]), map_location="cpu").eval()
    dec = torch.jit.load(str(DIR / FILES[1]), map_location="cpu").eval()
    pre = transformers.SeamlessM4TFeatureExtractor.from_pretrained("facebook/w2v-bert-2.0")

    wav, sr = sf.read(src, dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    wav = 0.9 * wav / max(float(np.abs(wav).max()), 1e-9)
    target = int(48000 / sr * len(wav))
    w = torchaudio.functional.highpass_biquad(torch.from_numpy(wav), sr, 50)
    w16 = torchaudio.functional.resample(w, sr, 16000)
    w16 = torch.nn.functional.pad(w16, (0, 24000))
    out, cache = [], None
    with torch.inference_mode():
        for chunk in w16.split(16000 * 96):  # the authors' chunk size; one frame of feature context carries across chunks
            x = torch.nn.functional.pad(chunk, (160, 160))
            feats = pre(x, return_tensors="pt", sampling_rate=16000)["input_features"]
            f = fe(feats)["last_hidden_state"]
            f = f if cache is None else torch.cat([cache, f], dim=1)
            out.append(dec(f.transpose(1, 2)).view(-1)[:-960])
            cache = f[:, -1:]
    res = torch.cat(out).numpy()[:target]
    sf.write(dst, res, 48000, subtype="FLOAT")


if __name__ == "__main__":
    if sys.argv[1:] == ["--fetch"]:
        fetch()
        import torch, torchaudio, transformers  # noqa: F401,E401  (touch the imports so uv builds the environment now)
    elif len(sys.argv) == 3:
        restore(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
