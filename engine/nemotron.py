#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = [
#   "torch",
#   "numba",
#   "safetensors",
#   "soundfile",
#   "numpy",
#   # Intel Macs: torch 2.2.2 is the last build for them and needs numpy 1.x; numba 0.62 is the last with a wheel
#   "numpy<2; sys_platform == 'darwin' and platform_machine == 'x86_64'",
#   "numba<0.63; sys_platform == 'darwin' and platform_machine == 'x86_64'",
# ]
# ///
# Ported from NVIDIA's RE-USE reference code: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES, OpenMDW-1.1.
"""NVIDIA NemotronLabs RE-USE in plain PyTorch on the CPU: the clean engine on Windows, Intel Macs and Linux.

  nemotron.py IN.wav OUT.wav [--chunk 2.0] [--hop 0.5]

The model runs at the input file's sample rate (8 to 48 kHz); for bandwidth extension, resample the input up first.
A port of NVIDIA's reference code (models/*.py and inference_chunk.py in the Hugging Face repo, OpenMDW-1.1): the
same modules and weight names, with the CUDA-only mamba_ssm scan replaced by a numba kernel. Apple silicon uses the
faster MLX tool in bin/ instead; both run the same weights from models/nemotron-re-use/.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numba
import numpy as np
import soundfile as sf
import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import load_file

MODEL = Path(os.environ.get("NEMOTRON_MODEL_DIR", Path(__file__).resolve().parent.parent / "models" / "nemotron-re-use"))
HID, D_STATE, D_CONV, EXPAND, N_BLOCKS = 64, 16, 4, 4, 30  # model_cfg in config.json


# ---------------------------------------------------------------- selective scan (replaces mamba_ssm's CUDA kernel)

@numba.njit(parallel=True, fastmath=True, cache=True)
def _scan(dt, x, bm, cm, a, d, y):
    """h_t = exp(dt_t A) h_{t-1} + dt_t B_t x_t,  y_t = <C_t, h_t> + D x_t.  dt, x, y: (B, L, Di); bm, cm: (B, L, N)."""
    nb, length, di = x.shape
    n = a.shape[1]
    for b in numba.prange(nb):
        h = np.zeros((di, n), np.float32)
        for t in range(length):
            for i in range(di):
                dv = dt[b, t, i]
                xv = x[b, t, i]
                u = dv * xv
                acc = np.float32(0.0)
                for k in range(n):
                    hv = math.exp(dv * a[i, k]) * h[i, k] + u * bm[b, t, k]
                    h[i, k] = hv
                    acc += hv * cm[b, t, k]
                y[b, t, i] = acc + d[i] * xv


class Mamba(nn.Module):
    """mamba_ssm.Mamba (v1) inference path, same parameter names."""

    def __init__(self):
        super().__init__()
        di, self.rank = EXPAND * HID, math.ceil(HID / 16)
        self.in_proj = nn.Linear(HID, 2 * di, bias=False)
        self.conv1d = nn.Conv1d(di, di, D_CONV, groups=di, padding=D_CONV - 1)
        self.x_proj = nn.Linear(di, self.rank + 2 * D_STATE, bias=False)
        self.dt_proj = nn.Linear(self.rank, di)
        self.A_log = nn.Parameter(torch.zeros(di, D_STATE))
        self.D = nn.Parameter(torch.ones(di))
        self.out_proj = nn.Linear(di, HID, bias=False)

    def forward(self, u):  # (B, L, HID)
        length = u.shape[1]
        x, z = self.in_proj(u).chunk(2, dim=-1)
        # causal depthwise conv as K shifted multiply-adds: torch's grouped Conv1d on the CPU is ~100x slower here
        xp, w = F.pad(x, (0, 0, D_CONV - 1, 0)), self.conv1d.weight[:, 0]  # (B, L+K-1, Di), (Di, K)
        x = self.conv1d.bias + sum(xp[:, k : k + length] * w[:, k] for k in range(D_CONV))
        x = F.silu(x).contiguous()
        dt, bm, cm = self.x_proj(x).split([self.rank, D_STATE, D_STATE], dim=-1)
        dt = F.softplus(self.dt_proj(dt)).contiguous()
        y = torch.empty_like(x)
        _scan(dt.numpy(), x.numpy(), bm.contiguous().numpy(), cm.contiguous().numpy(),
              (-torch.exp(self.A_log)).contiguous().numpy(), self.D.numpy(), y.numpy())
        return self.out_proj(y * F.silu(z))


class MambaBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.forward_blocks, self.backward_blocks = Mamba(), Mamba()
        self.output_proj = nn.Linear(2 * HID, HID)
        self.norm = nn.LayerNorm(HID)

    def forward(self, x):
        fw = self.forward_blocks(x) + x
        xr = torch.flip(x, dims=[1])
        bw = torch.flip(self.backward_blocks(xr) + xr, dims=[1])
        return self.norm(self.output_proj(torch.cat([fw, bw], dim=-1)))


class TFMambaBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.time_mamba, self.freq_mamba = MambaBlock(), MambaBlock()

    def forward(self, x):
        b, c, t, f = x.shape
        x = x.permute(0, 3, 2, 1).contiguous().view(b * f, t, c)
        x = self.time_mamba(x) + x
        x = x.view(b, f, t, c).permute(0, 2, 1, 3).contiguous().view(b * t, f, c)
        x = self.freq_mamba(x) + x
        return x.view(b, t, f, c).permute(0, 3, 1, 2)


def norm_act(conv):
    return nn.Sequential(conv, nn.InstanceNorm2d(HID, affine=True), nn.PReLU(HID))


class SPConvTranspose2d(nn.Module):
    def __init__(self, r):
        super().__init__()
        self.conv, self.r = nn.Conv2d(HID, HID * r, (1, 3)), r

    def forward(self, x):
        out = self.conv(F.pad(x, (1, 1, 0, 0)))
        b, c, h, w = out.shape
        return out.view(b, self.r, c // self.r, h, w).permute(0, 2, 3, 4, 1).contiguous().view(b, c // self.r, h, -1)


class DenseBlock(nn.Module):
    def __init__(self, depth=4):
        super().__init__()
        self.dense_block = nn.ModuleList(
            norm_act(nn.Conv2d(HID * (i + 1), HID, (3, 3), dilation=(2**i, 1), padding=(2**i, 1))) for i in range(depth))

    def forward(self, x):
        skip = x
        for layer in self.dense_block:
            x = layer(skip)
            skip = torch.cat([x, skip], dim=1)
        return x


class DenseEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.dense_conv_1 = norm_act(nn.Conv2d(2, HID, (1, 1)))
        self.dense_block = DenseBlock()
        self.dense_conv_2 = norm_act(nn.Conv2d(HID, HID, (1, 3), stride=(4, 2)))

    def forward(self, x):
        return self.dense_conv_2(self.dense_block(self.dense_conv_1(x)))


class Decoder(nn.Module):
    """MagDecoder (phase=False) and PhaseDecoder (phase=True)."""

    def __init__(self, phase: bool):
        super().__init__()
        self.phase = phase
        self.dense_block = DenseBlock()
        self.up_conv1 = norm_act(SPConvTranspose2d(2))
        self.up_conv2 = norm_act(SPConvTranspose2d(4))
        if phase:
            self.phase_conv_r, self.phase_conv_i = nn.Conv2d(HID, 1, (1, 1)), nn.Conv2d(HID, 1, (1, 1))
        else:
            self.final_conv = nn.Conv2d(HID, 1, (1, 1))

    def forward(self, x):
        x = self.up_conv1(self.dense_block(x))
        x = self.up_conv2(x.permute(0, 1, 3, 2)).permute(0, 1, 3, 2)
        return torch.atan2(self.phase_conv_i(x), self.phase_conv_r(x)) if self.phase else self.final_conv(x)


class SEMamba(nn.Module):
    def __init__(self):
        super().__init__()
        self.dense_encoder = DenseEncoder()
        self.TSMamba = nn.ModuleList(TFMambaBlock() for _ in range(N_BLOCKS))
        self.mask_decoder, self.phase_decoder = Decoder(False), Decoder(True)

    def forward(self, mag, pha):  # (1, F, T) each
        x = torch.stack((mag, pha), dim=1).transpose(2, 3)  # (1, 2, T, F)
        _, _, t, f = x.shape
        x = F.pad(x, (0, 2, 0, 2))  # NVIDIA: two zero bins and two zero frames ("prevent unpredictable errors")
        x = self.dense_encoder(x)
        for block in self.TSMamba:
            x = block(x)
        m = self.mask_decoder(x)[0, 0].T[:f, :t]
        p = self.phase_decoder(x)[0, 0].T[:f, :t]
        return m[None], p[None]


# ---------------------------------------------------------------- inference (inference_chunk.py)

def make_even(v: float) -> int:
    v = int(round(v))
    return v if v % 2 == 0 else v + 1


def load(model_dir: Path = MODEL) -> tuple[SEMamba, dict]:
    cfg = json.loads((model_dir / "config.json").read_text())
    net = SEMamba()
    net.load_state_dict(load_file(str(model_dir / "model.safetensors")), strict=True)
    return net.eval(), cfg


def enhance(net: SEMamba, cfg: dict, wav: np.ndarray, sr: int, chunk_s: float = 2.0, hop: float = 0.5) -> np.ndarray:
    s = cfg["stft_cfg"]
    n_fft, hop_size, win = (make_even(s[k] * sr // s["sampling_rate"]) for k in ("n_fft", "hop_size", "win_size"))
    window = torch.hann_window(win)
    noisy = torch.from_numpy(np.ascontiguousarray(wav, np.float32))[None]
    chunk = int(chunk_s * sr)
    step = max(1, int(hop * chunk))
    fade = torch.clamp(torch.hann_window(chunk), min=1e-7)
    out, wsum = torch.zeros_like(noisy), torch.zeros_like(noisy)
    n = max(1, math.ceil((noisy.shape[1] - chunk) / step) + 1)
    with torch.inference_mode():
        for i in range(n):
            sl = slice(i * step, i * step + chunk) if i < n - 1 else slice(-chunk, None)  # the last chunk ends at the end
            seg = noisy[:, sl]
            spec = torch.stft(seg, n_fft, hop_length=hop_size, win_length=win, window=window, center=True,
                              pad_mode="reflect", normalized=False, return_complex=True)
            amp, pha = net(torch.log1p(spec.abs()), spec.angle())
            mag = torch.expm1(F.relu(amp))
            mag[:, :, ((mag == 0).sum(1) / mag.shape[1] > 0.5)[0]] = 0  # NVIDIA's "strange sweep artifact" fix
            y = torch.istft(torch.polar(mag, pha), n_fft, hop_length=hop_size, win_length=win, window=window, center=True)
            k = seg.shape[1]
            y = y[:, :k] if y.shape[1] >= k else F.pad(y, (0, k - y.shape[1]), value=1e-8)
            out[:, sl] += y * fade[:k]
            wsum[:, sl] += fade[:k]
    return (out / wsum)[0].numpy()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--chunk", type=float, default=2.0, help="chunk length in seconds (NVIDIA's chunk_size_in_seconds)")
    ap.add_argument("--hop", type=float, default=0.5, help="chunk step as a fraction of the chunk (hop_length_portion)")
    a = ap.parse_args()
    wav, sr = sf.read(a.input, dtype="float32", always_2d=True)
    net, cfg = load()
    t0 = time.time()
    y = enhance(net, cfg, wav.mean(1), sr, a.chunk, a.hop)
    busy = time.time() - t0
    sf.write(a.output, y, sr, subtype="FLOAT")
    print(f"{a.output}: nemotron (PyTorch CPU), {len(y) / sr:.1f} s at {sr} Hz, RTF {busy / (len(y) / sr):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
