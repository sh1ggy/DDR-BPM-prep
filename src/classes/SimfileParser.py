import env
import simfile

# from simfile import timing
# from simfile import notes

# from simfile.notes.timed import time_notes
from simfile.notes import NoteData
from simfile.notes.count import count_steps
from simfile.timing import Beat, TimingData
from simfile.timing.engine import TimingEngine


BPM_BUMP_TRIGGER_DIFF = 10
BPM_BUMP_SMOOTH_DIFF = 3
BPM_BUMP_DUR = 2
SHORT_FAST_BPM_DUR = 4.5
MIN_DOMINANT_BPM_DUR = 13
MOST_BPM_DUR = 30


def _sec2beat(sec, bpm):
    return Beat(sec * bpm / 60)


def _fmt(decimal, fmt=".3f"):
    return format(float(decimal), fmt)


def _round(x, nearest=1.0):
    return round(x / nearest) * nearest


def _printBPMs(bpm_times, bpm_vals) -> None:
    print("-----BPM changes-----")
    for st, ed, bpm in zip(bpm_times[:-1], bpm_times[1:], bpm_vals[:-1]):
        print(f"{_fmt(st)} -- {_fmt(ed)}: {_fmt(st-ed)} sec @ {_fmt(bpm)}")


def _printSTOPs(timing_data, timing_eng) -> None:
    print("-----STOPs-----")
    for stop in timing_data.stops:
        # timestamp
        stop_time = timing_eng.time_at(stop.beat)
        # duration in beats
        stop_beats = _sec2beat(stop.value, timing_eng.bpm_at(stop.beat))
        print(
            f"{_fmt(stop_time)} -- {_fmt(stop_time + stop.value)}: {_fmt(stop_beats)}"
        )


