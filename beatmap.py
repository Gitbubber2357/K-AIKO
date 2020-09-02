import enum
import wave
import curses
import numpy
import realtime_analysis as ra


TOLERANCES = (0.02, 0.06, 0.10, 0.14)
#             GREAT GOOD  BAD   FAILED
BEATS_SYMS = ("□", "■", "◬", "◎", "◴◵◶◷")
#             Soft Loud Incr Roll Spin
PERF_SYMS = ("⟪", "⟪", "⟨", "˽", "⟩", "⟫", "⟫")
SPIN_FINISHED_SYM = "😊"
TARGET_SYMS = ("⛶", "🞎", "🞏", "🞐", "🞑", "🞒", "🞓")

INCR_TOL = 0.1
DROP_SPEED = 0.5 # screen per sec
SPEC_WIDTH = 5
HIT_DECAY = 0.4
HIT_SUSTAIN = 0.1


# beats and performances
class Beat:
    tolerances = TOLERANCES

    # lifespan, speed, score, total_score, finished
    # def hit(self, time, strength): pass
    # def finish(self): pass
    # def sound(self, sr): pass
    # def draw(self, track, time, drop_speed): pass

    def draw_judging(self, track, time): pass
    def draw_hitting(self, track, time): pass

class SingleBeat(Beat):
    total_score = 10
    perf_syms = PERF_SYMS

    def __init__(self, time, speed=1.0, perf=None):
        self.time = time
        self.speed = speed
        self.perf = perf

    @property
    def lifespan(self):
        return (self.time - self.tolerances[3], self.time + self.tolerances[3])
    
    @property
    def score(self):
        return self.perf.score if self.perf is not None else 0

    @property
    def finished(self):
        return self.perf is not None

    def finish(self):
        self.perf = Performance.MISS

    def hit(self, time, strength, is_correct_key):
        self.perf = Performance.judge(time - self.time, is_correct_key, self.tolerances)

    def draw(self, track, time, drop_speed):
        if self.perf in (None, Performance.MISS):
            pos = (self.time - time) * drop_speed * self.speed
            track.draw(pos, self.symbol)

    def draw_hitting(self, track, time):
        self.perf.draw(track, self.speed < 0, self.perf_syms)

class Soft(SingleBeat):
    total_score = 10
    symbol = BEATS_SYMS[0]

    def hit(self, time, strength):
        super().hit(time, strength, strength < 0.5)

    def sound(self, sr):
        return ra.pulse(sr=sr, freq=1000.0, decay_time=0.01, amplitude=0.5)

    def __repr__(self):
        return "Soft(time={!r}, speed={!r}, perf={!r})".format(self.time, self.speed, self.perf)
Beat.Soft = Soft

class Loud(SingleBeat):
    total_score = 10
    symbol = BEATS_SYMS[1]

    def hit(self, time, strength):
        super().hit(time, strength, strength >= 0.5)

    def sound(self, sr):
        return ra.pulse(sr=sr, freq=1000.0, decay_time=0.01, amplitude=1.0)

    def __repr__(self):
        return "Loud(time={!r}, speed={!r}, perf={!r})".format(self.time, self.speed, self.perf)
Beat.Loud = Loud

class IncrLevel:
    def __init__(self, threshold=0.0, total=0):
        self.threshold = threshold
        self.total = total

    def add(self, time, speed=1.0, perf=None):
        self.total += 1
        return Incr(time, speed, perf, count=self.total, level=self)

    def hit(self, strength):
        self.threshold = max(self.threshold, strength)

    def __repr__(self):
        return "IncrLevel(threshold={!r}, total={!r})".format(self.threshold, self.total)

class Incr(SingleBeat):
    total_score = 10
    symbol = BEATS_SYMS[2]
    incr_tol = INCR_TOL

    def __init__(self, time, speed=1.0, perf=None, count=None, level=None):
        super().__init__(time, speed, perf)
        if count is None or level is None:
            raise ValueError
        self.count = count
        self.level = level

    def hit(self, time, strength):
        super().hit(time, strength, strength >= self.level.threshold - self.incr_tol)
        self.level.hit(strength)

    def sound(self, sr):
        amplitude = 0.5 + 0.5 * (self.count-1)/self.level.total
        return ra.pulse(sr=sr, freq=1000.0, decay_time=0.01, amplitude=amplitude)

    def __repr__(self):
        return "Incr(time={!r}, speed={!r}, perf={!r}, count={!r}, level={!r})".format(
                     self.time, self.speed, self.perf, self.count, self.level)
