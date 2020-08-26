import sys
import time
import itertools
import enum
import wave
import numpy as np
import pyaudio
import realtime_analysis as ra

RATE = 44100
SAMPLES_PER_BUFFER = 1024
WIN_LENGTH = 512*4
HOP_LENGTH = 512
PRE_MAX = int(0.03 * RATE / HOP_LENGTH)
POST_MAX = int(0.03 * RATE / HOP_LENGTH)
PRE_AVG = int(0.03 * RATE / HOP_LENGTH)
POST_AVG = int(0.03 * RATE / HOP_LENGTH)
WAIT = int(0.03 * RATE / HOP_LENGTH)
DELTA = 8.2e-06 * 20 # noise_power * 20
# frame resolution: 11.6 ms
# delay: 30 ms
# fastest tempo: 2000 bpm

DISPLAY_FPS = 200
DISPLAY_DELAY = 0.03
KNOCK_VOLUME = HOP_LENGTH / RATE / 0.00017 # Dt / knock_max_energy
KNOCK_DELAY = 0.0

TRACK_WIDTH = 100
BAR_OFFSET = 0.1
DROP_SPEED = 0.5 # screen per sec
TOLERANCES = (0.02, 0.06, 0.10, 0.14)


# beats and performances
class Beat:
    def click(self):
        if isinstance(self, Beat.Soft):
            return ra.pulse(sr=RATE, freq=1000.0, decay_time=0.01, amplitude=0.5)

        elif isinstance(self, Beat.Loud):
            return ra.pulse(sr=RATE, freq=1000.0, decay_time=0.01, amplitude=1.0)

        elif isinstance(self, Beat.Incr):
            amplitude = 0.5 + 0.5 * (self.count-1)/self.total
            return ra.pulse(sr=RATE, freq=1000.0, decay_time=0.01, amplitude=amplitude)

        elif isinstance(self, Beat.Roll):
            sound = ra.pulse(sr=RATE, freq=1000.0, decay_time=0.01, amplitude=1.0)
            step = (self.end - self.time)/self.number
            signals = [(step*i, sound) for i in range(self.number)]
            duration = self.end - self.time
            gen = ra.pipe(ra.empty(RATE, SAMPLES_PER_BUFFER, duration),
                          ra.attach(signals, RATE, SAMPLES_PER_BUFFER))
            return np.concatenate(list(gen))

    @property
    def total_score(self):
        if isinstance(self, (Beat.Soft, Beat.Loud, Beat.Incr)):
            return 10
        elif isinstance(self, Beat.Roll):
            return 10 + (self.number - 1) * 2

    @property
    def score(self):
        if isinstance(self, (Beat.Soft, Beat.Loud, Beat.Incr)):
            return self.perf.score if self.perf is not None else 0
        elif isinstance(self, Beat.Roll):
            if self.perf is None:
                return 0
            elif self.roll == 0:
                return self.perf.score
            elif self.roll < self.number:
                return self.perf.score + (self.roll - 1) * 2
            elif self.roll < 2*self.number:
                return self.perf.score + (2*self.number - self.roll - 1) * 2
            else:
                return self.perf.score

class Soft(Beat):
    def __init__(self, time, speed=1.0, perf=None):
        super().__init__()
        self.time = time
        self.speed = speed
        self.perf = perf

    def __repr__(self):
        return "Beat.Soft(time={!r}, speed={!r}, perf={!r})".format(self.time, self.speed, self.perf)
Beat.Soft = Soft

class Loud(Beat):
    def __init__(self, time, speed=1.0, perf=None):
        super().__init__()
        self.time = time
        self.speed = speed
        self.perf = perf

    def __repr__(self):
        return "Beat.Loud(time={!r}, speed={!r}, perf={!r})".format(self.time, self.speed, self.perf)
Beat.Loud = Loud

class Incr(Beat):
    def __init__(self, time, count, total, speed=1.0, perf=None):
        super().__init__()
        self.time = time
        self.count = count
        self.total = total
        self.speed = speed
        self.perf = perf

    def __repr__(self):
        return "Beat.Incr(time={!r}, count={!r}, total={!r}, speed={!r}, perf={!r})".format(
                        self.time, self.count, self.total, self.speed, self.perf)
Beat.Incr = Incr

