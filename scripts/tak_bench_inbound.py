#!/usr/bin/env python3
"""Mät vad en inkommande CoT kostar, med och utan förfiltret.

En TAK-server trycker ut hela lägesbilden, så på ett livligt nät är nästan varje
händelse en positionsrapport som typ-vitlistan kastar. Den här bänken visar vad
det kostar att kasta den: att parsa XML:en först och titta på typen efteråt,
mot att läsa typen ur råbytena direkt.

Inget nätverk, inga inställningar, ingen databas — bara fixturerna i
tests/fixtures/tak. Kör:

    .venv/bin/python scripts/tak_bench_inbound.py
    .venv/bin/python scripts/tak_bench_inbound.py --number 50000

Referenssiffror (Python 3.14, Apple Silicon, friendly_pli.xml, 693 B):
parsa+typkoll 14,2 µs mot förfilter 0,90 µs, alltså ungefär sexton gånger
billigare. Vid 1000 CoT/min är det 0,024 % av en kärna mot 0,0015 %.
"""

from __future__ import annotations

import argparse
import sys
import timeit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oden.tak.cot import cot_to_inbound, cot_type_matches  # noqa: E402
from oden.tak.listener import _INBOUND_DEFAULTS, InboundFilter  # noqa: E402

_FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "tak"


def _verdicts(filt: InboundFilter, data: bytes) -> tuple[bool, bool]:
    """(släpps igenom av förfiltret, släpps igenom av hela filtret)."""
    cot = cot_to_inbound(data)
    full = cot is not None and filt.accept(cot)
    return not filt.prescreen_rejects(data), full


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--number", type=int, default=20000, help="antal varv per mätning")
    parser.add_argument("--rate", type=float, default=1000.0, help="CoT per minut att räkna om till CPU-andel")
    args = parser.parse_args()

    files = sorted(_FIX.glob("*.xml"))
    if not files:
        print(f"Hittade inga fixturer i {_FIX}", file=sys.stderr)
        return 1

    per_second = args.rate / 60.0
    print(f"{args.number} varv per mätning, CPU-andel räknad vid {args.rate:.0f} CoT/min\n")
    print(
        f"{'fixtur':18s}{'byte':>6s}{'parsa+typkoll':>16s}{'förfilter':>11s}{'faktor':>8s}{'% av kärna':>12s}  utfall"
    )

    # One filter for the whole run, as the listener has: it is built once per
    # bridge start, so building it inside the timed call would inflate the "old"
    # side. Only the discard decision is timed — accept()'s later stages mutate
    # state, and the flood never reaches them anyway.
    filt = InboundFilter(dict(_INBOUND_DEFAULTS))
    types = filt.types

    for path in files:
        data = path.read_bytes()

        def parse_then_filter(data=data, types=types):
            """What every event used to cost before the type was even looked at."""
            cot = cot_to_inbound(data)
            return cot is not None and cot_type_matches(cot.cot_type, types)

        def prescreen(data=data, filt=filt):
            return filt.prescreen_rejects(data)

        # Förfiltret får aldrig kasta något som hela filtret hade släppt igenom.
        maybe, full = _verdicts(InboundFilter(dict(_INBOUND_DEFAULTS)), data)
        assert maybe or not full, f"{path.name}: förfiltret kastade en CoT som filtret accepterar"

        slow = timeit.timeit(parse_then_filter, number=args.number) / args.number
        fast = timeit.timeit(prescreen, number=args.number) / args.number
        verdict = "parsas" if maybe else "kastas"
        print(
            f"{path.stem:18s}{len(data):6d}{slow * 1e6:14.2f} µs{fast * 1e6:9.2f} µs"
            f"{slow / fast:7.1f}x{(slow if maybe else fast) * per_second * 100:11.4f} %  {verdict}"
        )

    print("\nSista kolumnen är kostnaden efter ändringen: förfiltret för det som kastas,")
    print("hela vägen för det som är värt att titta på.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
