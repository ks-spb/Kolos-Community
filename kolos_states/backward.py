"""Same alternative-input competition as web/states/backward.mjs.

Only weighted activity and decay enter this operation. No world/task labels,
route extraction or per-test thresholds. Zero competition restores old mean.
"""
from .protocol import clamp


def backward_wave(memory, nodes, old, cfg, flows):
    new = {}
    for n in nodes:
        incoming = [e for e in memory['edges'] if e['kind'] == 'backward' and e['to'] == n['id']]
        attenuation = cfg['discount'] if n['kind'] == 'transition' else 1
        signals = [old.get(e['from'], 0) * e['weight'] * attenuation for e in incoming]
        count = max(1, len(incoming))
        peak = max([0, *signals])
        mean = sum(signals) / count
        competition = cfg.get('stateCompetition', 1) if n['kind'] == 'state' else 0
        winners = sum(v == peak and v > 0 for v in signals)
        drive = min(1, (1 - competition) * mean + competition * peak)
        new[n['id']] = clamp(cfg['decay'] * old.get(n['id'], 0) + (1 - cfg['decay']) * drive)
        for i, edge in enumerate(incoming):
            if not old.get(edge['from']):
                continue
            share = (1 - competition) / count + (competition / winners if competition and signals[i] == peak and winners else 0)
            flows.append(dict(**{'from': edge['from']}, to=edge['to'], edge=edge['id'], value=signals[i],
                              term=signals[i] * share * (1 - cfg['decay']),
                              aggregation='competitive-alternatives' if competition else 'mean',
                              stateCompetition=competition, share=share))
    return new