class SimfileParser:
    def __init__(self, simfile_path):
        self.simfile = simfile.open(simfile_path)
        self.charts = self.simfile.charts
        self.per_chart = self.isPerChart()

        self.measures = sum(c == "," for c in self.charts[0].notes)
        self.song_length = self.getSongLength()

        self.parseData()

    def parseData(self):
        title = self.simfile.title
        title_translit = self.simfile.titletranslit

        self.song_data = {
            "title": title,
            "titletranslit": title_translit or title,
            "song_length": float(_fmt(self.song_length)),
            "per_chart": self.per_chart,
        }
        self.levels_data = self.parseLevels()
        self.notecounts_data = self.parseNotecounts()
        self.radar_data = self.parseRadars()
        self.chart_data = self.parseCharts()

    def isPerChart(self):
        # per_chart if any chart has its own BPM/stops data
        # most songs (.sm) will have BPM/stops as part of the simfile
        for chart in self.charts:
            if hasattr(chart, "stops") or hasattr(chart, "bpms"):
                return True
        return False

    def getSongLength(self):
        chart = self.charts[0]
        timing_data = TimingData(self.simfile, chart)
        timing_eng = TimingEngine(timing_data)
        song_length = timing_eng.time_at(Beat(4 * self.measures))
        return song_length

    def parseLevels(self):
        sp_levels = {}
        dp_levels = {}
        for chart in self.charts:
            if chart.stepstype == "dance-double":
                dp_levels[chart.difficulty.lower()] = int(chart.meter)
            elif chart.stepstype == "dance-single":
                sp_levels[chart.difficulty.lower()] = int(chart.meter)
        return {"sp": sp_levels, "dp": dp_levels}

    def parseNotecounts(self):
        # steps as counted in-game: a jump counts as one step
        sp_counts = {}
        dp_counts = {}
        for chart in self.charts:
            notecount = count_steps(NoteData(chart))
            if chart.stepstype == "dance-double":
                dp_counts[chart.difficulty.lower()] = notecount
            elif chart.stepstype == "dance-single":
                sp_counts[chart.difficulty.lower()] = notecount
        return {"sp": sp_counts, "dp": dp_counts}

    def parseCharts(self):
        data = []
        if not self.per_chart:
            return self.parseChart(self.charts[0])

        diffs = ""
        for chart in self.charts:
            if chart.difficulty[0] not in diffs:
                diffs += chart.difficulty[0]
                data += self.parseChart(chart)
        # check difficulties are in order from Beginner to Challenge
        order = "BEMHC"
        assert diffs in order
        return data

    def parseChart(self, chart):
        timing_data = TimingData(self.simfile, chart)
        timing_eng = TimingEngine(timing_data)

        bpm_timestamps = [timing_eng.time_at(bpm.beat) for bpm in timing_data.bpms]
        bpm_timestamps.append(self.song_length)
        bpm_vals = [bpm.value for bpm in timing_data.bpms]
        bpm_vals.append(bpm_vals[-1])

        # displaybpm = self.simfile.displaybpm # some songs dont have displaybpm field. e.g. illegal function call
        data = self.parseBpm(bpm_timestamps, bpm_vals)

        data["stops"] = [
            self.processStop(timing_eng, stop) for stop in timing_data.stops
        ]

        return [data]

    def parseRadars(self):
        # radar is a per-chart quantity: group by style/difficulty like levels
        sp = {}
        dp = {}
        for chart in self.charts:
            radar = self.parseRadar(chart, TimingData(self.simfile, chart))
            if chart.stepstype == "dance-double":
                dp[chart.difficulty.lower()] = radar
            elif chart.stepstype == "dance-single":
                sp[chart.difficulty.lower()] = radar
        return {"sp": sp, "dp": dp}

    # Groove radar formulas per https://remywiki.com/GROOVE_RADAR
    def parseRadar(self, chart, timing_data):
        note = self._radarNoteData(chart)
        is_double = chart.stepstype == "dance-double"
        if not note:
            return {
                "stream": 0.0,
                "voltage": 0.0,
                "air": 0.0,
                "freeze": 0.0,
                "chaos": 0.0,
            }

        bpms = [[float(bpm.beat), float(bpm.value)] for bpm in timing_data.bpms]
        stops = [[float(stop.beat), float(stop.value)] for stop in timing_data.stops]

        stream = self._grStream(note, is_double)
        voltage = self._grVoltage(note)
        air = self._grAir(note, is_double)
        freeze = self._grFreeze(note, is_double)
        chaos = self._grChaos(note, bpms, stops, is_double)

        # no upper clamp: official radar values exceed 100 (up to ~312)
        def _pos(v):
            return float(_fmt(max(0.0, v)))

        return {
            "stream": _pos(stream),
            "voltage": _pos(voltage),
            "air": _pos(air),
            "freeze": _pos(freeze),
            "chaos": _pos(chaos),
        }

    def _songLenForRadar(self):
        return max(float(self.song_length), 0.001)

    def _radarNoteData(self, chart):
        measures = []
        for measure in chart.notes.split(","):
            rows = []
            for raw in measure.splitlines():
                row = raw.split("//", 1)[0].strip()
                if row:
                    rows.append(row)
            if rows:
                measures.append(rows)
        return measures

    def _sum1and2(self, arr):
        # steps + shock arrows ("M" rows), a jump counting as one step
        valid = ["1", "2", "4", "X", "x", "Y", "y", "S", "v", "M"]
        summed = 0
        for beat in arr:
            for note in beat:
                summed += int(sum(note.count(x) for x in valid) >= 1)
        return summed

    def _sumJumps(self, arr):
        valid = ["1", "2", "4", "X", "x", "Y", "y", "S", "v"]
        summed = 0
        for beat in arr:
            for note in beat:
                if sum(note.count(x) for x in valid) >= 2:
                    summed += 1
        return summed

    def _sumMines(self, arr):
        summed = 0
        for beat in arr:
            for note in beat:
                summed += int(note.count("M") >= 1)
        return summed

    def _sumFreezeTime(self, arr):
        if not arr or not arr[0]:
            return 0.0
        gm_num = len(arr[0][0])
        last = [-1.0 for _ in range(gm_num)]
        holds = []
        for beat in range(len(arr)):
            for note in range(len(arr[beat])):
                curr = beat + (note / len(arr[beat]))
                for lane in range(gm_num):
                    lane_note = arr[beat][note][lane]
                    if lane_note == "2" or lane_note == "4":
                        last[lane] = curr
                    elif lane_note == "3" and last[lane] != -1:
                        holds.append((last[lane], curr - last[lane]))
                        last[lane] = -1
        # freezes starting simultaneously: only the longer one counts
        by_start = {}
        for start, dur in holds:
            by_start[start] = max(by_start.get(start, 0.0), dur)
        return sum(by_start.values())

    def _chaosBaseValue(self, arr):
        # per-note base value: note color x arrows / interval from last note;
        # (quantization / interval-in-quantization-units) reduces to 1 / the
        # interval in measures. First note contributes 0.
        valid = ["1", "2", "4", "X", "x", "Y", "y", "S", "v"]
        base = 0.0
        last = None
        for beat in range(len(arr)):
            for note in range(len(arr[beat])):
                row = arr[beat][note]
                arrows = sum(row.count(x) for x in valid) + row.count("M")
                if arrows == 0:
                    continue
                fraction = note / len(arr[beat])
                if fraction % 0.25 == 0:
                    color = 0.0
                elif fraction % 0.125 == 0:
                    color = 0.5
                elif fraction % 0.0625 == 0:
                    color = 1.0
                else:
                    color = 1.25
                current = beat + fraction
                if last is not None:
                    dist = current - last
                    if dist > 0:
                        base += color * arrows / dist
                last = current
        return base

    def _totalBpmDelta(self, bpms, stops):
        # sum of |BPM changes|; each stop contributes the BPM in effect after
        # it (a change landing exactly on a stop is covered by the stop rule)
        stop_beats = {float(s[0]) for s in stops}
        delta = 0.0
        for (_, val), (beat2, val2) in zip(bpms[:-1], bpms[1:]):
            if beat2 not in stop_beats:
                delta += abs(val - val2)
        for stop_beat in stop_beats:
            after = [val for beat, val in bpms if beat <= stop_beat]
            delta += after[-1] if after else bpms[0][1]
        return delta

    def _grStream(self, note, is_double):
        npm = int((60.0 * self._sum1and2(note)) / self._songLenForRadar())
        if npm <= 300:
            return npm / 3
        if is_double:
            return (npm - 183) * 100 / 117
        return (npm - 139) * 100 / 161

    def _grVoltage(self, note):
        # peak density = max steps in any 4 consecutive beats (not measures)
        valid = ["1", "2", "4", "X", "x", "Y", "y", "S", "v", "M"]
        beats = []
        for measure in note:
            per_beat = [0, 0, 0, 0]
            for i, row in enumerate(measure):
                if sum(row.count(x) for x in valid) >= 1:
                    per_beat[int(i * 4 / len(measure))] += 1
            beats.extend(per_beat)
        avgbpm = 60.0 * len(beats) / self._songLenForRadar()
        maxdensity = 0
        for i in range(max(1, len(beats) - 3)):
            maxdensity = max(maxdensity, sum(beats[i : i + 4]))
        avg_peak_density = int(avgbpm * maxdensity / 4)
        if avg_peak_density <= 600:
            return avg_peak_density / 6
        return (avg_peak_density + 594) * 100 / 1194

    def _grAir(self, note, is_double):
        jpm = int(
            (60.0 * (self._sumJumps(note) + self._sumMines(note)))
            / self._songLenForRadar()
        )
        if jpm <= 55:
            return jpm * 20 / 11
        if is_double:
            return (jpm + 35) * 10 / 9
        return (jpm + 36) * 100 / 91

    def _grFreeze(self, note, is_double):
        if not note:
            return 0.0
        # Use beat-domain lengths for denominator semantics.
        freezelen_beats = 4.0 * self._sumFreezeTime(note)
        song_beats = max(4.0 * len(note), 0.001)
        farrowrate = int((10000.0 * freezelen_beats) / song_beats)
        if farrowrate <= 3500:
            return farrowrate / 35
        if is_double:
            return (farrowrate + 2246) * 100 / 5746
        return (farrowrate + 2484) * 100 / 5984

    def _grChaos(self, note, bpms, stops, is_double):
        basechaos = self._chaosBaseValue(note)
        totalbpmchange = self._totalBpmDelta(bpms, stops) if bpms else 0.0
        bpmchangepm = 60.0 * totalbpmchange / self._songLenForRadar()
        chaosdegree = basechaos * (1 + (bpmchangepm / 1500))
        chaosunit = int(chaosdegree * 100 / self._songLenForRadar())
        if chaosunit <= 2000:
            return chaosunit / 20
        if is_double:
            return (chaosunit + 16628) * 100 / 18628
        return (chaosunit + 21605) * 100 / 23605

    """
    TODO - calculate beats @ pre/post-bpms. If one of them is close to a nice number (1/3, 1/2, 1), then use it.
    Examples to consider: 
        Pluto - .48s (1 beat @ 125 bpm, 1.04 beat @ 130 bpm)
        out of focus - 1st stop/slowdown (1.75 beats @ 167 bpm, .875 beats @ 84 bpm)
        Max.(period) - 1st stop (6.646 beats @ 300 bpm to 4 beats @ 180 bpm)
    """

    def processStop(self, timing_eng, stop):
        stop_time = timing_eng.time_at(stop.beat)
        bpm_pre = round(timing_eng.bpm_at(stop.beat - 1))
        bpm_post = round(timing_eng.bpm_at(stop.beat + 1))

        convert = lambda bpm: float(_fmt(_sec2beat(stop.value, bpm)))
        beats_pre = convert(bpm_pre)
        beats_post = convert(bpm_post)

        def _niceness(x):
            to_third = abs(x - _round(x, nearest=1 / 3))
            to_quarter = abs(x - _round(x, nearest=1 / 4))
            return (to_third, 1 / 3) if to_third < to_quarter else (to_quarter, 1 / 4)

        nice_pre, denom_pre = _niceness(beats_pre)
        nice_post, denom_post = _niceness(beats_post)

        if nice_pre <= nice_post and nice_pre <= 0.05:
            beats = [{"bpm": bpm_pre, "val": _round(beats_pre, nearest=denom_pre)}]
        elif nice_post <= 0.05:
            beats = [{"bpm": bpm_post, "val": _round(beats_post, nearest=denom_post)}]
        else:
            env.logger.debug(self.simfile.title + "\n\t" + "no nice stop bpm found")
            # TODO - something?
            beats = [
                {"bpm": bpm_pre, "val": convert(bpm_pre)},
                {"bpm": bpm_post, "val": convert(bpm_post)},
            ]

        return {
            "st": float(_fmt(stop_time)),
            "dur": float(_fmt(stop.value)),
            "beats": beats,
        }

    def parseBpm(self, bpm_times, bpm_vals):
        bpms = [
            {"st": float(_fmt(st)), "ed": float(_fmt(ed)), "val": round(val)}
            for st, ed, val in zip(bpm_times[:-1], bpm_times[1:], bpm_vals[:-1])
        ]

        bpms = self.cleanBPM(bpms)

        d = {}
        dominant_bpm, dominant_dur = self.dominantBPM(bpms)
        d["dominant_bpm"] = dominant_bpm

        # Get actual min/max bpm, actual meaning the bpm must last a significant amount of duration
        # true_min/max is instantaneous min/max bpm
        durs = list(map(lambda x: x["ed"] - x["st"], bpms))
        vals = list(map(lambda x: x["val"], bpms))
        d["true_min"] = _max = min(vals)
        d["true_max"] = _min = max(vals)
        for dur, val in zip(durs, vals):
            if dur < SHORT_FAST_BPM_DUR and dominant_dur > MIN_DOMINANT_BPM_DUR:
                continue
            if val < _min:
                _min = val
            if val > _max:
                _max = val

        d["bpm_range"] = (
            f"{d['true_min']}~{dominant_bpm}~{d['true_max']}" if _min != _max else f"{dominant_bpm}"
        )
        d["bpms"] = bpms
        return d

    def cleanBPM(self, bpms):
        """
        smoothen bpm bumps & merge consecutive sections with equal bpm
        """

        # skip
        if self.simfile.titletranslit == "deltaMAX":
            return bpms

        new = [bpms.pop(0)]
        while bpms:
            b2 = bpms.pop(0)
            st, ed, val = new[-1].values()
            st2, ed2, val2 = b2.values()

            # false bpm bump?
            if abs(val2 - val) <= BPM_BUMP_TRIGGER_DIFF:
                if abs(val2 - val) <= BPM_BUMP_SMOOTH_DIFF and (ed - st) < BPM_BUMP_DUR:
                    new[-1]["val"] = val2 if (ed2 - st2) > (ed - st) else val
                    new[-1]["ed"] = ed2
                    env.logger.info(
                        self.simfile.title
                        + "\n\t"
                        + f'bpm bump {st}~{ed}~{ed2} @ {val}~{val2} -> {st}~{ed2} @ {new[-1]["val"]}'
                    )
                else:
                    env.logger.debug(
                        self.simfile.title
                        + "\n\t"
                        + f"bpm bump {st}~{ed}~{ed2} @ {val}~{val2}"
                    )
                    new.append(b2)
                    continue

            # check for matching bpm, noting new[-1] may have changed
            st, ed, val = new[-1].values()
            if val == val2:
                new[-1]["ed"] = ed2
            else:
                new.append(b2)
                continue

        return new

    def dominantBPM(self, bpms):
        # compute dominant BPM of song
        d = {}
        for bpm in bpms:
            st, ed, val = bpm.values()
            val = int(val)
            st = float(st)
            ed = float(ed)

            if val in d.keys():
                d[val] += ed - st  # / self.song_length
            else:
                d[val] = ed - st  # / self.song_length

        dominant_bpm = max(d, key=d.get)
        dominant_dur = d[dominant_bpm]
        for k, v in d.items():
            if k > dominant_bpm and (
                v > MOST_BPM_DUR or dominant_dur < MIN_DOMINANT_BPM_DUR
            ):
                dominant_bpm = k
                dominant_dur = v

        return dominant_bpm, dominant_dur
