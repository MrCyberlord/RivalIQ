"""Conservative, explicit-text rules. These are estimates, not verified specifications."""
import re
from decimal import Decimal

from app.intelligence_schemas import Comparability, ProductAttributes

CATEGORIES = {
    "bottle": r"\b(?:bottles?|bidon)\b",
    "flask": r"\b(?:flasks?|thermos)\b",
    "mug": r"\b(?:mugs?|tumblers?)\b",
    "container": r"\bcontainers?\b",
    "headphones": r"\bheadphones?\b",
    "earbuds": r"\b(?:earbuds?|earphones?)\b",
    "backpack": r"\bbackpacks?\b",
    "phone": r"\b(?:smartphones?|mobile phones?)\b",
}
MATERIALS = {
    "stainless steel": r"\b(?:stainless[ -]steel|inox)\b",
    "plastic": r"\b(?:plastic|tritan|polypropylene|pet)\b",
    "glass": r"\b(?:glass|borosilicate)\b",
    "copper": r"\bcopper\b", "aluminium": r"\balumin(?:ium|um)\b",
    "ceramic": r"\bceramic\b",
}
BRANDS = ("milton", "cello", "borosil", "pigeon", "hydro flask", "stanley", "nike", "adidas", "apple", "samsung")


def extract_attributes(name: str | None, features: list[str] | None = None,
                       hints: ProductAttributes | None = None) -> ProductAttributes:
    # Do not treat the merchant as a brand or a discovery query as a specification.
    text = " \n".join([name or "", *(features or [])]).casefold()
    result = ProductAttributes()

    def single(field, values):
        unique = set(values)
        if len(unique) == 1:
            setattr(result, field, unique.pop())
        elif len(unique) > 1:
            result.conflicts.append(field)

    single("category", [key for key, pattern in CATEGORIES.items() if re.search(pattern, text)])
    materials = []
    for key, pattern in MATERIALS.items():
        for match in re.finditer(pattern, text):
            prefix, suffix = text[max(0, match.start() - 20):match.start()], text[match.end():match.end() + 12]
            if re.search(r"(?:not(?: made of)?|without|non|no)[ -]+$", prefix) or re.match(r"[ -]?free\b", suffix):
                continue
            materials.append(key)
    single("material", materials)
    capacities = []
    for number, unit in re.findall(r"(?<![\w.])([0-9]+(?:\.[0-9]+)?)\s*(ml|millilit(?:re|er)s?|l|ltrs?|lit(?:re|er)s?)\b", text):
        capacity = Decimal(number) * (1 if unit.startswith("m") else 1000)
        if 0 < capacity <= 10000000:
            capacities.append(capacity)
    single("capacity_ml", capacities)
    brands = [brand for brand in BRANDS if re.search(r"\b" + re.escape(brand) + r"\b", text)]
    if hints and hints.brand and re.search(r"(?<!\w)" + re.escape(hints.brand.casefold()) + r"(?!\w)", text):
        brands.append(hints.brand.casefold())
    brands += re.findall(r"\bbrand\s*:\s*([\w-]+)", text)
    single("brand", brands)
    models = re.findall(r"\bmodel\s*:\s*([\w-]+)", text)
    if hints and hints.model and re.search(r"(?<!\w)" + re.escape(hints.model.casefold()) + r"(?!\w)", text):
        models.append(hints.model.casefold())
    single("model", models)
    quantities = re.findall(r"\b(?:pack of|set of)\s*(\d+)\b|\b(\d+)\s*(?:pack|pcs|pieces)\b|\b(\d+)\s*[x×]\s*\d", text)
    if any(int(value) > 1 for match in quantities for value in match if value):
        result.conflicts.append("multipack")
    if re.search(r"\d\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*(?:ml|l|litres?|liters?)\b", text):
        result.conflicts.append("capacity_range")
    if re.search(r"\b(?:replacement|spare)\s+(?:lid|cap)\b|\bbottles?\s+(?:lid|caps?)\b", text):
        result.conflicts.append("accessory")
    return result


def seller_attributes(name: str, explicit: ProductAttributes | None) -> ProductAttributes:
    result = extract_attributes(name, hints=explicit)
    if explicit:
        for field in ("category", "capacity_ml", "material", "brand", "model"):
            value = getattr(explicit, field)
            if value is not None:
                value = value.casefold() if isinstance(value, str) else value
                current = getattr(result, field)
                if current is not None and current != value:
                    result.conflicts.append(field)
                else:
                    setattr(result, field, value)
    return result


def assess(seller: ProductAttributes, other: ProductAttributes) -> Comparability:
    def decision(category, eligible, reason):
        return Comparability(category=category, eligible=eligible, reason=reason)
    if seller.conflicts or other.conflicts:
        return decision("uncertain", False, "Conflicting attributes or explicit multipack; excluded from primary pricing.")
    same_brand = bool(seller.brand and other.brand and seller.brand == other.brand)
    same_model = bool(same_brand and seller.model and seller.model == other.model)
    compared_fields = ["category", "capacity_ml", "material"] + (["model"] if same_brand else [])
    mismatches = [field for field in compared_fields
                  if getattr(seller, field) is not None and getattr(other, field) is not None
                  and getattr(seller, field) != getattr(other, field)]
    same_category = bool(seller.category and other.category and seller.category == other.category)
    if mismatches:
        category = "variant" if same_brand and same_category else "alternative" if same_category or {seller.category, other.category} <= {"bottle", "flask", "mug", "container"} else "uncertain"
        return decision(category, False, "Different stated " + ", ".join(mismatches) + "; excluded from primary pricing.")
    if same_model and same_category:
        return decision("identical", True, "Explicit brand/model and category match with no stated conflicts; identity unverified.")
    if all(getattr(seller, field) is not None and getattr(seller, field) == getattr(other, field)
           for field in ("category", "capacity_ml", "material")):
        return decision("variant" if same_brand else "comparable_alternative", True,
                        "Explicit category, capacity and material match; identity and quality unverified.")
    return decision("uncertain", False, "Insufficient explicit matching category, capacity and material (or brand/model) for primary pricing.")
