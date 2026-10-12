import env
import numpy as np
import struct
import subprocess
from pathlib import Path

from classes.SyncAnalyzer import Fingerprinter

# Fingerprints DDR arcade data instead of a fan simfile: chart timing comes
# from the game's .ssq step file and audio from the matching XACT wave bank
# (.xwb, MS-ADPCM). Because both are the game's own assets, the resulting
# bias is the sync a player actually feels on the cabinet (validated against
# https://finaloffset.telp.gg/ to within ~0.1 ms).

# SSQ tempo chunk: pairs of (measure tick, timekeeper tick) breakpoints.
# 4096 measure ticks per 4/4 measure; timekeeper rate is the chunk parameter
# (1/150 s). Format notes: https://zenius-i-vanisher.com/v5.2/thread?threadid=7564
SSQ_TEMPO_CHUNK = 1
TICKS_PER_BEAT = 4096 / 4

# Standard MS-ADPCM predictor coefficients, needed to rebuild a decodable
# WAV header around the raw block data stored in the wave bank
MSADPCM_COEFS = [(256, 0), (512, -256), (0, 0), (192, 64), (240, 0), (460, -208), (392, -232)]


class ArcadeSyncAnalyzer(Fingerprinter):
    """
    One instance per arcade song (basename): parses <basename>.ssq timing,
    decodes the full-length wave out of <basename>.xwb, and produces a single
    song-wide sync block (arcade timing is never per-chart):

    sync_data = {"bias_ms", "confidence", "curve_start_ms", "curve_step_ms",
    "curve"}  # see Fingerprinter
    """

    def __init__(self, ssq_path, xwb_path):
        self.ssq_path = Path(ssq_path)
        self.xwb_path = Path(xwb_path)
        self.measure_ticks, self.beat_seconds = self.parseTempo()
        self.loadAudio()
        self.sync_data = self.fingerprint(self.beatTimes())

    def parseTempo(self):
        data = self.ssq_path.read_bytes()
        pos = 0
        while pos + 12 <= len(data):
            (length,) = struct.unpack_from("<I", data, pos)
            if length == 0:
                break
            ctype, param = struct.unpack_from("<HH", data, pos + 4)
            (entries,) = struct.unpack_from("<I", data, pos + 8)
            if ctype == SSQ_TEMPO_CHUNK:
                mticks = struct.unpack_from(f"<{entries}i", data, pos + 12)
                tticks = struct.unpack_from(f"<{entries}i", data, pos + 12 + 4 * entries)
                return np.array(mticks, float), np.array(tticks, float) / param
            pos += length
        env.logger.error(f"{self.ssq_path.name}: no tempo chunk")
        raise RuntimeError

    def loadAudio(self):
        payload, channels, rate, block_align, samples_per_block = self.findWave()
        samples = self.decodeAdpcm(payload, channels, rate, block_align, samples_per_block)
        if channels == 2:
            samples = samples.reshape((-1, 2)).max(1)
        self.setSamples(samples / 2**15, rate)

    def findWave(self):
        # XWB (XACT3 wave bank): pick the longest entry — banks hold the full
        # song plus a short song-wheel preview ("<basename>_s"). Segment
        # layout below is version-gated in the format (see Microsoft's
        # xact3wb.h / Luigi Auriemma's unxwb); every WORLD bank observed is
        # dwVersion 43 / dwHeaderVersion 42, which is what these fixed
        # offsets assume — asserted rather than silently trusted.
        data = self.xwb_path.read_bytes()
        if data[:4] != b"WBND":
            env.logger.error(f"{self.xwb_path.name}: not a WBND wave bank")
            raise RuntimeError
        (version,) = struct.unpack_from("<I", data, 4)
        if version < 42:
            env.logger.error(f"{self.xwb_path.name}: unsupported wave bank version {version}")
            raise RuntimeError
        segments = [struct.unpack_from("<II", data, 0x0C + i * 8) for i in range(5)]
        bank_off = segments[0][0]
        flags, count = struct.unpack_from("<II", data, bank_off)
        (meta_size,) = struct.unpack_from("<I", data, bank_off + 8 + 64)
        if flags & 0x20000:  # WAVEBANK_FLAGS_COMPACT: entries packed differently, not handled
            env.logger.error(f"{self.xwb_path.name}: compact-format wave bank not supported")
            raise RuntimeError
        if meta_size < 24:
            env.logger.error(f"{self.xwb_path.name}: entry metadata too small ({meta_size} bytes)")
            raise RuntimeError

        best = None
        for i in range(count):
            _fd, fmt, play_off, play_len = struct.unpack_from("<IIII", data, segments[1][0] + i * meta_size)
            if best is None or play_len > best[1]:
                best = (play_off, play_len, fmt)
        play_off, play_len, fmt = best

        codec = fmt & 3
        if codec != 2:
            env.logger.error(f"{self.xwb_path.name}: expected MS-ADPCM, found codec {codec}")
            raise RuntimeError
        channels = (fmt >> 2) & 7
        rate = (fmt >> 5) & 0x3FFFF
        block_align = (((fmt >> 23) & 0xFF) + 22) * channels
        samples_per_block = 2 + (block_align - 7 * channels) * 2 // channels
        wave_off = segments[4][0] + play_off
        return data[wave_off : wave_off + play_len], channels, rate, block_align, samples_per_block

    def decodeAdpcm(self, payload, channels, rate, block_align, samples_per_block) -> np.ndarray:
        # wrap the raw blocks in a WAV header and let ffmpeg decode to s16.
        # dwAvgBytesPerSec is purely advisory (ffmpeg derives real timing
        # from block_align/rate/the fact chunk), but compute it the way
        # XACT itself does — (rate // samples_per_block) * block_align,
        # per unxwb — for spec fidelity.
        avg_bps = (rate // samples_per_block) * block_align
        fmt = struct.pack(
            "<HHIIHHHH", 2, channels, rate, avg_bps, block_align, 4, 4 + 4 * len(MSADPCM_COEFS), samples_per_block
        )
        fmt += struct.pack("<H", len(MSADPCM_COEFS))
        for c1, c2 in MSADPCM_COEFS:
            fmt += struct.pack("<hh", c1, c2)
        riff = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
        wav = b"RIFF" + struct.pack("<I", len(riff)) + riff

        proc = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-c:a", "pcm_s16le", "pipe:1"],
            input=wav,
            capture_output=True,
        )
        if proc.returncode != 0:
            env.logger.error(f"{self.xwb_path.name}: ffmpeg failed: {proc.stderr.decode(errors='replace')}")
            raise RuntimeError
        samples = np.frombuffer(proc.stdout, dtype=np.int16)
        return samples[: len(samples) // channels * channels]

    def audio_name(self) -> str:
        return self.xwb_path.name

    def beatTimes(self):
        last_beat = int(self.measure_ticks[-1] // TICKS_PER_BEAT)
        for beat in range(last_beat + 1):
            yield float(np.interp(beat * TICKS_PER_BEAT, self.measure_ticks, self.beat_seconds))