class Roll(Beat):
    def __init__(self, time, end, number, speed=1.0, perf=None, roll=0):
        super().__init__()
        self.time = time
        self.end = end
        self.number = number
        self.speed = speed
        self.perf = perf
        self.roll = roll

    def __repr__(self):
        return "Beat.Roll(time={!r}, end={!r}, number={!r}, speed={!r}, perf={!r}, roll={!r})".format(
                        self.time, self.end, self.number, self.speed, self.perf, self.roll)
Beat.Roll = Roll

class Performance(enum.Enum):
    MISS               = ("Miss"                      , 0)
    GREAT              = ("Great"                     , 10)
    LATE_GOOD          = ("Late Good"                 , 5)
    EARLY_GOOD         = ("Early Good"                , 5)
    LATE_BAD           = ("Late Bad"                  , 3)
    EARLY_BAD          = ("Early Bad"                 , 3)
    LATE_FAILED        = ("Late Failed"               , 0)
    EARLY_FAILED       = ("Early Failed"              , 0)
    GREAT_WRONG        = ("Great but Wrong Key"       , 5)
    LATE_GOOD_WRONG    = ("Late Good but Wrong Key"   , 3)
    EARLY_GOOD_WRONG   = ("Early Good but Wrong Key"  , 3)
    LATE_BAD_WRONG     = ("Late Bad but Wrong Key"    , 1)
    EARLY_BAD_WRONG    = ("Early Bad but Wrong Key"   , 1)
    LATE_FAILED_WRONG  = ("Late Failed but Wrong Key" , 0)
    EARLY_FAILED_WRONG = ("Early Failed but Wrong Key", 0)

    def __repr__(self):
        return "Performance." + self.name

    def __str__(self):
        return self.value[0]

    @property
    def score(self):
        return self.value[1]


