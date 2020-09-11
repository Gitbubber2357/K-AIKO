from knock import *
from beatmap import *

# test
# beatmap = Beatmap(None, 9.0, [Beat.Loud(1.0 + t*0.5) for t in range(16)])
# level = IncrLevel()
# beatmap = Beatmap(None, 13.0, [Beat.Soft(1.0), Beat.Loud(1.5, -0.5), Beat.Soft(2.0), Beat.Soft(2.25), Beat.Loud(2.5, 0.5),
#                                Beat.Soft(3.0), Beat.Loud(3.5, -0.5), Beat.Soft(4.0), Beat.Soft(4.25),
#                                Beat.Roll(4.5, 4.875, 4, 1.5),
#                                Beat.Soft(5.0), Beat.Loud(5.5, -0.5), Beat.Soft(6.0), Beat.Soft(6.25), Beat.Loud(6.5, 0.5),
#                                level.add(7.0, 0.5), level.add(7.25, 0.7), level.add(7.5, 0.9),
#                                level.add(7.75, 1.1), level.add(8.0, 1.3), level.add(8.25, 1.5),
#                                Beat.Spin(8.5, 12.5, 30.0, 1.7)])

exec(open("蛋餅好朋友.ka").read())
beatmap = Beatmap(filename, duration, from_pattern(offset, 60.0/bpm, beats))

console = KnockConsole()
console.play(beatmap)
print()
for beat in beatmap.beats:
    print(beat)
