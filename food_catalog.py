"""
Curated food catalog for 12Weeks fitness app.
~60 foods across 5 categories with USDA-accurate macros and dietary tags.
"""

FOOD_CATALOG = {
    "proteins": [
        {
            "id": "chicken_breast",
            "name": "Chicken Breast",
            "unit": "oz",
            "default_portion": 6,
            "max_portion": 8,
            "cal": 46,
            "protein": 8.8,
            "carbs": 0,
            "fat": 1.0,
            "tags": ["gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "ground_turkey_93",
            "name": "Ground Turkey 93%",
            "unit": "oz",
            "default_portion": 5,
            "max_portion": 8,
            "cal": 50,
            "protein": 7.5,
            "carbs": 0,
            "fat": 2.1,
            "tags": ["gluten_free", "dairy_free", "halal"],
        },
        {
            "id": "ground_beef_90",
            "name": "Ground Beef 90/10",
            "unit": "oz",
            "default_portion": 5,
            "max_portion": 8,
            "cal": 51,
            "protein": 7.6,
            "carbs": 0,
            "fat": 2.1,
            "tags": ["gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "salmon",
            "name": "Salmon (Atlantic)",
            "unit": "oz",
            "default_portion": 5,
            "max_portion": 8,
            "cal": 58,
            "protein": 7.9,
            "carbs": 0,
            "fat": 2.6,
            "tags": ["pescatarian", "gluten_free", "dairy_free", "kosher"],
        },
        {
            "id": "tilapia",
            "name": "Tilapia",
            "unit": "oz",
            "default_portion": 5,
            "cal": 36,
            "protein": 7.5,
            "carbs": 0,
            "fat": 0.6,
            "tags": ["pescatarian", "gluten_free", "dairy_free", "kosher"],
        },
        {
            "id": "shrimp",
            "name": "Shrimp",
            "unit": "oz",
            "default_portion": 5,
            "cal": 30,
            "protein": 7.0,
            "carbs": 0.3,
            "fat": 0.3,
            "tags": ["pescatarian", "gluten_free", "dairy_free"],
        },
        {
            "id": "tuna_canned",
            "name": "Tuna (Canned in Water)",
            "unit": "oz",
            "default_portion": 4,
            "cal": 33,
            "protein": 7.7,
            "carbs": 0,
            "fat": 0.2,
            "tags": ["pescatarian", "gluten_free", "dairy_free", "kosher"],
        },
        {
            "id": "eggs",
            "name": "Eggs (Whole)",
            "unit": "egg",
            "default_portion": 3,
            "max_portion": 5,
            "cal": 72,
            "protein": 6.3,
            "carbs": 0.4,
            "fat": 4.8,
            "tags": ["vegetarian", "gluten_free", "dairy_free", "kosher"],
        },
        {
            "id": "egg_whites",
            "name": "Egg Whites",
            "unit": "egg",
            "default_portion": 4,
            "cal": 17,
            "protein": 3.6,
            "carbs": 0.2,
            "fat": 0.1,
            "tags": ["vegetarian", "gluten_free", "dairy_free", "kosher"],
        },
        {
            "id": "greek_yogurt",
            "name": "Greek Yogurt (Plain Nonfat)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 100,
            "protein": 17.0,
            "carbs": 6.0,
            "fat": 0.7,
            "tags": ["vegetarian", "gluten_free", "kosher"],
        },
        {
            "id": "cottage_cheese",
            "name": "Cottage Cheese (Low Fat 2%)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 183,
            "protein": 24.0,
            "carbs": 9.9,
            "fat": 5.1,
            "tags": ["vegetarian", "gluten_free", "kosher"],
        },
        {
            "id": "tofu_firm",
            "name": "Tofu (Firm)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 183,
            "protein": 19.9,
            "carbs": 5.4,
            "fat": 11.0,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "tempeh",
            "name": "Tempeh",
            "unit": "oz",
            "default_portion": 4,
            "cal": 56,
            "protein": 5.5,
            "carbs": 2.7,
            "fat": 3.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "whey_protein",
            "name": "Whey Protein Powder",
            "unit": "scoop",
            "default_portion": 1,
            "cal": 120,
            "protein": 24.0,
            "carbs": 3.0,
            "fat": 1.5,
            "tags": ["vegetarian", "gluten_free"],
        },
        {
            "id": "plant_protein",
            "name": "Plant Protein Powder (Pea/Rice)",
            "unit": "scoop",
            "default_portion": 1,
            "cal": 120,
            "protein": 21.0,
            "carbs": 6.0,
            "fat": 2.0,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
    ],

    "carbs": [
        {
            "id": "white_rice",
            "name": "White Rice (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 206,
            "protein": 4.3,
            "carbs": 44.5,
            "fat": 0.4,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "brown_rice",
            "name": "Brown Rice (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 216,
            "protein": 5.0,
            "carbs": 44.8,
            "fat": 1.8,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "oats",
            "name": "Oats (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "max_portion": 1.5,
            "cal": 166,
            "protein": 5.9,
            "carbs": 28.1,
            "fat": 3.6,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "sweet_potato",
            "name": "Sweet Potato (Baked)",
            "unit": "medium",
            "default_portion": 1,
            "max_portion": 2,
            "cal": 103,
            "protein": 2.3,
            "carbs": 23.6,
            "fat": 0.1,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "white_potato",
            "name": "White Potato (Baked)",
            "unit": "medium",
            "default_portion": 1,
            "cal": 161,
            "protein": 4.3,
            "carbs": 36.6,
            "fat": 0.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "quinoa",
            "name": "Quinoa (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "max_portion": 1.5,
            "cal": 222,
            "protein": 8.1,
            "carbs": 39.4,
            "fat": 3.6,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "whole_wheat_bread",
            "name": "Whole Wheat Bread",
            "unit": "slice",
            "default_portion": 2,
            "cal": 81,
            "protein": 3.6,
            "carbs": 13.8,
            "fat": 1.1,
            "tags": ["vegan", "vegetarian", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "whole_wheat_pasta",
            "name": "Whole Wheat Pasta (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 174,
            "protein": 7.5,
            "carbs": 37.2,
            "fat": 0.8,
            "tags": ["vegan", "vegetarian", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "black_beans",
            "name": "Black Beans (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 227,
            "protein": 15.2,
            "carbs": 40.8,
            "fat": 0.9,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "lentils",
            "name": "Lentils (Cooked)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 230,
            "protein": 17.9,
            "carbs": 39.9,
            "fat": 0.8,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "banana",
            "name": "Banana",
            "unit": "medium",
            "default_portion": 1,
            "max_portion": 2,
            "cal": 105,
            "protein": 1.3,
            "carbs": 27.0,
            "fat": 0.4,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "blueberries",
            "name": "Blueberries",
            "unit": "cup",
            "default_portion": 1,
            "cal": 84,
            "protein": 1.1,
            "carbs": 21.4,
            "fat": 0.5,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
    ],

    "vegetables": [
        {
            "id": "broccoli",
            "name": "Broccoli (Chopped)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 31,
            "protein": 2.6,
            "carbs": 6.0,
            "fat": 0.3,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "spinach",
            "name": "Spinach (Raw)",
            "unit": "cup",
            "default_portion": 2,
            "cal": 7,
            "protein": 0.9,
            "carbs": 1.1,
            "fat": 0.1,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "kale",
            "name": "Kale (Chopped, Raw)",
            "unit": "cup",
            "default_portion": 2,
            "cal": 7,
            "protein": 0.6,
            "carbs": 0.9,
            "fat": 0.3,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "asparagus",
            "name": "Asparagus",
            "unit": "cup",
            "default_portion": 1,
            "cal": 27,
            "protein": 2.9,
            "carbs": 5.2,
            "fat": 0.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "green_beans",
            "name": "Green Beans",
            "unit": "cup",
            "default_portion": 1,
            "cal": 31,
            "protein": 1.8,
            "carbs": 7.0,
            "fat": 0.1,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "bell_pepper",
            "name": "Bell Pepper (Chopped)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 30,
            "protein": 1.0,
            "carbs": 7.0,
            "fat": 0.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "zucchini",
            "name": "Zucchini (Sliced)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 19,
            "protein": 1.4,
            "carbs": 3.5,
            "fat": 0.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "cauliflower",
            "name": "Cauliflower (Chopped)",
            "unit": "cup",
            "default_portion": 1,
            "cal": 27,
            "protein": 2.1,
            "carbs": 5.3,
            "fat": 0.3,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "mixed_greens",
            "name": "Mixed Greens (Salad)",
            "unit": "cup",
            "default_portion": 2,
            "cal": 9,
            "protein": 0.7,
            "carbs": 1.5,
            "fat": 0.1,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "cherry_tomatoes",
            "name": "Cherry Tomatoes",
            "unit": "cup",
            "default_portion": 1,
            "cal": 27,
            "protein": 1.3,
            "carbs": 5.8,
            "fat": 0.3,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
    ],

    "fats": [
        {
            "id": "olive_oil",
            "name": "Olive Oil",
            "unit": "tbsp",
            "default_portion": 1,
            "cal": 119,
            "protein": 0,
            "carbs": 0,
            "fat": 13.5,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "coconut_oil",
            "name": "Coconut Oil",
            "unit": "tbsp",
            "default_portion": 1,
            "cal": 121,
            "protein": 0,
            "carbs": 0,
            "fat": 13.5,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "avocado",
            "name": "Avocado",
            "unit": "half",
            "default_portion": 1,
            "cal": 161,
            "protein": 2.0,
            "carbs": 8.6,
            "fat": 14.7,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "almonds",
            "name": "Almonds",
            "unit": "oz",
            "default_portion": 1,
            "cal": 164,
            "protein": 6.0,
            "carbs": 6.1,
            "fat": 14.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "walnuts",
            "name": "Walnuts",
            "unit": "oz",
            "default_portion": 1,
            "cal": 185,
            "protein": 4.3,
            "carbs": 3.9,
            "fat": 18.5,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "peanut_butter",
            "name": "Peanut Butter (Natural)",
            "unit": "tbsp",
            "default_portion": 2,
            "cal": 94,
            "protein": 3.6,
            "carbs": 3.6,
            "fat": 8.0,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "almond_butter",
            "name": "Almond Butter",
            "unit": "tbsp",
            "default_portion": 2,
            "cal": 98,
            "protein": 3.4,
            "carbs": 3.0,
            "fat": 8.9,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "chia_seeds",
            "name": "Chia Seeds",
            "unit": "tbsp",
            "default_portion": 2,
            "cal": 58,
            "protein": 2.0,
            "carbs": 5.1,
            "fat": 3.7,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "flax_seeds",
            "name": "Flax Seeds (Ground)",
            "unit": "tbsp",
            "default_portion": 2,
            "cal": 37,
            "protein": 1.3,
            "carbs": 2.0,
            "fat": 3.0,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "cheddar_cheese",
            "name": "Cheddar Cheese",
            "unit": "oz",
            "default_portion": 1,
            "cal": 113,
            "protein": 7.1,
            "carbs": 0.4,
            "fat": 9.3,
            "tags": ["vegetarian", "gluten_free", "kosher"],
        },
    ],

    "snacks": [
        {
            "id": "protein_bar",
            "name": "Protein Bar",
            "unit": "bar",
            "default_portion": 1,
            "cal": 210,
            "protein": 20.0,
            "carbs": 22.0,
            "fat": 7.0,
            "tags": ["vegetarian", "gluten_free"],
        },
        {
            "id": "rice_cakes",
            "name": "Rice Cakes (Plain)",
            "unit": "cake",
            "default_portion": 2,
            "cal": 35,
            "protein": 0.7,
            "carbs": 7.3,
            "fat": 0.3,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "apple",
            "name": "Apple",
            "unit": "medium",
            "default_portion": 1,
            "cal": 95,
            "protein": 0.5,
            "carbs": 25.1,
            "fat": 0.3,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "orange",
            "name": "Orange",
            "unit": "medium",
            "default_portion": 1,
            "cal": 62,
            "protein": 1.2,
            "carbs": 15.4,
            "fat": 0.2,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "beef_jerky",
            "name": "Beef Jerky",
            "unit": "oz",
            "default_portion": 1,
            "cal": 82,
            "protein": 6.6,
            "carbs": 6.1,
            "fat": 3.1,
            "tags": ["gluten_free", "dairy_free"],
        },
        {
            "id": "dark_chocolate",
            "name": "Dark Chocolate (85%+)",
            "unit": "oz",
            "default_portion": 1,
            "cal": 170,
            "protein": 2.2,
            "carbs": 13.0,
            "fat": 12.4,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "hummus",
            "name": "Hummus",
            "unit": "tbsp",
            "default_portion": 4,
            "cal": 25,
            "protein": 1.2,
            "carbs": 2.1,
            "fat": 1.4,
            "tags": ["vegan", "vegetarian", "gluten_free", "dairy_free", "halal", "kosher"],
        },
        {
            "id": "string_cheese",
            "name": "String Cheese",
            "unit": "stick",
            "default_portion": 1,
            "cal": 80,
            "protein": 7.0,
            "carbs": 1.0,
            "fat": 5.0,
            "tags": ["vegetarian", "gluten_free", "kosher"],
        },
    ],
}

# Build a flat lookup by ID for fast access
_FOOD_BY_ID = {}
for _category, _items in FOOD_CATALOG.items():
    for _item in _items:
        _FOOD_BY_ID[_item["id"]] = {**_item, "category": _category}


def get_food(food_id):
    """Look up a single food by ID. Returns dict with category field, or None."""
    return _FOOD_BY_ID.get(food_id)


def get_filtered_catalog(restrictions):
    """Filter catalog by dietary restrictions.

    restrictions: list like ["vegetarian", "gluten_free", "no_dairy"]

    Restriction mapping:
        "vegetarian"   -> keep only items tagged "vegetarian"
        "vegan"        -> keep only items tagged "vegan"
        "pescatarian"  -> keep items tagged "vegetarian" OR "pescatarian"
        "gluten_free"  -> keep only items tagged "gluten_free"
        "halal"        -> keep only items tagged "halal"
        "kosher"       -> keep only items tagged "kosher"
        "no_dairy"     -> keep only items tagged "dairy_free"
        "dairy_free"   -> keep only items tagged "dairy_free"

    Returns filtered FOOD_CATALOG dict (same shape, fewer items).
    """
    if not restrictions:
        return {cat: list(items) for cat, items in FOOD_CATALOG.items()}

    restrictions_lower = [r.lower().strip() for r in restrictions]

    # Diet-type restrictions: only keep foods WITH these tags
    diet_filters = []  # require item to have at least one of these tags
    if "vegan" in restrictions_lower:
        diet_filters.append("vegan")
    elif "vegetarian" in restrictions_lower:
        diet_filters.append("vegetarian")
    elif "pescatarian" in restrictions_lower:
        diet_filters.extend(["vegetarian", "pescatarian"])

    # Exclusion restrictions: remove foods WITHOUT these tags
    must_have = []
    if "no_dairy" in restrictions_lower or "dairy_free" in restrictions_lower:
        must_have.append("dairy_free")
    if "no_gluten" in restrictions_lower or "gluten_free" in restrictions_lower:
        must_have.append("gluten_free")
    if "halal" in restrictions_lower:
        must_have.append("halal")
    if "kosher" in restrictions_lower:
        must_have.append("kosher")

    filtered = {}
    for category, items in FOOD_CATALOG.items():
        kept = []
        for item in items:
            tags = set(item["tags"])

            # Diet filter: item must have at least one matching diet tag
            if diet_filters and not any(d in tags for d in diet_filters):
                continue

            # Exclusion filter: item must have ALL required tags
            if must_have and not all(t in tags for t in must_have):
                continue

            kept.append(item)
        filtered[category] = kept

    return filtered


def validate_selections(selections, daily_calories, daily_protein):
    """Check if user's food selections can meet nutritional needs.

    selections: {"proteins": ["chicken_breast", "eggs"], "carbs": [...], ...}
    daily_calories: target daily calories (int)
    daily_protein: target daily protein in grams (int)

    Returns dict:
        {
            "valid": bool,
            "warnings": [str],
            "protein_sources": int,       # number of protein items selected
            "can_hit_protein": bool,       # whether selections can plausibly hit protein target
            "estimated_max_protein": float # max protein from selections at default portions
        }
    """
    warnings = []
    protein_sources = 0
    total_default_cal = 0
    total_default_protein = 0

    all_ids = set()
    for category, ids in selections.items():
        for food_id in ids:
            if food_id in all_ids:
                warnings.append(f"Duplicate selection: {food_id}")
                continue
            all_ids.add(food_id)

            food = get_food(food_id)
            if food is None:
                warnings.append(f"Unknown food ID: {food_id}")
                continue

            if food["category"] != category:
                warnings.append(
                    f"{food_id} is in '{food['category']}' but was placed in '{category}'"
                )

            portion_cal = food["cal"] * food["default_portion"]
            portion_protein = food["protein"] * food["default_portion"]
            total_default_cal += portion_cal
            total_default_protein += portion_protein

            if food["category"] == "proteins":
                protein_sources += 1

    # Check protein source count
    if protein_sources < 2:
        warnings.append(
            f"Only {protein_sources} protein source(s) selected. Aim for at least 2-3 for variety."
        )

    # Estimate max protein: assume user can eat up to 2x default portions of protein sources
    max_protein = total_default_protein * 1.5  # generous scaling

    can_hit_protein = max_protein >= daily_protein
    if not can_hit_protein:
        warnings.append(
            f"Selected foods may not provide enough protein. "
            f"Estimated max ~{max_protein:.0f}g vs target {daily_protein}g."
        )

    # Check if default portions are in a reasonable calorie range
    if total_default_cal > 0:
        cal_ratio = daily_calories / total_default_cal
        if cal_ratio < 0.5:
            warnings.append(
                "Too many foods selected relative to calorie target. "
                "Portions will need to be very small."
            )
        elif cal_ratio > 3.0:
            warnings.append(
                "Few foods selected relative to calorie target. "
                "Consider adding more variety."
            )

    # Check category coverage
    for category in ["proteins", "carbs", "vegetables"]:
        if category not in selections or not selections[category]:
            warnings.append(f"No {category} selected. A balanced diet needs all food groups.")

    valid = len(warnings) == 0

    return {
        "valid": valid,
        "warnings": warnings,
        "protein_sources": protein_sources,
        "can_hit_protein": can_hit_protein,
        "estimated_max_protein": round(max_protein, 1),
    }