# beatmap
class Beatmap:
    def __init__(self, filename, beats):
        self.beats = tuple(beats)
        self.hit = dict(number=-1, strength=-1.0, beat=None)

        if isinstance(filename, float):
            self.file = None
            self.duration = filename
        else:
            self.file = wave.open(filename, "rb")
            self.duration = self.file.getnframes() / self.file.getframerate()

        self.spectrum = " "*5

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self.file is not None:
            self.file.close()

    @property
    def total_score(self):
        return sum(beat.total_score for beat in self.beats)

    @property
    def score(self):
        return sum(beat.score for beat in self.beats)

    @property
    def progress(self):
        if len(self.beats) == 0:
            return 1000
        return sum(1 for beat in self.beats if beat.perf is not None) * 1000 // len(self.beats)

    def get_sound_handler(self, sr, buffer_length, win_length):
        if self.file is None:
            sound = ra.empty(RATE, SAMPLES_PER_BUFFER, self.duration)
        else:
            sound = ra.load(self.file, sr, buffer_length)

        signals = [(beat.time, beat.click()) for beat in self.beats]
        spec = ra.pipe(ra.frame(win_length, buffer_length),
                       ra.power_spectrum(sr, win_length, windowing=True, weighting=False),
                       ra.draw_spectrum(len(self.spectrum), sr, win_length, decay=(buffer_length/sr)/0.01),
                       lambda s: setattr(self, "spectrum", s))

        return ra.pipe(sound, ra.branch(spec), ra.attach(signals, RATE, SAMPLES_PER_BUFFER))

    @ra.DataNode.from_generator
    def get_knock_handler(self, tolerances):
        beats = iter(self.beats)
        incr_tol = 0.1

        incr_threshold = 0.0
        hit_number = 0

        beat = next(beats, None)
        while True:
            time, strength, detected = yield

            # if next beat has passed through
            if isinstance(beat, Beat.Roll) and beat.roll != 0 and beat.end - tolerances[2] < time:
                beat = next(beats, None)

            if not isinstance(beat, Beat.Roll) or beat.roll == 0:
                while beat is not None and beat.time + tolerances[3] < time:
                    beat.perf = Performance.MISS
                    beat = next(beats, None)

            # update state
            if not detected:
                continue
            self.hit = dict(number=hit_number, strength=strength, beat=beat)
            hit_number += 1

            # if next beat isn't in the range yet
            if beat is None or beat.time - tolerances[3] >= time:
                continue

            # drumrolls
            if isinstance(beat, Beat.Roll):
                beat.roll += 1
                if beat.roll > 1:
                    continue

            # judge pressed key (determined by loudness)
            if isinstance(beat, Beat.Soft):
                is_correct_key = strength < 0.5
            elif isinstance(beat, Beat.Loud):
                is_correct_key = strength >= 0.5
            elif isinstance(beat, Beat.Incr):
                is_correct_key = strength >= incr_threshold - incr_tol
            elif isinstance(beat, Beat.Roll):
                is_correct_key = True

            # judge accuracy
            err = abs(time - beat.time)
            too_late = time > beat.time

            if err < tolerances[0]:
                if is_correct_key:
                    perf = Performance.GREAT
                else:
                    perf = Performance.GREAT_WRONG

            elif err < tolerances[1]:
                if is_correct_key:
                    perf = Performance.LATE_GOOD         if too_late else Performance.EARLY_GOOD
                else:
                    perf = Performance.LATE_GOOD_WRONG   if too_late else Performance.EARLY_GOOD_WRONG

            elif err < tolerances[2]:
                if is_correct_key:
                    perf = Performance.LATE_BAD          if too_late else Performance.EARLY_BAD
                else:
                    perf = Performance.LATE_BAD_WRONG    if too_late else Performance.EARLY_BAD_WRONG

            else:
                if is_correct_key:
                    perf = Performance.LATE_FAILED       if too_late else Performance.EARLY_FAILED
                else:
                    perf = Performance.LATE_FAILED_WRONG if too_late else Performance.EARLY_FAILED_WRONG

            beat.perf = perf

            # add hit and wait for next beat
            incr_threshold = max(strength, incr_threshold) if isinstance(beat, Beat.Incr) else 0.0
            if not isinstance(beat, Beat.Roll):
                beat = next(beats, None)

    @ra.DataNode.from_generator
    def get_screen_handler(self, drop_speed, track_width, bar_offset):
        dt = 1.0 / track_width / drop_speed
        sustain = 0.1 / drop_speed
        decay = 0.2 / drop_speed
        bar_index = int(track_width * bar_offset)

        beats_syms = ["□", "■", "◬", "◎"]
        target_sym = "⛶"

        hit_number = -1
        hit_time = -1.0
        loudness_syms = ["🞎", "🞏", "🞐", "🞑", "🞒", "🞓"]
        accuracy_syms = ["⟪", "⟪", "⟨", "⟩", "⟫", "⟫"]
        correct_sym = "˽"

        def range_of(beat):
            cross_time = (track_width / abs(beat.speed) + 1.0) * dt
            if isinstance(beat, Beat.Roll):
                return (beat.time-cross_time, beat.end+cross_time)
            else:
                return (beat.time-cross_time, beat.time+cross_time)

        dripping_beats = ra.drip(self.beats, range_of)

        current_time = yield
        while True:
            view = [" "]*track_width

            # draw un-hitted beats, it also catches the last visible beat
            beats = dripping_beats.send(current_time)
            beats = sorted(beats, key=lambda b: (b.time>current_time-dt, -b.time))
            for beat in beats:
                velocity = track_width * drop_speed * beat.speed

                if isinstance(beat, Beat.Roll):
                    step_time = (beat.end - beat.time) / beat.number

                    for r in range(beat.number)[beat.roll:]:
                        pixel = bar_index + int((beat.time + step_time * r - current_time) / dt * beat.speed)
                        if pixel in range(track_width):
                            view[pixel] = beats_syms[3]
                    continue

                if beat.perf in (None, Performance.MISS):
                    pixel = bar_index + int((beat.time - current_time) / dt * beat.speed)

                    if isinstance(beat, Beat.Soft):
                        symbol = beats_syms[0]
                    elif isinstance(beat, Beat.Loud):
                        symbol = beats_syms[1]
                    elif isinstance(beat, Beat.Incr):
                        symbol = beats_syms[2]

                    if pixel in range(track_width):
                        view[pixel] = symbol

            # draw target
            view[bar_index] = target_sym

            if hit_number != self.hit["number"]:
                hit_number = self.hit["number"]
                hit_time = current_time

            # visual feedback for hit strength
            if current_time - hit_time < decay:
                strength = min(1.0, self.hit["strength"])
                strength -= (current_time - hit_time) / decay
                if strength >= 0:
                    view[bar_index] = loudness_syms[int(strength * (len(loudness_syms) - 1))]

            # visual feedback for hit accuracy
            if current_time - hit_time < sustain and self.hit["beat"] is not None:
                correct_types = (Performance.GREAT,
                                 Performance.LATE_GOOD, Performance.EARLY_GOOD,
                                 Performance.LATE_BAD, Performance.EARLY_BAD,
                                 Performance.LATE_FAILED, Performance.EARLY_FAILED)
                perf = self.hit["beat"].perf
                if perf in correct_types:
                    view[bar_index+1] = correct_sym

                if perf in (Performance.LATE_GOOD, Performance.LATE_GOOD_WRONG):
                    view[bar_index-1] = accuracy_syms[2]
                elif perf in (Performance.EARLY_GOOD, Performance.EARLY_GOOD_WRONG):
                    view[bar_index+2] = accuracy_syms[3]
                elif perf in (Performance.LATE_BAD, Performance.LATE_BAD_WRONG):
                    view[bar_index-1] = accuracy_syms[1]
                elif perf in (Performance.EARLY_BAD, Performance.EARLY_BAD_WRONG):
                    view[bar_index+2] = accuracy_syms[4]
                elif perf in (Performance.LATE_FAILED, Performance.LATE_FAILED_WRONG):
                    view[bar_index-1] = accuracy_syms[0]
                elif perf in (Performance.EARLY_FAILED, Performance.EARLY_FAILED_WRONG):
                    view[bar_index+2] = accuracy_syms[5]

            # print
            out = ""
            out = out + " " + self.spectrum + " "
            out = out + "[{:>5d}/{:>5d}]".format(self.score, self.total_score)
            out = out + "".join(view)
            out = out + " [{:>5.1f}%]".format(self.progress/10)

            current_time = yield out

