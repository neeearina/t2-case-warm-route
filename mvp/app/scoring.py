from datetime import datetime

WEIGHTS = {'hazard': .35, 'mobility': .25, 'criticality': .20, 'duration': .10, 'confidence': .10}
HAZARD = {'ice': .9, 'snow': .6, 'delay': .4}


def calculate(category: str, criticality: float, started_at: datetime,
              now: datetime, signal_count: int, context: dict) -> tuple[float, dict]:
    factors = {
        'hazard': max(HAZARD[category], context.get('weather', .5)),
        'mobility': context.get('mobility', .5),
        'criticality': max(criticality, context.get('transport', .5)),
        'duration': min(1, max(0, (now - started_at).total_seconds()) / 86400),
        'confidence': min(1, .5 + .25 * (signal_count - 1)),
    }
    contributions = {key: round(100 * factors[key] * weight, 4) for key, weight in WEIGHTS.items()}
    return round(sum(contributions.values()), 2), {
        'formula_version': 'weighted-v1', 'factors': factors,
        'weights': WEIGHTS, 'contributions': contributions,
        'missing_or_stale': sorted(set(('weather', 'mobility', 'transport')) - context.keys()),
        'evaluated_at': now.isoformat(),
    }
