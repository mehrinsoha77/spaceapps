"""Reference thresholds shown in SHELTER. Each one names its source.

These are *reference lines* on charts and gauges. SHELTER's planner uses its own
team-configurable flight-rule thresholds (see planner.policy), because NASA's
operational flight rules are not published in a form we can reproduce.
"""

REFERENCE_LIMITS = [
    {
        "key": "career_effective",
        "label": "Career effective dose limit",
        "value_msv": 600.0,
        "applies_to": "effective dose (career, all missions)",
        "source": "NASA-STD-3001 Vol. 1 Rev C, [V1 4030]",
    },
    {
        "key": "spe_design",
        "label": "Vehicle SPE protection design threshold",
        "value_msv": 250.0,
        "applies_to": "effective dose for a design-reference SPE (Oct 1989 class) "
                      "inside the protected area -- a vehicle design requirement, not a crew dose limit",
        "source": "NASA-STD-3001 (Vol. 2), radiation protection technical brief, NASA OCHMO",
    },
    {
        "key": "bfo_30day",
        "label": "30-day BFO short-term limit",
        "value_msv": 250.0,
        "applies_to": "blood-forming organ dose (equivalent), any 30 days",
        "source": "ISS partners' multilateral consensus limits, as summarised in "
                  "PMC10919966 (J. Radiol. Prot./ICRP context, 2023)",
    },
    {
        "key": "eye_30day",
        "label": "30-day eye lens limit",
        "value_msv": 1000.0,
        "applies_to": "lens of the eye, any 30 days",
        "source": "NCRP-132 short-term limits (as tabulated by NASA)",
    },
    {
        "key": "skin_30day",
        "label": "30-day skin limit",
        "value_msv": 1500.0,
        "applies_to": "skin, any 30 days",
        "source": "NCRP-132 short-term limits (as tabulated by NASA)",
    },
]

# GCR background inside a lightly shielded spacecraft in deep space, measured.
GCR_CRUISE_MSV_PER_DAY = 1.75
GCR_SOURCE = ("MSL/RAD cruise measurement 1.75 +/- 0.30 mSv/day "
              "(Guo et al. 2015, A&A 577 A58; Zeitlin et al. 2013, Science 340:1080). "
              "Applied as a constant: moderate shielding barely changes GCR dose.")

# NOAA Space Weather Scale for solar radiation storms (>=10 MeV integral flux, pfu)
NOAA_S_SCALE = [(10.0, "S1"), (100.0, "S2"), (1e3, "S3"), (1e4, "S4"), (1e5, "S5")]


def s_level(flux_10mev):
    """NOAA S-scale label for a >=10 MeV flux in pfu ('S0' below S1)."""
    level = "S0"
    for threshold, name in NOAA_S_SCALE:
        if flux_10mev is not None and flux_10mev >= threshold:
            level = name
    return level