# console
class KnockConsole:
    def __init__(self):
        self.pyaudio = pyaudio.PyAudio()

    def __del__(self):
        self.pyaudio.terminate()

    def get_output_stream(self, sound_handler):
        def output_callback(in_data, frame_count, time_info, status):
            out_data = next(sound_handler, None)
            if out_data is None:
                return b'', pyaudio.paComplete
            else:
                return out_data.tobytes(), pyaudio.paContinue

        output_stream = self.pyaudio.open(format=pyaudio.paFloat32,
                                          channels=1,
                                          rate=RATE,
                                          input=False,
                                          output=True,
                                          frames_per_buffer=SAMPLES_PER_BUFFER,
                                          stream_callback=output_callback,
                                          start=False)

        return output_stream

    def get_input_stream(self, knock_handler):
        pick_peak = ra.pick_peak(pre_max=PRE_MAX, post_max=POST_MAX,
                                 pre_avg=PRE_AVG, post_avg=POST_AVG,
                                 wait=WAIT, delta=DELTA)
        halfhann_window = np.sin(np.linspace(0, np.pi/2, WIN_LENGTH))**2
        dect = ra.pipe(ra.frame(WIN_LENGTH, HOP_LENGTH),
                       ra.power_spectrum(RATE, WIN_LENGTH, windowing=halfhann_window, weighting=True),
                       ra.onset_strength(RATE/WIN_LENGTH),
                       (lambda a: (None, a, a)),
                       ra.pair(itertools.count(-pick_peak.delay), ra.delay(pick_peak.delay), pick_peak),
                       (lambda a: (a[0]*HOP_LENGTH/RATE-KNOCK_DELAY, (a[1] or 0.0)*KNOCK_VOLUME, a[2])),
                       knock_handler)

        def input_callback(in_data, frame_count, time_info, status):
            audio_data = np.frombuffer(in_data, dtype=np.float32)

            for i in range(0, frame_count, HOP_LENGTH):
                dect.send(audio_data[i:i+HOP_LENGTH])

            return in_data, pyaudio.paContinue

        input_stream = self.pyaudio.open(format=pyaudio.paFloat32,
                                         channels=1,
                                         rate=RATE,
                                         input=True,
                                         output=False,
                                         frames_per_buffer=SAMPLES_PER_BUFFER,
                                         stream_callback=input_callback,
                                         start=False)

        return input_stream

    def play(self, beatmap):
        with beatmap:
            sound_handler = beatmap.get_sound_handler(RATE, SAMPLES_PER_BUFFER, WIN_LENGTH)
            knock_handler = beatmap.get_knock_handler(TOLERANCES)
            screen_handler = beatmap.get_screen_handler(DROP_SPEED, TRACK_WIDTH, BAR_OFFSET)

            output_stream = self.get_output_stream(sound_handler)
            input_stream = self.get_input_stream(knock_handler)

            try:
                reference_time = time.time()
                input_stream.start_stream()
                output_stream.start_stream()

                while output_stream.is_active() and input_stream.is_active():
                    view = screen_handler.send(time.time() - reference_time - DISPLAY_DELAY)
                    sys.stdout.write(" ")
                    sys.stdout.write(view)
                    sys.stdout.write("\r")
                    sys.stdout.flush()
                    time.sleep(1/DISPLAY_FPS)

            finally:
                output_stream.stop_stream()
                input_stream.stop_stream()
                output_stream.close()
                input_stream.close()


