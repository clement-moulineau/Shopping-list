from __future__ import annotations

import json
import sqlite3
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flask import Flask, Response, flash, g, redirect, render_template, request, url_for


SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    servings INTEGER NOT NULL CHECK (servings > 0)
);

CREATE TABLE IF NOT EXISTS ingredients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    quantity TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_plan (
    week_start TEXT NOT NULL,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    servings INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (week_start, recipe_id)
);

CREATE TABLE IF NOT EXISTS shopping_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    ingredient_key TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    UNIQUE (week_start, ingredient_key)
);
CREATE TABLE IF NOT EXISTS ingredient_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    default_quantity TEXT NOT NULL,
    default_unit TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT '🛒',
    image_data BLOB,
    image_mimetype TEXT
);
"""

NATURAL_INGREDIENT_UNITS = frozenset(
    {
        "g",
        "kg",
        "mg",
        "ml",
        "cl",
        "l",
        "gramme",
        "grammes",
        "litre",
        "litres",
        "centilitre",
        "centilitres",
        "millilitre",
        "millilitres",
        "tsp",
        "tbsp",
        "cup",
        "cups",
        "oz",
        "lb",
        "c. à café",
        "c. à soupe",
        "cuillère à café",
        "cuillères à café",
        "cuillère à soupe",
        "cuillères à soupe",
        "tasse",
        "tasses",
        "pincée",
        "pincées",
        "gousse",
        "gousses",
        "tranche",
        "tranches",
        "botte",
        "bottes",
        "boîte",
        "boîtes",
        "sachet",
        "sachets",
        "verre",
        "verres",
        "pièce",
        "pièces",
    }
)
NATURAL_INGREDIENT_UNIT_PATTERN = "|".join(
    re.escape(unit)
    for unit in sorted(NATURAL_INGREDIENT_UNITS, key=len, reverse=True)
)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY="local-grocery-planner",
        DATABASE=str(Path(app.instance_path) / "groceries.sqlite3"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    aliases_path = Path(__file__).parent / "data" / "ingredient_aliases.json"
    with aliases_path.open(encoding="utf-8") as aliases_file:
        ingredient_aliases = {
            alias.casefold(): canonical
            for alias, canonical in json.load(aliases_file).items()
        }
    icons_path = Path(__file__).parent / "data" / "ingredient_icons.json"
    with icons_path.open(encoding="utf-8") as icons_file:
        ingredient_icon_data = json.load(icons_file)
    category_icons = ingredient_icon_data["default_by_category"]
    ingredient_icons = {
        name.casefold(): icon
        for name, icon in ingredient_icon_data["ingredients"].items()
    }

    def initialize_database() -> None:
        database = sqlite3.connect(app.config["DATABASE"])
        database.row_factory = sqlite3.Row
        try:
            database.executescript(SCHEMA)
            ingredient_count = database.execute(
                "SELECT COUNT(*) FROM ingredient_catalog"
            ).fetchone()[0]
            seed_path = Path(__file__).parent / "data" / "initial_ingredients.json"
            with seed_path.open(encoding="utf-8") as seed_file:
                ingredients = json.load(seed_file)
            if ingredient_count == 0:
                database.executemany(
                    """
                    INSERT INTO ingredient_catalog
                        (name, name_key, category, default_quantity, default_unit, icon)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item["name"],
                            item["name"].casefold(),
                            item["category"],
                            item["default_quantity"],
                            item["default_unit"],
                            item["icon"],
                        )
                        for item in ingredients
                    ],
                )
            category_path = (
                Path(__file__).parent / "data" / "recipe_ingredient_categories.json"
            )
            with category_path.open(encoding="utf-8") as category_file:
                recipe_ingredient_categories = json.load(category_file)
            ingredient_categories = {
                item["name"].casefold(): item["category"] for item in ingredients
            }
            ingredient_categories.update(recipe_ingredient_categories)
            migration_changed = False
            for row in database.execute(
                "SELECT DISTINCT name FROM ingredients"
            ).fetchall():
                name = row[0]
                category = ingredient_categories.get(name.casefold())
                if category is None:
                    continue
                name_key = name.casefold()
                catalog_entry = database.execute(
                    "SELECT category FROM ingredient_catalog WHERE name_key = ?",
                    (name_key,),
                ).fetchone()
                if catalog_entry is None:
                    database.execute(
                        """
                        INSERT INTO ingredient_catalog
                            (name, name_key, category, default_quantity)
                        VALUES (?, ?, ?, '1')
                        """,
                        (name, name_key, category),
                    )
                    migration_changed = True
                elif catalog_entry[0].strip().casefold() in {
                    "",
                    "other",
                    "others",
                    "autres",
                }:
                    database.execute(
                        "UPDATE ingredient_catalog SET category = ? WHERE name_key = ?",
                        (category, name_key),
                    )
            for alias_entry in database.execute(
                "SELECT id, name, image_data, image_mimetype FROM ingredient_catalog"
            ).fetchall():
                canonical_name = ingredient_aliases.get(alias_entry["name"].casefold())
                if canonical_name is None:
                    continue
                canonical_entry = database.execute(
                    """
                    SELECT id, image_data, image_mimetype
                    FROM ingredient_catalog WHERE name_key = ?
                    """,
                    (canonical_name.casefold(),),
                ).fetchone()
                if canonical_entry is None:
                    database.execute(
                        """
                        UPDATE ingredient_catalog
                        SET name = ?, name_key = ?
                        WHERE id = ?
                        """,
                        (canonical_name, canonical_name.casefold(), alias_entry["id"]),
                    )
                else:
                    database.execute(
                        """
                        UPDATE ingredient_catalog
                        SET image_data = COALESCE(image_data, ?),
                            image_mimetype = COALESCE(image_mimetype, ?)
                        WHERE id = ?
                        """,
                        (
                            alias_entry["image_data"],
                            alias_entry["image_mimetype"],
                            canonical_entry["id"],
                        ),
                    )
                    database.execute(
                        "DELETE FROM ingredient_catalog WHERE id = ?",
                        (alias_entry["id"],),
                    )
                migration_changed = True

            for catalog_entry in database.execute(
                "SELECT id, name, category, icon, image_data FROM ingredient_catalog"
            ).fetchall():
                icon = ingredient_icons.get(
                    catalog_entry["name"].casefold(),
                    category_icons.get(catalog_entry["category"].casefold(), "🛒"),
                )
                if (
                    catalog_entry["icon"] != icon
                    and catalog_entry["image_data"] is None
                ):
                    database.execute(
                        "UPDATE ingredient_catalog SET icon = ? WHERE id = ?",
                        (icon, catalog_entry["id"]),
                    )
                    migration_changed = True

            for row in database.execute(
                "SELECT id, name FROM ingredients"
            ).fetchall():
                canonical_name = ingredient_aliases.get(row["name"].casefold())
                if canonical_name is not None:
                    database.execute(
                        "UPDATE ingredients SET name = ? WHERE id = ?",
                        (canonical_name, row["id"]),
                    )
                    migration_changed = True

            ingredient_groups: dict[
                tuple[int, str, str], list[sqlite3.Row]
            ] = {}
            for row in database.execute(
                """
                SELECT id, recipe_id, name, unit, quantity
                FROM ingredients
                ORDER BY id
                """
            ):
                key = (
                    row["recipe_id"],
                    row["name"].casefold(),
                    row["unit"].strip().casefold(),
                )
                ingredient_groups.setdefault(key, []).append(row)
            for rows in ingredient_groups.values():
                if len(rows) < 2:
                    continue
                total = sum((Decimal(row["quantity"]) for row in rows), Decimal("0"))
                database.execute(
                    "UPDATE ingredients SET quantity = ? WHERE id = ?",
                    (format_quantity(total), rows[0]["id"]),
                )
                database.executemany(
                    "DELETE FROM ingredients WHERE id = ?",
                    [(row["id"],) for row in rows[1:]],
                )
                migration_changed = True

            weekly_plan_columns = {
                row[1] for row in database.execute("PRAGMA table_info(weekly_plan)")
            }
            if "servings" not in weekly_plan_columns:
                database.execute(
                    "ALTER TABLE weekly_plan ADD COLUMN servings INTEGER NOT NULL DEFAULT 1"
                )
                database.execute(
                    """
                    UPDATE weekly_plan
                    SET servings = (
                        SELECT recipes.servings
                        FROM recipes
                        WHERE recipes.id = weekly_plan.recipe_id
                    )
                    """
                )
            database.commit()
            if migration_changed:
                for row in database.execute(
                    "SELECT DISTINCT week_start FROM weekly_plan"
                ).fetchall():
                    refresh_shopping_list(database, row["week_start"])
        finally:
            database.close()

    @app.teardown_appcontext
    def close_database(error: BaseException | None = None) -> None:
        del error
        database = g.pop("database", None)
        if database is not None:
            database.close()

    def get_database() -> sqlite3.Connection:
        if "database" not in g:
            g.database = sqlite3.connect(app.config["DATABASE"])
            g.database.row_factory = sqlite3.Row
            g.database.execute("PRAGMA foreign_keys = ON")
        return g.database

    def current_week_start() -> str:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def ingredient_key(name: str, unit: str) -> str:
        return f"{name.strip().casefold()}\x1f{unit.strip().casefold()}"

    def format_quantity(quantity: Decimal) -> str:
        return format(quantity.normalize(), "f")

    def format_recipe_ingredient(quantity: str, unit: str, name: str) -> str:
        if unit and unit.casefold() not in NATURAL_INGREDIENT_UNITS:
            return f"{quantity} | {unit} | {name}"
        unit_text = f'{" " if " " in unit else ""}{unit}' if unit else ""
        return f"{quantity}{unit_text} {name}"

    def parse_recipe_input(
        name: str, servings_text: str, ingredient_text: str
    ) -> tuple[str, int, list[tuple[str, str, str]]]:
        name = name.strip()
        if not name:
            raise ValueError("Enter a recipe name.")

        try:
            servings = int(servings_text)
        except ValueError as error:
            raise ValueError("Enter a whole number of servings.") from error
        if servings < 1:
            raise ValueError("Servings must be at least one.")

        combined_ingredients: dict[tuple[str, str], tuple[str, str, Decimal]] = {}
        for line_number, line in enumerate(ingredient_text.splitlines(), start=1):
            if not line.strip():
                continue
            if "|" in line:
                parts = [part.strip() for part in line.split("|")]
                if len(parts) != 3 or not parts[0] or not parts[2]:
                    raise ValueError(
                        f"Ingredient line {line_number} must use quantity | unit | name."
                    )
                quantity_text, unit, ingredient = parts
            else:
                match = re.fullmatch(
                    rf"\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+))"
                    rf"(?:\s*({NATURAL_INGREDIENT_UNIT_PATTERN}))?"
                    r"\s+(.+?)\s*",
                    line,
                    re.IGNORECASE,
                )
                if match is None:
                    raise ValueError(
                        f"Ingredient line {line_number} must contain a quantity "
                        "and ingredient name, for example 100g boeuf or 1 poire."
                    )
                quantity_text, unit, ingredient = match.groups()
                unit = unit or ""
            try:
                quantity = Decimal(quantity_text.replace(",", "."))
            except InvalidOperation as error:
                raise ValueError(
                    f"Ingredient line {line_number} needs a valid quantity."
                ) from error
            if not quantity.is_finite() or quantity <= 0:
                raise ValueError(
                    f"Ingredient line {line_number} needs a quantity greater than zero."
                )
            ingredient = ingredient_aliases.get(ingredient.casefold(), ingredient)
            ingredient_key = (ingredient.casefold(), unit.strip().casefold())
            if ingredient_key not in combined_ingredients:
                combined_ingredients[ingredient_key] = (
                    ingredient,
                    unit,
                    quantity,
                )
            else:
                previous = combined_ingredients[ingredient_key]
                combined_ingredients[ingredient_key] = (
                    previous[0],
                    previous[1],
                    previous[2] + quantity,
                )

        if not combined_ingredients:
            raise ValueError("Add at least one ingredient.")
        ingredients = [
            (ingredient, unit, format_quantity(quantity))
            for ingredient, unit, quantity in combined_ingredients.values()
        ]
        return name, servings, ingredients

    def refresh_shopping_list(database: sqlite3.Connection, week_start: str) -> None:
        existing: dict[str, int] = {}
        for row in database.execute(
            """
            SELECT name, unit, checked
            FROM shopping_items
            WHERE week_start = ?
            """,
            (week_start,),
        ):
            name = ingredient_aliases.get(row["name"].casefold(), row["name"])
            key = ingredient_key(name, row["unit"])
            existing[key] = max(existing.get(key, 0), row["checked"])
        totals: dict[str, dict[str, Any]] = {}
        rows = database.execute(
            """
            SELECT ingredients.name, ingredients.unit, ingredients.quantity,
                   weekly_plan.servings AS planned_servings,
                   recipes.servings AS recipe_servings
            FROM ingredients
            JOIN weekly_plan ON weekly_plan.recipe_id = ingredients.recipe_id
            JOIN recipes ON recipes.id = ingredients.recipe_id
            WHERE weekly_plan.week_start = ?
            ORDER BY ingredients.id
            """,
            (week_start,),
        )
        for row in rows:
            key = ingredient_key(row["name"], row["unit"])
            if key not in totals:
                totals[key] = {
                    "name": row["name"].strip(),
                    "unit": row["unit"].strip(),
                    "quantity": Decimal("0"),
                }
            scaled_quantity = (
                Decimal(row["quantity"])
                * row["planned_servings"]
                / row["recipe_servings"]
            )
            totals[key]["quantity"] += scaled_quantity

        with database:
            database.execute(
                "DELETE FROM shopping_items WHERE week_start = ?", (week_start,)
            )
            database.executemany(
                """
                INSERT INTO shopping_items
                    (week_start, ingredient_key, name, unit, quantity, checked)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        week_start,
                        key,
                        item["name"],
                        item["unit"],
                        format_quantity(item["quantity"]),
                        existing.get(key, 0),
                    )
                    for key, item in totals.items()
                ],
            )

    @app.get("/")
    def index():
        database = get_database()
        week_start = current_week_start()
        ingredient_category_options = [
            row["category"]
            for row in database.execute(
                """
                SELECT DISTINCT category
                FROM ingredient_catalog
                WHERE TRIM(category) != ''
                ORDER BY category COLLATE NOCASE
                """
            )
        ]
        ingredient_unit_options = [
            row["default_unit"]
            for row in database.execute(
                """
                SELECT DISTINCT default_unit
                FROM ingredient_catalog
                WHERE TRIM(default_unit) != ''
                ORDER BY default_unit COLLATE NOCASE
                """
            )
        ]
        ingredient_groups: dict[str, list[dict[str, Any]]] = {}
        ingredient_categories: dict[str, str] = {}
        for ingredient in database.execute(
            """
            SELECT id, name, category, default_quantity, default_unit, icon,
                   image_data IS NOT NULL AS has_image
            FROM ingredient_catalog
            ORDER BY category COLLATE NOCASE, name COLLATE NOCASE
            """
        ):
            ingredient_data = dict(ingredient)
            ingredient_categories[ingredient["name"].casefold()] = ingredient[
                "category"
            ]
            ingredient_data["entry_text"] = format_recipe_ingredient(
                ingredient["default_quantity"],
                ingredient["default_unit"],
                ingredient["name"],
            )
            ingredient_data["image_url"] = (
                url_for("ingredient_image", ingredient_id=ingredient["id"])
                if ingredient["has_image"]
                else None
            )
            ingredient_groups.setdefault(ingredient["category"], []).append(
                ingredient_data
            )
        recipes = database.execute(
            """
            SELECT recipes.id, recipes.name, recipes.servings,
                   COUNT(ingredients.id) AS ingredient_count
            FROM recipes
            LEFT JOIN ingredients ON ingredients.recipe_id = recipes.id
            GROUP BY recipes.id
            ORDER BY recipes.name COLLATE NOCASE
            """
        ).fetchall()
        recipe_list = []
        for recipe in recipes:
            recipe_data = dict(recipe)
            ingredients = database.execute(
                """
                SELECT name, unit, quantity
                FROM ingredients
                WHERE recipe_id = ?
                ORDER BY id
                """,
                (recipe["id"],),
            ).fetchall()
            recipe_data["ingredient_text"] = "\n".join(
                format_recipe_ingredient(
                    ingredient["quantity"], ingredient["unit"], ingredient["name"]
                )
                for ingredient in ingredients
            )
            recipe_list.append(recipe_data)
        selected_servings = {
            row["recipe_id"]: row["servings"]
            for row in database.execute(
                "SELECT recipe_id, servings FROM weekly_plan WHERE week_start = ?",
                (week_start,),
            )
        }
        shopping_sort = request.args.get("sort", "name")
        if shopping_sort not in {"name", "recipe", "category"}:
            shopping_sort = "name"

        recipe_names_by_ingredient: dict[str, set[str]] = {}
        for ingredient in database.execute(
            """
            SELECT ingredients.name, ingredients.unit, recipes.name AS recipe_name
            FROM ingredients
            JOIN weekly_plan ON weekly_plan.recipe_id = ingredients.recipe_id
            JOIN recipes ON recipes.id = ingredients.recipe_id
            WHERE weekly_plan.week_start = ?
            """,
            (week_start,),
        ):
            key = ingredient_key(ingredient["name"], ingredient["unit"])
            recipe_names_by_ingredient.setdefault(key, set()).add(
                ingredient["recipe_name"]
            )

        shopping_rows = database.execute(
            """
            SELECT id, name, unit, quantity, checked
            FROM shopping_items
            WHERE week_start = ?
            ORDER BY checked, name COLLATE NOCASE
            """,
            (week_start,),
        ).fetchall()
        shopping_groups_by_name: dict[str, list[dict[str, Any]]] = {}
        for shopping_item in shopping_rows:
            item = dict(shopping_item)
            key = ingredient_key(item["name"], item["unit"])
            if shopping_sort == "category":
                group_name = ingredient_categories.get(
                    item["name"].casefold(), "Other"
                )
            elif shopping_sort == "recipe":
                recipes_for_item = sorted(
                    recipe_names_by_ingredient.get(key, set()),
                    key=str.casefold,
                )
                group_name = " · ".join(recipes_for_item) or "Other"
            else:
                group_name = ""
            shopping_groups_by_name.setdefault(group_name, []).append(item)

        shopping_groups = [
            {
                "name": group_name,
                "items": sorted(
                    items,
                    key=lambda item: (
                        item["checked"],
                        item["name"].casefold(),
                    ),
                ),
            }
            for group_name, items in sorted(
                shopping_groups_by_name.items(),
                key=lambda group: (
                    shopping_sort == "category"
                    and group[0].casefold() == "other",
                    group[0].casefold(),
                ),
            )
        ]
        return render_template(
            "index.html",
            recipes=recipe_list,
            selected_ids=set(selected_servings),
            selected_servings=selected_servings,
            shopping_groups=shopping_groups,
            shopping_item_count=len(shopping_rows),
            shopping_sort=shopping_sort,
            show_shopping_list=request.args.get("show_list") == "1",
            week_start=week_start,
            common_ingredients=list(ingredient_groups.items()),
            ingredient_category_options=ingredient_category_options,
            ingredient_unit_options=ingredient_unit_options,
        )

    @app.get("/ingredients/<int:ingredient_id>/image")
    def ingredient_image(ingredient_id: int):
        image = get_database().execute(
            "SELECT image_data, image_mimetype FROM ingredient_catalog WHERE id = ?",
            (ingredient_id,),
        ).fetchone()
        if image is None or image["image_data"] is None:
            return "Ingredient image not found.", 404
        response = Response(image["image_data"], mimetype=image["image_mimetype"])
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/shopping-list.txt")
    def download_shopping_list():
        week_start = current_week_start()
        shopping_items = get_database().execute(
            """
            SELECT name, unit, quantity, checked
            FROM shopping_items
            WHERE week_start = ?
            ORDER BY name COLLATE NOCASE
            """,
            (week_start,),
        ).fetchall()
        lines = [f"Shopping list - week of {week_start}", ""]
        for item in shopping_items:
            checkmark = "x" if item["checked"] else " "
            quantity = " ".join(
                part for part in (item["quantity"], item["unit"]) if part
            )
            lines.append(f"- [{checkmark}] {quantity} {item['name']}")
        if not shopping_items:
            lines.append("No items yet.")

        response = Response(
            "\n".join(lines) + "\n",
            content_type="text/plain; charset=utf-8",
        )
        response.headers["Content-Disposition"] = (
            'attachment; filename="shopping-list.txt"'
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(413)
    def request_too_large(error: Exception):
        del error
        flash("The image must be smaller than 4 MB.", "error")
        return redirect(url_for("index"))

    @app.post("/ingredients")
    def add_ingredient():
        name = request.form.get("name", "").strip()
        name = ingredient_aliases.get(name.casefold(), name)
        category = request.form.get("category", "").strip()
        quantity_text = request.form.get("default_quantity", "1").strip()
        unit = request.form.get("default_unit", "").strip()

        if not name or len(name) > 80:
            flash("Enter an ingredient name of 1 to 80 characters.", "error")
            return redirect(url_for("index"))
        if not category or len(category) > 50:
            flash("Enter a category of 1 to 50 characters.", "error")
            return redirect(url_for("index"))
        if len(unit) > 20:
            flash("The default unit must be 20 characters or fewer.", "error")
            return redirect(url_for("index"))
        try:
            quantity = Decimal(quantity_text.replace(",", "."))
        except InvalidOperation:
            flash("Enter a valid default quantity greater than zero.", "error")
            return redirect(url_for("index"))
        if not quantity.is_finite() or quantity <= 0:
            flash("Enter a valid default quantity greater than zero.", "error")
            return redirect(url_for("index"))

        image_file = request.files.get("image")
        image_data = image_file.read() if image_file and image_file.filename else None
        image_mimetype = None
        if image_data:
            image_signatures = (
                (b"\x89PNG\r\n\x1a\n", "image/png"),
                (b"\xff\xd8\xff", "image/jpeg"),
                (b"GIF87a", "image/gif"),
                (b"GIF89a", "image/gif"),
            )
            image_mimetype = next(
                (
                    mimetype
                    for signature, mimetype in image_signatures
                    if image_data.startswith(signature)
                ),
                None,
            )
            if (
                image_mimetype is None
                and len(image_data) >= 12
                and image_data.startswith(b"RIFF")
                and image_data[8:12] == b"WEBP"
            ):
                image_mimetype = "image/webp"
            if image_mimetype is None or len(image_data) > 4 * 1024 * 1024:
                flash("Upload a PNG, JPEG, GIF, or WebP image smaller than 4 MB.", "error")
                return redirect(url_for("index"))

        database = get_database()
        icon = ingredient_icons.get(
            name.casefold(),
            category_icons.get(category.casefold(), "🛒"),
        )
        try:
            with database:
                database.execute(
                    """
                    INSERT INTO ingredient_catalog
                        (name, name_key, category, default_quantity, default_unit,
                         icon, image_data, image_mimetype)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        name.casefold(),
                        category,
                        format_quantity(quantity),
                        unit,
                        icon,
                        image_data,
                        image_mimetype,
                    ),
                )
        except sqlite3.IntegrityError:
            flash("An ingredient with that name already exists.", "error")
            return redirect(url_for("index"))

        flash(f"Added {name} to your ingredient library.", "success")
        return redirect(url_for("index"))

    @app.post("/recipes")
    def add_recipe():
        try:
            name, servings, ingredients = parse_recipe_input(
                request.form.get("name", ""),
                request.form.get("servings", "").strip(),
                request.form.get("ingredients", ""),
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))

        database = get_database()
        try:
            with database:
                cursor = database.execute(
                    "INSERT INTO recipes (name, servings) VALUES (?, ?)",
                    (name, servings),
                )
                database.executemany(
                    "INSERT INTO ingredients (recipe_id, name, unit, quantity) VALUES (?, ?, ?, ?)",
                    [
                        (cursor.lastrowid, ingredient, unit, quantity)
                        for ingredient, unit, quantity in ingredients
                    ],
                )
        except sqlite3.IntegrityError:
            flash("A recipe with that name already exists.", "error")
            return redirect(url_for("index"))

        flash(f"Added {name}.", "success")
        return redirect(url_for("index"))

    @app.post("/recipes/<int:recipe_id>/edit")
    def edit_recipe(recipe_id: int):
        database = get_database()
        recipe = database.execute(
            "SELECT id, servings FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        if recipe is None:
            return "Recipe not found.", 404

        try:
            name, servings, ingredients = parse_recipe_input(
                request.form.get("name", ""),
                request.form.get("servings", "").strip(),
                request.form.get("ingredients", ""),
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("index"))

        week_start = current_week_start()
        selected_plan = database.execute(
            "SELECT servings FROM weekly_plan WHERE week_start = ? AND recipe_id = ?",
            (week_start, recipe_id),
        ).fetchone()
        try:
            with database:
                database.execute(
                    "UPDATE recipes SET name = ?, servings = ? WHERE id = ?",
                    (name, servings, recipe_id),
                )
                database.execute(
                    "DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,)
                )
                database.executemany(
                    """
                    INSERT INTO ingredients (recipe_id, name, unit, quantity)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (recipe_id, ingredient, unit, quantity)
                        for ingredient, unit, quantity in ingredients
                    ],
                )
                if (
                    selected_plan is not None
                    and selected_plan["servings"] == recipe["servings"]
                ):
                    database.execute(
                        """
                        UPDATE weekly_plan
                        SET servings = ?
                        WHERE week_start = ? AND recipe_id = ?
                        """,
                        (servings, week_start, recipe_id),
                    )
        except sqlite3.IntegrityError:
            flash("A recipe with that name already exists.", "error")
            return redirect(url_for("index"))

        if selected_plan is not None:
            refresh_shopping_list(database, week_start)
        flash(f"Updated {name}.", "success")
        return redirect(url_for("index"))

    @app.post("/recipes/<int:recipe_id>/delete")
    def delete_recipe(recipe_id: int):
        database = get_database()
        recipe = database.execute(
            "SELECT name FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        if recipe is None:
            return "Recipe not found.", 404

        week_start = current_week_start()
        with database:
            database.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
        refresh_shopping_list(database, week_start)
        flash(f"Deleted {recipe['name']}.", "success")
        return redirect(url_for("index"))

    @app.post("/plan")
    def save_plan():
        database = get_database()
        week_start = current_week_start()
        requested_ids = request.form.getlist("recipe_ids")
        try:
            recipe_ids = {int(recipe_id) for recipe_id in requested_ids}
        except ValueError:
            flash("The recipe selection was invalid.", "error")
            return redirect(url_for("index"))

        available_servings = {
            row["id"]: row["servings"]
            for row in database.execute("SELECT id, servings FROM recipes")
        }
        if not recipe_ids.issubset(available_servings):
            flash("One or more selected recipes no longer exist.", "error")
            return redirect(url_for("index"))

        planned_servings: dict[int, int] = {}
        for recipe_id in recipe_ids:
            servings_text = request.form.get(
                f"servings_{recipe_id}", str(available_servings[recipe_id])
            ).strip()
            try:
                servings = int(servings_text)
            except ValueError:
                flash("Servings must be a whole number greater than zero.", "error")
                return redirect(url_for("index"))
            if servings <= 0:
                flash("Servings must be a whole number greater than zero.", "error")
                return redirect(url_for("index"))
            planned_servings[recipe_id] = servings

        with database:
            database.execute(
                "DELETE FROM weekly_plan WHERE week_start = ?", (week_start,)
            )
            database.executemany(
                """
                INSERT INTO weekly_plan (week_start, recipe_id, servings)
                VALUES (?, ?, ?)
                """,
                [
                    (week_start, recipe_id, servings)
                    for recipe_id, servings in planned_servings.items()
                ],
            )
        refresh_shopping_list(database, week_start)
        flash("Your plan and shopping list are up to date.", "success")
        return redirect(url_for("index", show_list=1))

    @app.post("/shopping/<int:item_id>/toggle")
    def toggle_shopping_item(item_id: int):
        database = get_database()
        with database:
            database.execute(
                """
                UPDATE shopping_items
                SET checked = CASE checked WHEN 0 THEN 1 ELSE 0 END
                WHERE id = ? AND week_start = ?
                """,
                (item_id, current_week_start()),
            )
        shopping_sort = request.form.get("sort", "name")
        if shopping_sort not in {"name", "recipe", "category"}:
            shopping_sort = "name"
        return redirect(url_for("index", show_list=1, sort=shopping_sort))

    with app.app_context():
        initialize_database()

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=False)