Beat.Incr = Incr

class Roll(Beat):
    symbol = BEATS_SYMS[3]

    def __init__(self, time, end, number, speed=1.0, roll=0, finished=False, endpoint=True):
        if not endpoint:
            end = time + (end - time)/number*(number-1)
        self.time = time
        self.end = end
        self.speed = speed
        self.number = number
        self.roll = roll
        self.finished = finished

    @property
    def lifespan(self):
        return (self.time - self.tolerances[2], self.end)

    @property
    def total_score(self):
        return self.number * 2

    @property
    def score(self):
        if self.roll < self.number:
            return self.roll * 2
        elif self.roll < 2*self.number:
            return (2*self.number - self.roll) * 2
        else:
            return 0

    def hit(self, time, strength):
        self.roll += 1

    def finish(self):
        self.finished = True

    def sound(self, sr):
        sound = ra.pulse(sr=sr, freq=1000.0, decay_time=0.01, amplitude=1.0)
        step = (self.end - self.time)/(self.number-1) if self.number > 1 else 0.0
        rolls_sounds = [(step*i, sound) for i in range(self.number)]
        duration = self.end - self.time + 0.01

        beats_sounds = ra.pipe(ra.empty(sr, duration=duration),
                               ra.attach(rolls_sounds, sr))
        return numpy.concatenate(list(beats_sounds))

    def draw(self, track, time, drop_speed):
        step = (self.end - self.time)/(self.number-1) if self.number > 1 else 0.0

        for r in range(self.number):
            if r > self.roll-1:
                pos = (self.time + step * r - time) * drop_speed * self.speed
                track.draw(pos, self.symbol)

    def __repr__(self):
        return "Roll(time={!r}, end={!r}, number={!r}, speed={!r}, roll={!r}, finished={!r})".format(
                     self.time, self.end, self.number, self.speed, self.roll, self.finished)
Beat.Roll = Roll

class Spin(Beat):
    total_score = 10
    symbols = BEATS_SYMS[4]
    finished_sym = SPIN_FINISHED_SYM

    def __init__(self, time, end, capacity, speed=1.0, charge=0.0, finished=False):
        self.time = time
        self.end = end
        self.speed = speed
        self.capacity = capacity
        self.charge = charge
        self.finished = finished

    @property
    def lifespan(self):
        return (self.time - self.tolerances[2], self.end + self.tolerances[2])

    @property
    def score(self):
        return self.total_score if self.charge == self.capacity else 0

    def hit(self, time, strength):
        self.charge = min(self.charge + min(1.0, strength)*2.0, self.capacity)
        if self.charge == self.capacity:
            self.finished = True

    def finish(self):
        self.finished = True

    def sound(self, sr):
        sound = ra.pulse(sr=sr, freq=1000.0, decay_time=0.01, amplitude=0.5)
        step = (self.end - self.time)/self.capacity if self.capacity > 0.0 else 0.0
        spin_sounds = [(step*i, sound) for i in range(int(self.capacity))]
        duration = self.end - self.time

        gen = ra.pipe(ra.empty(sr, duration=duration),
                      ra.attach(spin_sounds, sr))
        return numpy.concatenate(list(gen))

    def draw(self, track, time, drop_speed):
        if self.charge < self.capacity:
            pos = 0.0
            pos += max(0.0, (self.time - time) * drop_speed * self.speed)
            pos += min(0.0, (self.end - time) * drop_speed * self.speed)
            track.draw(pos, self.symbols[int(self.charge) % 4])

    def draw_judging(self, track, time):
        return True

    def draw_hitting(self, track, time):
        track.draw(0.0, self.finished_sym)
        return True

    def __repr__(self):
        return "Spin(time={!r}, end={!r}, capacity={!r}, speed={!r}, charge={!r}, finished={!r})".format(
                     self.time, self.end, self.capacity, self.speed, self.charge, self.finished)
