from datetime import datetime, timezone
from fastapi import FastAPI
from app.demo import SEGMENTS

app = FastAPI(title='Synthetic sources for local MVP')


def hour():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)


@app.get('/weather')
def weather():
    observed_at = hour()
    return [dict(segment_id=s.id, observed_at=observed_at, value=s.weather, synthetic=True) for s in SEGMENTS]


@app.get('/mobility')
def mobility():
    observed_at = hour()
    return [dict(segment_id=s.id, observed_at=observed_at, value=s.mobility, synthetic=True) for s in SEGMENTS]


@app.get('/transport')
def transport():
    observed_at = hour()
    return [dict(external_id=f'transport-{s.id}-{observed_at.isoformat()}', segment_id=s.id,
                 observed_at=observed_at, delay_minutes=s.delay_minutes) for s in SEGMENTS]


@app.get('/reports')
def reports():
    day = hour().replace(hour=0)
    # Stable per day, including the original report ID for existing databases.
    scenarios = (
        (1, 'ice', 'Демонстрация: скользкий переход'),
        (2, 'snow', 'На остановке сугроб перекрывает подход к автобусу.'),
        (4, 'ice', 'Автобусы буксуют на обледеневшем подъёме.'),
        (4, 'ice', 'Пешеходы обходят скользкий подъём по проезжей части.'),
        (5, 'snow', 'Снежный вал мешает пройти к пешеходному переходу.'),
        (5, 'snow', 'У подхода к школе не расчищена пешеходная дорожка.'),
        (6, 'snow', 'На остановке у сквера скопился рыхлый снег.'),
        (7, 'ice', 'У края перехода образовалась наледь.'),
        (8, 'snow', 'На тихой улице требуется расчистить узкий проход.'),
    )
    by_id = {s.id: s for s in SEGMENTS}
    return [dict(external_id=f'demo-report-{day.date()}' if index == 0 else f'demo-report-{index}-{day.date()}',
                 occurred_at=day, latitude=by_id[segment_id].latitude, longitude=by_id[segment_id].longitude,
                 category=category, text=text, synthetic=True)
            for index, (segment_id, category, text) in enumerate(scenarios)]
