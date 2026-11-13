from datetime import datetime, timezone
from app.contracts import Context, Report, TransportSample
from app.demo import SEGMENTS


def fetch_weather(client, provider, mock_url, now):
    if provider == 'mock':
        response = client.get(f'{mock_url}/weather')
        response.raise_for_status()
        return [Context.model_validate(row) for row in response.json()]
    response = client.get('https://api.open-meteo.com/v1/forecast', params={
        'latitude':57.15, 'longitude':65.54, 'hourly':'temperature_2m,precipitation,snowfall',
        'forecast_days':1, 'timezone':'UTC',
    })
    response.raise_for_status()
    data = response.json()
    units = data['hourly_units']
    if units['temperature_2m'] != '°C' or units['precipitation'] != 'mm' or units['snowfall'] != 'cm':
        raise ValueError('Unexpected weather units')
    h = data['hourly']
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h['time']]
    index = max(i for i,t in enumerate(times) if t <= now)
    temperature, rain, snow = (h[key][index] for key in ('temperature_2m','precipitation','snowfall'))
    if any(value is None for value in (temperature,rain,snow)):
        raise ValueError('Weather sample is incomplete')
    risk = .9 if snow > 0 or (rain > 0 and temperature <= 1) else .5 if temperature <= 0 else .2
    return [Context(segment_id=i,observed_at=times[index],value=risk,synthetic=False) for i in (s.id for s in SEGMENTS)]


def fetch_feed(client, mock_url, source):
    """Small immutable feeds share transport; their DTOs remain distinct."""
    model = {'reports': Report, 'mobility': Context, 'transport': TransportSample}[source]
    response = client.get(f'{mock_url}/{source}')
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError('Expected a feed of at most 100 records')
    return [model.model_validate(row) for row in data]
