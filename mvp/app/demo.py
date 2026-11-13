"""Shared illustrative geography and context. No authoritative city measurements."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoSegment:
    id: int
    name: str
    kind: str
    latitude: float
    longitude: float
    criticality: float
    mobility: float
    weather: float
    delay_minutes: float


SEGMENTS = (
    DemoSegment(1, 'Демонстрационный участок: центр', 'crossing', 57.1530, 65.5340, .9, .9, .8, 18),
    DemoSegment(2, 'Демонстрационная остановка', 'stop', 57.1450, 65.5500, .6, .6, .6, 8),
    DemoSegment(3, 'Демонстрационный участок улицы', 'road', 57.1600, 65.5650, .3, .2, .3, 2),
    DemoSegment(4, 'Демо: подъём у транспортного узла', 'road', 57.1650, 65.5400, 1, .95, .9, 26),
    DemoSegment(5, 'Демо: подход к школе', 'crossing', 57.1500, 65.5750, .7, .55, .7, 4),
    DemoSegment(6, 'Демо: остановка у сквера', 'stop', 57.1380, 65.5600, .4, .35, .4, 5),
    DemoSegment(7, 'Демо: переход в жилом квартале', 'crossing', 57.1550, 65.5150, .25, .15, .4, 1),
    DemoSegment(8, 'Демо: тихая улица', 'road', 57.1420, 65.5250, .1, .05, .2, 0),
)
