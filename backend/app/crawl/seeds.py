from __future__ import annotations

# Deterministic portal / employer overview seeds (ICT-leaning where possible).
DEFAULT_SEED_URLS: tuple[str, ...] = (
    "https://www.werkenvoornederland.nl/vacatures?vakgebied=CVG.08",
    "https://www.werkenbijdeoverheid.nl/vacatures?searchterm=ICT",
    "https://www.werkenbijanwb.nl/vacatures",
    "https://www.werkenbijns.nl/vacatures?keywords=Inhuur",
    "https://werkenbij.amsterdam.nl/vacatures",
    "https://www.werkenbijachmea.nl/vacatures",
    "https://werkenbij.enexis.nl/vacatures",
    "https://www.werkenbijradboudumc.nl/vacatures",
    "https://werkenbij.portofrotterdam.com/vacatures",
)

# NL search queries expanded via DuckDuckGo HTML.
# Aimed at employer career pages (werkenbij / careers) for ICT + external staffing,
# not broker boards (Indeed / LinkedIn / uitzend).
DEFAULT_SEARCH_QUERIES: tuple[str, ...] = (
    # Employer career hubs + staffing language
    "werkenbij vacatures inhuur ICT",
    "werkenbij vacatures detachering ICT",
    "\"werken bij\" vacatures ICT inhuur",
    "\"werken bij\" vacatures interim ICT",
    "careers vacatures ICT inhuur Nederland",
    # Role-shaped ICT that often lands on employer sites
    "vacature software engineer inhuur Nederland",
    "vacature devops engineer inhuur",
    "vacature cloud engineer detachering Nederland",
    "vacature data engineer inhuur",
    "vacature solution architect inhuur ICT",
    "vacature java developer inhuur Nederland",
    "vacature .NET developer detachering",
    # Public / inlener-style phrasing
    "vacature externe inhuur ICT overheid",
    "vacature inlener ICT",
    "vacatures ICT zzp opdrachtgever -freelancer.nl -freelance.nl",
    # Steer off major boards (DDG minus-operator)
    "vacature ICT inhuur Nederland -indeed -linkedin -monsterboard -nationalevacaturebank -jobbird",
    "vacature detachering ICT \"werken bij\" -yacht -randstad -tempo-team -hays",
)

DDG_HTML_SEARCH = "https://html.duckduckgo.com/html/"
