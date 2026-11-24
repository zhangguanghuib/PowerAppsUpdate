from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    slug: str
    name: str
    excluded_topics: re.Pattern[str] | None = None
    exclusion_note: str = ""

    @property
    def roots(self) -> tuple[str, str]:
        return (
            f"https://learn.microsoft.com/en-us/{self.slug}/",
            f"https://learn.microsoft.com/en-us/troubleshoot/power-platform/{self.slug}/",
        )


POWER_APPS = Product(
    slug="power-apps",
    name="Power Apps",
    excluded_topics=re.compile(
        r"model[-\s]+driven|dataverse|data[-\s]+platform|common[-\s]+data[-\s]+service",
        re.IGNORECASE,
    ),
    exclusion_note=", excluding model-driven apps and Dataverse topics",
)
POWER_AUTOMATE = Product(slug="power-automate", name="Power Automate")
PRODUCTS = {product.slug: product for product in (POWER_APPS, POWER_AUTOMATE)}
