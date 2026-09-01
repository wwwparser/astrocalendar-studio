"""Равноденствия и солнцестояния."""
from __future__ import annotations

import datetime as dt

from skyfield import almanac

from ..core import Event, planets, timescale, to_msk

NAMES = {0: "Весеннее равноденствие", 1: "Летнее солнцестояние",
         2: "Осеннее равноденствие", 3: "Зимнее солнцестояние"}


def all_events(start: dt.datetime, end: dt.datetime) -> list[Event]:
    ts = timescale()
    times, which = almanac.find_discrete(ts.from_datetime(start), ts.from_datetime(end),
                                         almanac.seasons(planets()))
    return [Event(
        when=to_msk(t),
        text=NAMES[int(w)],
        category="season",
        computed=("видимая геоцентрическая эклиптическая долгота Солнца проходит "
                  f"через узловую точку; {t.utc_strftime('%Y-%m-%d %H:%M:%S UTC')}"),
        sources=["Skyfield/DE440s"],
        precision="minute",
    ) for t, w in zip(times, which)]
