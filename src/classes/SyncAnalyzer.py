import env
import simfile
import numpy as np
from pathlib import Path
from pydub import AudioSegment
from scipy import signal
from simfile.timing import TimingData
from simfile.timing.engine import TimingEngine

# Core algorithm vendored from Telperion's "+9ms or Null?" (MIT licence):
# https://github.com/telperion/nine-or-null
# Stripped to the sync-fingerprint math: no GUI, plots, paradigm labels or
# offset rewriting. For each beat of the chart timing, a small spectrogram
# window around the beat is flattened and stacked into a "beat digest"; a
# rising-edge convolution over the digest yields a response curve whose peak
# marks where the audio attack sits relative to the chart's beat grid.

FINGERPRINT_MS = 50  # time margin analyzed on either side of each beat
WINDOW_MS = 10  # spectrogram moving-window size
STEP_MS = 0.2  # spectrogram step size
FREQ_EMPHASIS = 3000  # frequency weighting: filt(f) = f * e^(-f / emphasis)

# Output curve: resampled onto a fixed millisecond grid so the app never
# depends on the audio sample rate, values normalized to 0..100 ints.
CURVE_SPAN_MS = 49
CURVE_STEP_MS = 1.0

# Confidence-metric shaping (see nine-or-null README "Confidence")
NEARNESS_SCALAR = 10  # milliseconds
NEARNESS_OFFSET = 0.5  # milliseconds
THEORETICAL_UPPER = 0.83

# Responds to the leading (rising) edge of the beat attack
RISING_EDGE_KERNEL = np.array(
    [
        [1, 1, 0, -1, -1],
        [1, 1, 0, -1, -1],
        [1, 1, 0, -1, -1],
        [1, 1, 0, -1, -1],
        [1, 1, 0, -1, -1],
    ]
)

AUDIO_EXTS = [".ogg", ".oga", ".mp3", ".wav"]