# test
# beatmap = Beatmap(9.0, [Beat.Loud(1.0 + t*0.5) for t in range(16)])
beatmap = Beatmap(9.0, [Beat.Soft(1.0), Beat.Loud(1.5, -0.5), Beat.Soft(2.0), Beat.Soft(2.25), Beat.Loud(2.5, 0.5),
                        Beat.Soft(3.0), Beat.Loud(3.5, -0.5), Beat.Soft(4.0), Beat.Soft(4.25),
                        Beat.Roll(4.5, 5.0, 4, 1.5),
                        Beat.Soft(5.0), Beat.Loud(5.5, -0.5), Beat.Soft(6.0), Beat.Soft(6.25), Beat.Loud(6.5, 0.5),
                        Beat.Incr(7.0, 1, 6, 0.5), Beat.Incr(7.25, 2, 6, 0.7), Beat.Incr(7.5, 3, 6, 0.9),
                        Beat.Incr(7.75, 4, 6, 1.1), Beat.Incr(8.0, 5, 6, 1.3), Beat.Incr(8.25, 6, 6, 1.5),
                        Beat.Loud(8.5, 1.7)])
# beatmap = Beatmap("test_scale.wav", [])
# beatmap = Beatmap(10.0, [])

# def from_pattern(t0, dt, pattern):
#     incring = None
#     for j, c in enumerate(pattern):
#         if incring is not None and c != ",":
#             for n, t in enumerate(incring):
#                 yield Beat.Incr(t, n+1, len(incring))
#             incring = None

#         if c == ".":
#             yield Beat.Soft(t0 + j/2*dt)
#         elif c == "-":
#             yield Beat.Loud(t0 + j/2*dt)
#         elif c == ":":
#             yield Beat.Roll(t0 + j/2*dt, t0 + (j+1)/2*dt, 2)
#         elif c == ",":
#             incring = (incring or []) + [t0 + j/2*dt]
# test_beats = list(from_pattern(2.233, 60.0/140.0,
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-..:- "
#     #| - | - | - | - |
#     "..- ..- ..- - - "
#     "..- ..- ..- - - "
#     "..- ..- ..- -.-."
#     ",,,,,,,,-             - "
#     #| - | - | - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "

#     #| - | - | - | - |
#     ". -..- .-..-  - "
#     ". -..- .-..-  -."
#     ". -..- .-..-  - "
#     ". -..- .-..-- - "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-..:- "
#     #| - | - | - | - |
#     "..- ..- ..- - - "
#     "..- ..- ..- - - "
#     "..- ..- ..- -.-."
#     ",,,,,,,,-     - "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-:- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-..:- "

#     #| - | - | - | - |
#     "..-  .- ..-  .- "
#     "..-  .- ..- ..- "
#     "..-  .- ..-  .- "
#     "..-.. -. .-. .- "
#     #| - | - | - | - |
#     "- - - - - - - - "
#     "- - - - - - - - "
#     "-       -       "
#     ".  . . ..       "
#     "              - "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -..- .-..-  - "
#     ". -..- .-.. - - "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.-.- "
#     #| - | - | - | - |
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-.. - "
#     ". -.. -. .-..:- "
#     ))
# beatmap = Beatmap("test_music.wav", test_beats)

console = KnockConsole()
console.play(beatmap)
print()
for beat in beatmap.beats:
    print(beat)