Beat.Spin = Spin

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

    @staticmethod
    def judge(time_diff, is_correct_key, tolerances):
        err = abs(time_diff)
        too_late = time_diff > 0

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

        return perf

    def draw(self, track, flipped, perf_syms):
        CORRECT_TYPES = (Performance.GREAT,
                         Performance.LATE_GOOD, Performance.EARLY_GOOD,
                         Performance.LATE_BAD, Performance.EARLY_BAD,
                         Performance.LATE_FAILED, Performance.EARLY_FAILED)

        if self in CORRECT_TYPES:
            track.draw(0.0, perf_syms[3], 1)

        LEFT_GOOD    = (Performance.LATE_GOOD,    Performance.LATE_GOOD_WRONG)
        RIGHT_GOOD   = (Performance.EARLY_GOOD,   Performance.EARLY_GOOD_WRONG)
        LEFT_BAD     = (Performance.LATE_BAD,     Performance.LATE_BAD_WRONG)
        RIGHT_BAD    = (Performance.EARLY_BAD,    Performance.EARLY_BAD_WRONG)
        LEFT_FAILED  = (Performance.LATE_FAILED,  Performance.LATE_FAILED_WRONG)
        RIGHT_FAILED = (Performance.EARLY_FAILED, Performance.EARLY_FAILED_WRONG)
        if flipped:
            LEFT_GOOD, RIGHT_GOOD = RIGHT_GOOD, LEFT_GOOD
            LEFT_BAD, RIGHT_BAD = RIGHT_BAD, LEFT_BAD
            LEFT_FAILED, RIGHT_FAILED = RIGHT_FAILED, LEFT_FAILED

        if self in LEFT_GOOD:
            track.draw(0.0, perf_syms[2], -1)
        elif self in RIGHT_GOOD:
            track.draw(0.0, perf_syms[4], +2)
        elif self in LEFT_BAD:
            track.draw(0.0, perf_syms[1], -1)
        elif self in RIGHT_BAD:
            track.draw(0.0, perf_syms[5], +2)
        elif self in LEFT_FAILED:
            track.draw(0.0, perf_syms[0], -1)
        elif self in RIGHT_FAILED:
            track.draw(0.0, perf_syms[6], +2)


class Hitter:
    hit_decay = HIT_DECAY
    hit_sustain = HIT_SUSTAIN
    target_syms = TARGET_SYMS

    def __init__(self, beats):
        self.beats = tuple(beats)

        self.hit_index = 0
        self.hit_time = -1.0
        self.hit_strength = 0.0
        self.hit_beat = None
        self.draw_index = 0
        self.current_beat = None

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
        return sum(1 for beat in self.beats if beat.finished) * 1000 // len(self.beats)

    @ra.DataNode.from_generator
    def get_beats_handler(self):
        beats = iter(self.beats)
        beat = next(beats, None)
        time = yield None
        while True:
            while beat is not None and (beat.finished or beat.lifespan[1] < time):
                if not beat.finished:
                    beat.finish()
                beat = next(beats, None)

            time = yield (beat if beat is not None and beat.lifespan[0] < time else None)

    @ra.DataNode.from_generator
    def get_knock_handler(self):
        beats_handler = self.get_beats_handler()

        while True:
            time, strength, detected = yield
            self.current_beat = beats_handler.send(time)

            if not detected:
                continue

            self.hit_index += 1
            self.hit_strength = strength
            self.hit_beat = self.current_beat
            
            if self.current_beat is None:
                continue

            self.current_beat.hit(time, strength)
            self.current_beat = beats_handler.send(time)

    def update_draw_index(self, time):
        if self.draw_index != self.hit_index:
            self.hit_time = time
            self.draw_index = self.hit_index

    def draw(self, track, time):
        strength = min(1.0, self.hit_strength)
        strength -= (time - self.hit_time) / self.hit_decay
        strength = max(0.0, min(1.0, strength))
        loudness = int(strength * (len(self.target_syms) - 1))
        if abs(time - self.hit_time) < self.hit_sustain:
            loudness = max(1, loudness)
        track.draw(0.0, self.target_syms[loudness])


class Track:
    def __init__(self, win, offset):
        self.win = win
        self.offset = offset

    def draw(self, pos, sym, shift=0):
        _, width = self.win.getmaxyx()
        index = round((self.offset + pos) * width) + shift

        if index in range(width-1):
            self.win.addstr(0, index, sym)


