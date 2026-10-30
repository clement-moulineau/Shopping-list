from io import BytesIO
import tempfile
import unittest
from pathlib import Path
import sqlite3

from app import create_app


class GroceryPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = str(Path(self.temp_dir.name) / "test.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": database,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_recipe(self, name, ingredients):
        return self.client.post(
            "/recipes",
            data={
                "name": name,
                "servings": "2",
                "ingredients": ingredients,
            },
            follow_redirects=True,
        )

    def test_shopping_list_is_hidden_until_week_is_updated(self):
        self.add_recipe("Soup", "2 | | carrots")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()

        response = self.client.get("/")

        self.assertIn(b'class="workspace planning-only"', response.data)
        self.assertNotIn(b'class="panel shopping-panel"', response.data)

        response = self.client.post(
            "/plan", data={"recipe_ids": str(recipe_id)}, follow_redirects=True
        )

        self.assertIn(b'class="panel shopping-panel"', response.data)
        self.assertIn(b'class="item-name">carrots</span>', response.data)
        response = self.client.get("/")
        self.assertNotIn(b'class="panel shopping-panel"', response.data)

    def test_shopping_list_can_be_downloaded_as_text(self):
        self.add_recipe("Soup", "2 | | carrots\n1 | kg | potatoes")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()
        self.client.post("/plan", data={"recipe_ids": str(recipe_id)})
        database = sqlite3.connect(self.app.config["DATABASE"])
        carrot_id = database.execute(
            "SELECT id FROM shopping_items WHERE name = 'carrots'"
        ).fetchone()[0]
        database.close()
        self.client.post(f"/shopping/{carrot_id}/toggle")

        response = self.client.get("/shopping-list.txt")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/plain")
        self.assertIn('attachment; filename="shopping-list.txt"', response.headers["Content-Disposition"])
        self.assertIn(b"- [x] 2 carrots", response.data)
        self.assertIn(b"- [ ] 1 kg potatoes", response.data)
        page = self.client.get("/?show_list=1")
        self.assertIn(b"Share list", page.data)
        self.assertIn(b"Download .txt", page.data)

    def test_selected_recipes_combine_matching_ingredients(self):
        self.add_recipe("Tomato pasta", "2 | cups | tomatoes\n1 | tbsp | olive oil")
        self.add_recipe("Tomato soup", "1.5 | cups | TOMATOES\n2 | tbsp | olive oil")

        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_ids = [
            row[0] for row in database.execute("SELECT id FROM recipes ORDER BY id")
        ]
        database.close()

        response = self.client.post(
            "/plan",
            data={"recipe_ids": [str(recipe_id) for recipe_id in recipe_ids]},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data.count(b'class="item-name">tomatoes</span>'), 1
        )
        self.assertIn(b'<span class="item-quantity">3.5 cups</span>', response.data)
        self.assertIn(b'<span class="item-quantity">3 tbsp</span>', response.data)

    def test_shopping_list_can_be_grouped_by_category(self):
        self.add_recipe("Soup", "2 | | carottes\n1 | | poulet\n1 | | unknown ingredient")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()
        self.client.post("/plan", data={"recipe_ids": str(recipe_id)})

        response = self.client.get("/?show_list=1&sort=category")
        page = response.data.decode()

        self.assertIn('option value="category" selected', page)
        self.assertLess(page.index(">Légumes</h3>"), page.index(">Viandes</h3>"))
        self.assertLess(page.index(">carotte</span>"), page.index(">poulet</span>"))
        self.assertLess(page.index(">Viandes</h3>"), page.index(">Other</h3>"))
        self.assertLess(page.index(">poulet</span>"), page.index(">unknown ingredient</span>"))

    def test_shopping_list_can_be_grouped_by_recipe_without_uncombining_items(self):
        self.add_recipe("Soup", "2 | | carrots\n1 | | onions")
        self.add_recipe("Salad", "1 | | carrots\n1 | | tomatoes")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_ids = [
            row[0] for row in database.execute("SELECT id FROM recipes")
        ]
        database.close()
        self.client.post(
            "/plan",
            data={"recipe_ids": [str(recipe_id) for recipe_id in recipe_ids]},
        )

        response = self.client.get("/?show_list=1&sort=recipe")
        page = response.data.decode()

        self.assertIn('option value="recipe" selected', page)
        self.assertLess(page.index(">Salad · Soup</h3>"), page.index(">Soup</h3>"))
        self.assertEqual(page.count('class="item-name">carrots</span>'), 1)
        self.assertIn('<span class="item-quantity">3</span>', page)

    def test_selected_recipe_scales_ingredients_to_planned_servings(self):
        self.add_recipe("Poulet", "200g poulet")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()

        response = self.client.post(
            "/plan",
            data={"recipe_ids": str(recipe_id), f"servings_{recipe_id}": "4"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<span class="item-quantity">400 g</span>', response.data)
        self.assertIn(
            f'id="servings-{recipe_id}" name="servings_{recipe_id}"'.encode(),
            response.data,
        )
        self.assertIn(b'type="number" min="1" step="1"\n                           value="4"', response.data)

        database = sqlite3.connect(self.app.config["DATABASE"])
        self.assertEqual(
            database.execute(
                "SELECT servings FROM weekly_plan WHERE recipe_id = ?", (recipe_id,)
            ).fetchone()[0],
            4,
        )
        database.close()

    def test_invalid_planned_servings_do_not_change_weekly_plan(self):
        self.add_recipe("Poulet", "200g poulet")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()
        self.client.post(
            "/plan",
            data={"recipe_ids": str(recipe_id), f"servings_{recipe_id}": "3"},
        )

        response = self.client.post(
            "/plan",
            data={"recipe_ids": str(recipe_id), f"servings_{recipe_id}": "0"},
            follow_redirects=True,
        )

        self.assertIn(b"Servings must be a whole number greater than zero.", response.data)
        database = sqlite3.connect(self.app.config["DATABASE"])
        self.assertEqual(
            database.execute(
                "SELECT servings FROM weekly_plan WHERE recipe_id = ?", (recipe_id,)
            ).fetchone()[0],
            3,
        )
        database.close()

    def test_existing_weekly_plan_defaults_to_recipe_servings_after_migration(self):
        database_path = str(Path(self.temp_dir.name) / "legacy.sqlite3")
        database = sqlite3.connect(database_path)
        database.executescript(
            """
            CREATE TABLE recipes (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                servings INTEGER NOT NULL
            );
            CREATE TABLE weekly_plan (
                week_start TEXT NOT NULL,
                recipe_id INTEGER NOT NULL,
                PRIMARY KEY (week_start, recipe_id)
            );
            INSERT INTO recipes (id, name, servings) VALUES (1, 'Poulet', 3);
            INSERT INTO weekly_plan (week_start, recipe_id)
            VALUES ('2026-10-26', 1);
            """
        )
        database.close()

        create_app({"TESTING": True, "DATABASE": database_path})

        database = sqlite3.connect(database_path)
        servings = database.execute(
            "SELECT servings FROM weekly_plan WHERE recipe_id = 1"
        ).fetchone()[0]
        database.close()
        self.assertEqual(servings, 3)

    def test_shopping_items_can_be_checked_and_remain_checked_after_plan_refresh(self):
        self.add_recipe("Soup", "2 | | carrots")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()

        response = self.client.post(
            "/plan", data={"recipe_ids": str(recipe_id)}, follow_redirects=True
        )
        self.assertIn(b"carrots", response.data)

        database = sqlite3.connect(self.app.config["DATABASE"])
        item_id = database.execute("SELECT id FROM shopping_items").fetchone()[0]
        database.close()

        self.client.post(f"/shopping/{item_id}/toggle")
        response = self.client.post(
            "/plan", data={"recipe_ids": str(recipe_id)}, follow_redirects=True
        )
        self.assertIn(b"is-checked", response.data)

    def test_invalid_ingredient_does_not_create_recipe(self):
        response = self.add_recipe("Broken recipe", "0 | cups | flour")

        self.assertIn(b"needs a quantity greater than zero", response.data)
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_count = database.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        database.close()
        self.assertEqual(recipe_count, 0)

    def test_natural_ingredient_lines_parse_attached_units_and_unitless_items(self):
        response = self.add_recipe(
            "Soupe", "100g boeuf\n1 poire\n150ml lait\n1,5 kg farine"
        )

        self.assertEqual(response.status_code, 200)
        database = sqlite3.connect(self.app.config["DATABASE"])
        ingredients = database.execute(
            "SELECT name, unit, quantity FROM ingredients ORDER BY id"
        ).fetchall()
        database.close()
        self.assertEqual(
            ingredients,
            [
                ("boeuf", "g", "100"),
                ("poire", "", "1"),
                ("lait", "ml", "150"),
                ("farine", "kg", "1.5"),
            ],
        )

    def test_edit_form_shows_natural_ingredient_lines(self):
        self.add_recipe("Soupe", "100 | g | boeuf\n1 | | poire")
        response = self.client.get("/")
        page = response.data.decode()

        self.assertIn("100g boeuf\n1 poire", page)

    def test_editing_selected_recipe_refreshes_list_and_keeps_matching_checks(self):
        self.add_recipe("Soup", "2 | | carrots\n1 | tsp | salt")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()
        self.client.post("/plan", data={"recipe_ids": str(recipe_id)})

        database = sqlite3.connect(self.app.config["DATABASE"])
        carrot_id = database.execute(
            "SELECT id FROM shopping_items WHERE name = 'carrots'"
        ).fetchone()[0]
        database.close()
        self.client.post(f"/shopping/{carrot_id}/toggle")

        response = self.client.post(
            f"/recipes/{recipe_id}/edit",
            data={
                "name": "Big soup",
                "servings": "4",
                "ingredients": "4 | | carrots\n2 | | onions",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Big soup", response.data)
        self.assertIn(b"4 servings", response.data)
        self.assertNotIn(b'class="panel shopping-panel"', response.data)
        response = self.client.get("/?show_list=1")
        self.assertIn(b'class="item-name">carrots</span>', response.data)
        self.assertIn(b'<span class="item-quantity">4</span>', response.data)
        self.assertIn(b'class="item-name">onions</span>', response.data)
        self.assertIn(b'<span class="item-quantity">2</span>', response.data)
        self.assertIn(b"is-checked", response.data)
        self.assertNotIn(b">salt<", response.data)

    def test_invalid_recipe_edit_does_not_change_saved_recipe(self):
        self.add_recipe("Soup", "2 | | carrots")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()

        response = self.client.post(
            f"/recipes/{recipe_id}/edit",
            data={
                "name": "Changed soup",
                "servings": "4",
                "ingredients": "0 | | carrots",
            },
            follow_redirects=True,
        )

        self.assertIn(b"needs a quantity greater than zero", response.data)
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe = database.execute(
            "SELECT name, servings FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        ingredient = database.execute(
            "SELECT name, quantity FROM ingredients WHERE recipe_id = ?", (recipe_id,)
        ).fetchone()
        database.close()
        self.assertEqual(recipe, ("Soup", 2))
        self.assertEqual(ingredient, ("carrots", "2"))

    def test_deleting_selected_recipe_refreshes_plan_and_preserves_shared_checks(self):
        self.add_recipe("Soup", "2 | | carrots\n1 | | onions")
        self.add_recipe("Salad", "1 | | carrots\n3 | | tomatoes")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_ids = database.execute(
            "SELECT id FROM recipes ORDER BY id"
        ).fetchall()
        database.close()
        soup_id, salad_id = (row[0] for row in recipe_ids)
        self.client.post(
            "/plan",
            data={"recipe_ids": [str(soup_id), str(salad_id)]},
        )

        database = sqlite3.connect(self.app.config["DATABASE"])
        carrot_id = database.execute(
            "SELECT id FROM shopping_items WHERE name = 'carrots'"
        ).fetchone()[0]
        onion_id = database.execute(
            "SELECT id FROM shopping_items WHERE name = 'onions'"
        ).fetchone()[0]
        database.close()
        self.client.post(f"/shopping/{carrot_id}/toggle")
        self.client.post(f"/shopping/{onion_id}/toggle")

        response = self.client.post(
            f"/recipes/{soup_id}/delete", follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Deleted Soup.", response.data)
        self.assertNotIn(b">Soup<", response.data)
        self.assertIn(b">Salad<", response.data)
        self.assertNotIn(b'class="panel shopping-panel"', response.data)
        response = self.client.get("/?show_list=1")
        self.assertIn(b'class="item-name">carrots</span>', response.data)
        self.assertIn(b'<span class="item-quantity">1</span>', response.data)
        self.assertIn(b">tomatoes</span>", response.data)
        self.assertNotIn(b">onions</span>", response.data)
        self.assertEqual(response.data.count(b"is-checked"), 1)

        database = sqlite3.connect(self.app.config["DATABASE"])
        self.assertEqual(
            database.execute(
                "SELECT COUNT(*) FROM weekly_plan WHERE recipe_id = ?", (soup_id,)
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            database.execute(
                "SELECT COUNT(*) FROM ingredients WHERE recipe_id = ?", (soup_id,)
            ).fetchone()[0],
            0,
        )
        database.close()

    def test_deleting_missing_recipe_returns_not_found(self):
        response = self.client.post("/recipes/999/delete")

        self.assertEqual(response.status_code, 404)

    def test_recipe_forms_show_french_ingredient_choices_with_icons(self):
        self.add_recipe("Soup", "2 | | carrots")
        response = self.client.get("/")

        self.assertIn(b'aria-label="Viandes"', response.data)
        self.assertIn(b'aria-label="L\xc3\xa9gumes"', response.data)
        self.assertIn(b'aria-label="Fruits"', response.data)
        self.assertIn(b'aria-label="Produits laitiers et \xc5\x93ufs"', response.data)
        self.assertIn(b'aria-label="F\xc3\xa9culents et c\xc3\xa9r\xc3\xa9ales"', response.data)
        self.assertNotIn(b'aria-label="Cuisine fran\xc3\xa7aise"', response.data)
        self.assertNotIn(b'aria-label="Cuisine italienne"', response.data)
        self.assertIn(b'data-ingredient="moutarde de Dijon"', response.data)
        self.assertIn(b'data-ingredient="Parmigiano Reggiano"', response.data)
        page = response.data.decode()
        self.assertRegex(
            page,
            r'data-ingredient="carotte"\s+data-quantity="100"\s+data-unit="g"',
        )
        self.assertRegex(
            page,
            r'data-ingredient="bœuf"\s+data-quantity="100"\s+data-unit="g"',
        )
        self.assertRegex(
            page,
            r'data-ingredient="citron"\s+data-quantity="100"\s+data-unit="g"',
        )
        self.assertRegex(
            page,
            r'data-ingredient="moutarde de Dijon"\s+data-quantity="1"\s+data-unit=""',
        )
        self.assertIn("🥕".encode(), response.data)
        self.assertIn("Rechercher un ingrédient".encode(), response.data)
        self.assertEqual(
            response.data.count(b'class="common-ingredient-search"'), 2
        )

    def test_french_picker_ingredient_can_be_saved_to_shopping_list(self):
        response = self.add_recipe("Pâtes", "250 | g | tomates cerises")
        self.assertIn(b"P\xc3\xa2tes", response.data)
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()

        response = self.client.post(
            "/plan", data={"recipe_ids": str(recipe_id)}, follow_redirects=True
        )

        self.assertIn('tomates cerises'.encode(), response.data)
        self.assertIn(b'<span class="item-quantity">250 g</span>', response.data)

    def test_selected_meat_fruit_and_vegetable_entries_use_100g_default(self):
        response = self.add_recipe(
            "Poêlée", "100 | g | carottes\n100 | g | poulet\n100 | g | citron"
        )
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute("SELECT id FROM recipes").fetchone()[0]
        database.close()
        response = self.client.post(
            "/plan", data={"recipe_ids": str(recipe_id)}, follow_redirects=True
        )

        self.assertIn(b'<span class="item-quantity">100 g</span>', response.data)
        self.assertEqual(response.data.count(b'<span class="item-quantity">100 g</span>'), 3)

    def test_created_ingredient_is_saved_with_defaults_and_image(self):
        response = self.client.post(
            "/ingredients",
            data={
                "name": "Patate douce",
                "category": "Légumes",
                "default_quantity": "250",
                "default_unit": "g",
                "image": (BytesIO(b"\x89PNG\r\n\x1a\nimage-data"), "sweet-potato.png"),
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.data.decode(),
            r'data-ingredient="Patate douce"\s+data-quantity="250"\s+data-unit="g"',
        )
        self.assertIn(b'class="ingredient-image"', response.data)

        database = sqlite3.connect(self.app.config["DATABASE"])
        ingredient = database.execute(
            """
            SELECT default_quantity, default_unit, icon, image_data, image_mimetype
            FROM ingredient_catalog WHERE name = ?
            """,
            ("Patate douce",),
        ).fetchone()
        ingredient_id = database.execute(
            "SELECT id FROM ingredient_catalog WHERE name = ?", ("Patate douce",)
        ).fetchone()[0]
        database.close()
        self.assertEqual(
            ingredient,
            ("250", "g", "🥕", b"\x89PNG\r\n\x1a\nimage-data", "image/png"),
        )

        image_response = self.client.get(f"/ingredients/{ingredient_id}/image")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/png")
        self.assertEqual(image_response.data, b"\x89PNG\r\n\x1a\nimage-data")
        self.assertEqual(image_response.headers["X-Content-Type-Options"], "nosniff")

    def test_existing_catalog_ingredients_get_relevant_icons(self):
        self.add_recipe(
            "Icon check",
            "1 cumin\n1 gingembre\n1 brocolis\n1 dinde\n1 lait de coco",
        )
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": self.app.config["DATABASE"],
            }
        )
        self.client = self.app.test_client()

        database = sqlite3.connect(self.app.config["DATABASE"])
        icons = dict(
            database.execute(
                """
                SELECT name, icon FROM ingredient_catalog
                WHERE name IN (
                    'cumin', 'gingembre', 'brocolis', 'dinde', 'lait de coco',
                    'Parmigiano Reggiano'
                )
                """
            )
        )
        database.close()

        self.assertEqual(
            icons,
            {
                "brocolis": "🥦",
                "cumin": "🧂",
                "dinde": "🦃",
                "gingembre": "🫚",
                "lait de coco": "🥥",
                "Parmigiano Reggiano": "🧀",
            },
        )

    def test_ingredient_form_suggests_existing_categories_and_default_units(self):
        response = self.client.get("/")
        page = response.data.decode()

        self.assertIn('list="ingredient-category-options"', page)
        self.assertIn('list="ingredient-unit-options"', page)
        self.assertIn('<option value="Légumes">', page)
        self.assertIn('<option value="g">', page)

        self.client.post(
            "/ingredients",
            data={
                "name": "Nouvel ingrédient",
                "category": "Épices",
                "default_quantity": "1",
                "default_unit": "pincée",
            },
        )
        page = self.client.get("/").data.decode()
        self.assertIn('<option value="Épices">', page)
        self.assertIn('<option value="pincée">', page)

    def test_existing_recipe_ingredients_get_categories_when_catalog_is_refreshed(self):
        self.add_recipe("Spices", "1 cumin\n1 carottes")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute(
            "SELECT id FROM recipes WHERE name = 'Spices'"
        ).fetchone()[0]
        database.execute(
            "UPDATE ingredient_catalog SET category = 'Others' WHERE name = 'carotte'"
        )
        database.commit()
        database.close()

        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": self.app.config["DATABASE"],
            }
        )
        self.client = self.app.test_client()

        database = sqlite3.connect(self.app.config["DATABASE"])
        categories = dict(
            database.execute(
                """
                SELECT name, category FROM ingredient_catalog
                WHERE name IN ('cumin', 'carotte')
                """
            )
        )
        database.close()
        self.assertEqual(categories, {"carotte": "Légumes", "cumin": "Condiments et huiles"})

        response = self.client.post(
            "/plan", data={"recipe_ids": str(recipe_id)}
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/?show_list=1&sort=category")
        self.assertIn(b">L\xc3\xa9gumes</h3>", response.data)
        self.assertIn(b">Condiments et huiles</h3>", response.data)

    def test_singular_plural_ingredients_are_canonicalized_and_combined(self):
        response = self.add_recipe(
            "Onion dish", "2 oignons\n1 oignon\n100g carottes\n50g carotte"
        )
        self.assertEqual(response.status_code, 200)

        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_id = database.execute(
            "SELECT id FROM recipes WHERE name = 'Onion dish'"
        ).fetchone()[0]
        ingredients = database.execute(
            """
            SELECT name, unit, quantity FROM ingredients
            WHERE recipe_id = ? ORDER BY id
            """,
            (recipe_id,),
        ).fetchall()
        database.close()
        self.assertEqual(
            ingredients,
            [("oignon", "", "3"), ("carotte", "g", "150")],
        )

    def test_same_ingredient_in_different_recipes_remains_and_combines_on_list(self):
        self.add_recipe("First chicken recipe", "300g poulet")
        self.add_recipe("Second chicken recipe", "200g poulet")
        database = sqlite3.connect(self.app.config["DATABASE"])
        recipe_ids = [
            row[0] for row in database.execute("SELECT id FROM recipes ORDER BY id")
        ]
        database.close()

        response = self.client.post(
            "/plan",
            data={"recipe_ids": [str(recipe_id) for recipe_id in recipe_ids]},
            follow_redirects=True,
        )

        self.assertEqual(response.data.count(b'class="item-name">poulet</span>'), 1)
        self.assertIn(b'<span class="item-quantity">500 g</span>', response.data)

    def test_startup_migration_removes_duplicate_catalog_aliases(self):
        database = sqlite3.connect(self.app.config["DATABASE"])
        database.execute(
            """
            INSERT INTO ingredient_catalog
                (name, name_key, category, default_quantity, default_unit)
            VALUES ('oignon', 'oignon', 'Légumes', '1', '')
            """
        )
        database.execute(
            """
            INSERT INTO recipes (name, servings)
            VALUES ('Legacy onions', 2)
            """
        )
        recipe_id = database.execute(
            "SELECT id FROM recipes WHERE name = 'Legacy onions'"
        ).fetchone()[0]
        database.executemany(
            """
            INSERT INTO ingredients (recipe_id, name, unit, quantity)
            VALUES (?, ?, '', ?)
            """,
            [
                (recipe_id, "oignon", "2"),
                (recipe_id, "oignons", "3"),
            ],
        )
        database.commit()
        database.close()

        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": self.app.config["DATABASE"],
            }
        )

        database = sqlite3.connect(self.app.config["DATABASE"])
        catalog_names = database.execute(
            """
            SELECT name FROM ingredient_catalog
            WHERE name_key IN ('oignon', 'oignons')
            """
        ).fetchall()
        ingredients = database.execute(
            "SELECT name, quantity FROM ingredients WHERE recipe_id = ?",
            (recipe_id,),
        ).fetchall()
        database.close()
        self.assertEqual(catalog_names, [("oignon",)])
        self.assertEqual(ingredients, [("oignon", "5")])

    def test_ingredient_creation_rejects_invalid_image_and_duplicate_name(self):
        response = self.client.post(
            "/ingredients",
            data={
                "name": "Patate douce",
                "category": "Légumes",
                "default_quantity": "1",
                "image": (BytesIO(b"not an image"), "invalid.png"),
            },
            follow_redirects=True,
        )
        self.assertIn(b"Upload a PNG, JPEG, GIF, or WebP image", response.data)

        response = self.client.post(
            "/ingredients",
            data={
                "name": "Patate douce",
                "category": "Légumes",
                "default_quantity": "1",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Added Patate douce to your ingredient library.", response.data)

        response = self.client.post(
            "/ingredients",
            data={
                "name": "PATATE DOUCE",
                "category": "Légumes",
                "default_quantity": "1",
            },
            follow_redirects=True,
        )
        self.assertIn(b"An ingredient with that name already exists.", response.data)


if __name__ == "__main__":
    unittest.main()
