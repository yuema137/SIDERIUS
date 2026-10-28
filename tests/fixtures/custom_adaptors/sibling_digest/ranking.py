"""Helper member: a stable ranking key (ties keep declared order)."""


def by_confidence(finding):
    return -(finding.confidence or 0.0)