# beatmap
class Beatmap:
    def __init__(self, filename, duration, beats, drop_speed=DROP_SPEED,
                                                  spec_width=SPEC_WIDTH):
        self.drop_speed = drop_speed

        self.beats = tuple(beats)
        self.hitter = Hitter(self.beats)

        self.file = None
        self.filename = filename
        self.duration = duration

        self.spectrum = " "*spec_width

    def __enter__(self):
        if self.filename is not None:
            self.file = wave.open(self.filename, "rb")
        return self

    def __exit__(self, type, value, traceback):
        if self.file is not None:
            self.file.close()

    def get_knock_handler(self):
        return self.hitter.get_knock_handler()

    def get_spectrum_handler(self, sr, hop_length, win_length, decay_time):
        spec = ra.pipe(ra.frame(win_length, hop_length),
                       ra.power_spectrum(sr, win_length, windowing=True, weighting=False),
                       ra.draw_spectrum(len(self.spectrum), sr, win_length, decay=(hop_length/sr)/decay_time),
                       lambda s: setattr(self, "spectrum", s))
        return spec

    def get_sound_handler(self, sr, hop_length):
        # generate music
        if self.file is None:
            music = ra.empty(sr, hop_length, self.duration)
        else:
            music = ra.load(self.file, sr, hop_length)

        # add spec
        WIN_LENGTH = 512*4
        DECAY_TIME = 0.01
        music = ra.pipe(music, ra.branch(self.get_spectrum_handler(sr, hop_length, WIN_LENGTH, DECAY_TIME)))

        # add beats sounds
        beats_sounds = [(beat.time, beat.sound(sr)) for beat in self.beats]
        music = ra.pipe(music, ra.attach(beats_sounds, sr, hop_length))

        return music

    @ra.DataNode.from_generator
    def get_screen_handler(self, scr):
        _, width = scr.getmaxyx()

        "  ⣿⣴⣧⣰⣄ [  384/ 2240] □   □⛶  □   ■       ■   □   □   ■   ■   □   [ 21.8%] "
        spec_offset = 2
        score_offset = len(self.spectrum) + 3
        track_offset = len(self.spectrum) + 16
        progress_offset = width - 9
        track_width = width - 25 - len(self.spectrum)
        track_win = scr.subwin(1, track_width, 0, track_offset)

        bar_offset = 0.1
        track = Track(track_win, bar_offset)

        def range_of(beat):
            cross_time = 1.0 / abs(self.drop_speed * beat.speed)
            start, end = beat.lifespan
            return (start-cross_time, end+cross_time)
        dripper = ra.drip(self.beats, range_of)

        while True:
            time = yield
            self.hitter.update_draw_index(time)
            scr.clear()

            # draw beats
            ## find visible beats, and move finished beats to the bottom
            beats = dripper.send(time)
            beats = sorted(beats, key=lambda b: b.finished)
            for beat in beats[::-1]:
                beat.draw(track, time, self.drop_speed)

            # draw target
            stop_drawing = False
            if not stop_drawing and self.hitter.current_beat is not None:
                stop_drawing = self.hitter.current_beat.draw_judging(track, time)
            if not stop_drawing and self.hitter.hit_beat is not None:
                if abs(time - self.hitter.hit_time) < self.hitter.hit_sustain:
                    stop_drawing = self.hitter.hit_beat.draw_hitting(track, time)
            if not stop_drawing:
                self.hitter.draw(track, time)

            # draw others
            scr.addstr(0, spec_offset, self.spectrum)
            scr.addstr(0, score_offset, "[{:>5d}/{:>5d}]".format(self.hitter.score, self.hitter.total_score))
            scr.addstr(0, progress_offset, "[{:>5.1f}%]".format(self.hitter.progress/10))

            scr.refresh()


def from_pattern(t0, dt, pattern):
    incring = None
    for j, c in enumerate(pattern):
        if incring is not None and c != ",":
            incring = None
        elif incring is None and c == ",":
            incring = IncrLevel()

        if c == ".":
            yield Beat.Soft(t0 + j/2*dt)
        elif c == "-":
            yield Beat.Loud(t0 + j/2*dt)
        elif c == "=":
            yield Beat.Loud(t0 + j/2*dt)
        elif c == ":":
            # yield Beat.Soft(t0 + j/2*dt)
            # yield Beat.Soft(t0 + (j+1/2)/2*dt)
            yield Beat.Roll(t0 + j/2*dt, t0 + (j+1)/2*dt, 2, endpoint=False)
        elif c == ",":
            yield incring.add(t0 + j/2*dt)
