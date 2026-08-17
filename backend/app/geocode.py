"""Best-effort geocoding of the live feed's free-text `location` field.

The source API provides NO coordinates. We derive an APPROXIMATE point and a
district by keyword-matching the location string against known Gujarat places.
Every coordinate produced here is flagged `coords_approx=True` so it is never
mistaken for a surveyed camera position.
"""

# keyword (lowercased substring) -> (district, base_lat, base_lng)
# Order matters: more specific keywords first.
PLACES = [
    ("somnath", ("Gir Somnath", 20.9010, 70.3620)),
    ("gir-somnath", ("Gir Somnath", 20.9010, 70.3620)),
    ("junagadh", ("Junagadh", 21.5222, 70.4579)),
    ("dolatpara", ("Junagadh", 21.5100, 70.4700)),
    ("majewadi", ("Junagadh", 21.5300, 70.4600)),
    ("timbavadi", ("Junagadh", 21.5150, 70.4800)),
    ("rajkot", ("Rajkot", 22.3039, 70.8022)),
    ("bilimora", ("Navsari", 20.7690, 72.9600)),
    ("gandevi", ("Navsari", 20.8100, 72.9200)),
    ("navsari", ("Navsari", 20.9467, 72.9520)),
    ("khaparia", ("Navsari", 20.8000, 72.9000)),
    ("patan", ("Patan", 23.8493, 72.1266)),
    ("dethali", ("Patan", 23.8600, 72.1400)),
    ("dehgam", ("Gandhinagar", 23.1700, 72.8200)),
    ("adalaj", ("Gandhinagar", 23.1650, 72.5800)),
    ("gandhidham", ("Kutch", 23.0800, 70.1330)),
    ("rambaugh", ("Kutch", 23.0850, 70.1400)),
    ("chiman bhai", ("Ahmedabad", 23.0300, 72.5100)),
    ("chimanbhai", ("Ahmedabad", 23.0300, 72.5100)),
    ("paldi", ("Ahmedabad", 23.0100, 72.5700)),
    ("visat", ("Ahmedabad", 23.1050, 72.5850)),
    ("janpath", ("Ahmedabad", 23.0350, 72.5650)),
    ("o.n.g.c", ("Ahmedabad", 23.0400, 72.5000)),
    ("ongc", ("Ahmedabad", 23.0400, 72.5000)),
    ("cn vidhyalaya", ("Ahmedabad", 23.0330, 72.5500)),
    ("mervada", ("Mehsana", 23.5880, 72.3690)),
    ("kheram", ("Kheda", 22.7500, 72.6800)),
    ("dhanori", ("Sabarkantha", 23.8300, 72.9800)),
    ("tankal", ("Sabarkantha", 23.7500, 72.9500)),
    ("mohanpura", ("Vadodara", 22.3072, 73.1812)),
    ("kheda", ("Kheda", 22.7500, 72.6800)),
]

GUJARAT_CENTROID = ("Gujarat (unmapped)", 22.6000, 71.6000)


def geocode(location: str, number: int):
    """Return (district, lat, lng). Coords are approximate (city-level +
    a small deterministic spread so co-located cameras don't stack)."""
    loc = (location or "").lower()
    match = None
    for kw, place in PLACES:
        if kw in loc:
            match = place
            break
    district, base_lat, base_lng = match or GUJARAT_CENTROID
    # deterministic small offset (~1-1.5 km) to separate overlapping pins
    off = ((number * 7) % 11 - 5) / 1000.0
    off2 = ((number * 13) % 11 - 5) / 1000.0
    return district, round(base_lat + off, 6), round(base_lng + off2, 6)