class Fingerprinter:
    """
    The timing-source-agnostic core: give it mono audio samples via
    setSamples(), then fingerprint() an iterable of beat timestamps to get a
    sync block: {"bias_ms", "confidence", "curve_start_ms", "curve_step_ms",
    "curve"} where bias_ms > 0 means the audio attack lands after the beat
    time (chart feels early), bias_ms < 0 the reverse.
    """

    def setSamples(self, samples: np.ndarray, frame_rate: int):
        self.audio_data = samples
        self.frame_rate = frame_rate
        self.duration = samples.shape[0] / frame_rate

        # Spectrogram geometry (shared by every fingerprint of this song)
        self.nperseg = int(self.frame_rate * WINDOW_MS * 1e-3)
        self.nstep = int(self.frame_rate * STEP_MS * 1e-3)
        self.noverlap = self.nperseg - self.nstep
        self.actual_step = self.nstep / self.frame_rate
        self.fingerprint_size = 2 * int(round(FINGERPRINT_MS * 1e-3 / self.actual_step))
        # the spectrogram doesn't "start" until a full window is in view
        self.spectrogram_offset = np.sqrt(0.5) * self.nperseg / self.nstep
        self.n_time_taps = -((self.audio_data.shape[0] - self.nperseg) // -self.nstep)

    def fingerprint(self, beat_times) -> dict:
        digest = self.beatDigest(beat_times)

        post_kernel = signal.convolve2d(digest, RISING_EDGE_KERNEL, mode="same", boundary="wrap")
        curve = np.sum(post_kernel, axis=0)
        times_ms = np.arange(-self.fingerprint_size // 2, self.fingerprint_size // 2) * self.actual_step * 1e3

        # highest response (edges hold convolution wrap artifacts) is the bias
        edge_discard = RISING_EDGE_KERNEL.shape[1] // 2
        curve_clip = curve[edge_discard:-edge_discard]
        times_clip = times_ms[edge_discard:-edge_discard]
        i_max = np.argmax(curve_clip)
        bias_ms = times_clip[i_max]

        return {
            "bias_ms": round(float(bias_ms), 1),
            "confidence": round(self.confidence(curve_clip, times_clip, i_max), 3),
            "curve_start_ms": -CURVE_SPAN_MS,
            "curve_step_ms": CURVE_STEP_MS,
            "curve": self.compactCurve(curve_clip, times_clip),
        }

    def beatDigest(self, beat_times) -> np.ndarray:
        # stack a flattened spectrogram snippet around every beat's timestamp
        rows = []
        t_last = -np.inf
        for t in beat_times:
            if t < 0:
                continue
            if t - t_last < FINGERPRINT_MS * 1e-3:
                continue
            t_last = t

            t_s = int(round(t / self.actual_step - self.spectrogram_offset - self.fingerprint_size * 0.5))
            t_f = int(round(t / self.actual_step - self.spectrogram_offset + self.fingerprint_size * 0.5))
            t_s = max(0, t_s)
            t_f = min(self.n_time_taps, t_f)
            if t_f - t_s != self.fingerprint_size:
                # not enough audio around this beat
                continue

            frequencies, _, spectrogram = signal.spectrogram(
                self.audio_data[t_s * self.nstep : t_f * self.nstep + self.nperseg - 1],
                fs=self.frame_rate,
                window="hann",
                nperseg=self.nperseg,
                noverlap=self.noverlap,
                detrend=False,
            )
            snippet = np.log2(spectrogram + 1e-9)
            weights = np.tile(frequencies * np.exp(-frequencies / FREQ_EMPHASIS), [self.fingerprint_size, 1]).T
            rows.append(np.sum(snippet * weights, axis=0))

        if not rows:
            env.logger.error(f"{self.audio_name()}: no beats with enough surrounding audio")
            raise RuntimeError
        return np.vstack(rows)

    def audio_name(self) -> str:
        # overridden for log messages
        return "audio"

    def confidence(self, curve_clip, times_clip, i_max) -> float:
        # how much rivaling response exists far away from the chosen peak
        v = np.interp(curve_clip, (curve_clip.min(), curve_clip.max()), (0, 1))
        v_median = np.median(v)
        v_rivaling = np.maximum(0, (v - v_median) / (v[i_max] - v_median))
        t_away = np.maximum(0, np.abs(times_clip - times_clip[i_max]) - NEARNESS_OFFSET) / NEARNESS_SCALAR
        influence = np.power(v_rivaling, 4) * np.power(t_away, 1.5)
        total = np.sum(influence) / np.size(influence)
        return float(min(1, (1 - np.power(total, 0.2)) / THEORETICAL_UPPER))

    def compactCurve(self, curve_clip, times_clip) -> list[int]:
        grid = np.arange(-CURVE_SPAN_MS, CURVE_SPAN_MS + CURVE_STEP_MS / 2, CURVE_STEP_MS)
        resampled = np.interp(grid, times_clip, curve_clip)
        normalized = np.interp(resampled, (resampled.min(), resampled.max()), (0, 100))
        return [int(round(x)) for x in normalized]


class SyncAnalyzer(Fingerprinter):
    """
    One instance per simfile. Loads the song audio once, then produces
    sync fingerprints against the simfile's timing data:

    sync_data = {
        "song":   {...} | None,   # set when all charts share timing
        "charts": [{...}] | None, # per_chart songs: one entry per chart_data
                                  # entry (unique difficulty, BEMHC order)
    }

    Each block: see Fingerprinter.
    """

    def __init__(self, simfile_path):
        simfile_path = Path(simfile_path)
        self.simfile = simfile.open(str(simfile_path), strict=False)
        self.charts = self.simfile.charts
        self.per_chart = self.isPerChart()
        self.audio_path = self.findMusic(simfile_path.parent)

        self.loadAudio()
        self.sync_data = self.analyze()

    def isPerChart(self):
        # same rule as SimfileParser.isPerChart
        for chart in self.charts:
            if hasattr(chart, "stops") or hasattr(chart, "bpms"):
                return True
        return False

    def findMusic(self, folder: Path) -> Path:
        # Prefer the #MUSIC tag, fall back to any single audio file
        music = self.simfile.music
        if music:
            tagged = folder / music
            if tagged.exists():
                return tagged
        options = [f for f in folder.iterdir() if f.suffix.lower() in AUDIO_EXTS]
        if music:
            stem_matches = [f for f in options if f.stem.lower() == Path(music).stem.lower()]
            if len(stem_matches) == 1:
                return stem_matches[0]
        if len(options) != 1:
            env.logger.error(f"{folder.name}: expected one audio file, found {len(options)}")
            raise RuntimeError
        return options[0]

    def loadAudio(self):
        audio = AudioSegment.from_file(str(self.audio_path), format=self.audio_path.suffix[1:])
        samples = np.array(audio.get_array_of_samples())
        if audio.channels == 2:
            samples = samples.reshape((-1, 2)).max(1)
        self.setSamples(samples / 2**15, audio.frame_rate)

    def audio_name(self) -> str:
        return self.audio_path.name

    def analyze(self):
        if not self.per_chart:
            return {"song": self.analyzeTiming(TimingData(self.simfile, self.charts[0])), "charts": None}

        # mirror SimfileParser.parseCharts: one entry per unique difficulty
        # letter, reusing results when charts share identical timing
        chart_syncs = []
        cache = {}
        diffs = ""
        for chart in self.charts:
            if chart.difficulty[0] in diffs:
                continue
            diffs += chart.difficulty[0]
            timing_data = TimingData(self.simfile, chart)
            key = repr(
                (timing_data.offset, timing_data.bpms, timing_data.stops, timing_data.delays, timing_data.warps)
            )
            if key not in cache:
                cache[key] = self.analyzeTiming(timing_data)
            chart_syncs.append(cache[key])
        return {"song": None, "charts": chart_syncs}

    def analyzeTiming(self, timing_data) -> dict:
        return self.fingerprint(self.beatTimes(TimingEngine(timing_data)))

    def beatTimes(self, engine):
        beat = 0
        while True:
            t = engine.time_at(beat)
            beat += 1
            if t > self.duration:
                return
            yield t
