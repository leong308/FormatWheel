"""Original synthesized HUD sounds; no downloaded or copyrighted game audio."""
from __future__ import annotations

import math
import os
import random
import struct
import sys
import wave
from pathlib import Path


class Sounds:
    kinds = ("open", "tick", "page", "passed", "wasted", "denied", "wanted", "evaded", "rackPistol",
             "rackRifle", "rackBolt", "rackPump", "rackHeavy", "pinPull", "bladeDraw", "meleeSwing")
    def __init__(self, settings):
        self.settings = settings
        self._cache = {}

    @staticmethod
    def render(kind):
        rate = 22050
        duration = {"open": .32, "tick": .035, "page": .14, "denied": .17,
                    "passed": 1.0, "wasted": 2.2, "wanted": .5, "evaded": .75,
                    "rackPistol": .45, "rackRifle": .55, "rackBolt": .75, "rackPump": .6,
                    "rackHeavy": .95, "pinPull": .7, "bladeDraw": .75, "meleeSwing": .5}.get(kind, .1)
        rng = random.Random(616)
        output = bytearray()
        low = 0.
        for index in range(int(rate * duration)):
            t = index / rate
            noise = rng.uniform(-1, 1)
            low += .08 * (noise - low)
            if kind == "passed":
                voice = sum(math.sin(2 * math.pi * f * (t - start)) * math.exp(-(t - start) * 3.2) * .28
                            for start, f in ((0, 659.25), (.12, 987.77), (.12, 1318.5)) if t >= start)
            elif kind == "wasted":
                voice = (math.sin(2 * math.pi * (62 - 16 * t) * t) * .52 + low * 2) * math.exp(-t * 1.9)
            elif kind == "open":
                voice = (low * 2 + math.sin(2 * math.pi * (310 - 210 * t) * t) * .15) * math.sin(math.pi * t / duration)
            elif kind in ("wanted", "evaded"):
                freq = (1180 if int(t / .125) % 2 == 0 else 860) if kind == "wanted" else (988 - int(t / .1) * 110)
                voice = math.sin(2 * math.pi * freq * t) * math.exp(-t * 3.5) * .3
            elif kind.startswith("rack"):
                interval, tone = {"rackPistol": (.12, 130), "rackRifle": (.2, 95), "rackBolt": (.2, 110),
                                  "rackPump": (.24, 80), "rackHeavy": (.36, 65)}[kind]
                u = t % interval
                voice = (noise * .4 + math.sin(2 * math.pi * tone * u) * .4) * math.exp(-u * 48) * math.exp(-t * 2)
                if kind == "rackHeavy":
                    voice += math.sin(2*math.pi*(180+340*min(t/.6,1))*t) * (.6+.4*math.sin(2*math.pi*38*t)) * min(1,t/.1)*math.exp(-max(0,t-.55)*12)*.16
            elif kind == "pinPull":
                voice = sum(math.sin(2*math.pi*f*(t-start))*math.exp(-(t-start)*decay)*gain
                            for start, f, decay, gain in ((0,3400,9,.35),(.22,5200,18,.2)) if t >= start)
            elif kind == "bladeDraw":
                voice = noise * math.sin(math.pi*min(1,t/.28))*.28 if t < .28 else math.sin(2*math.pi*4100*(t-.22))*math.exp(-(t-.22)*6)*.3
            elif kind == "meleeSwing":
                voice = low * math.sin(math.pi*min(1,t/.22))*2 if t < .22 else math.sin(2*math.pi*110*(t-.22))*math.exp(-(t-.22)*26)*.6
            else:
                freq = {"tick": 1600, "page": 720, "denied": 170}.get(kind, 800)
                voice = (math.sin(2 * math.pi * freq * t) * .4 + noise * .08) * math.exp(-t * (80 if kind == "tick" else 20))
            output.extend(struct.pack("<h", round(max(-1., min(1., voice)) * 24000)))
        return bytes(output)

    def play(self, kind):
        if not self.settings.get("sound") or sys.platform != "win32":
            return
        try:
            import winsound
            path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FormatWheel" / "Sounds" / f"{kind}-v1.wav"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                self._write(path, kind)
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except (RuntimeError, OSError, ImportError):
            pass

    def _write(self, path, kind):
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes(self._cache.setdefault(kind, self.render(kind)))

    def export(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        for kind in self.kinds:
            self._write(folder / f"{kind}.wav", kind)
