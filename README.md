# Weeknight grocery planner

A small Flask app for saving recipes, choosing what to cook this week, setting servings per recipe, and building a combined grocery list. Ingredient quantities scale to the selected servings; matching ingredient names and units are added together, and shopping items can be checked off.

## Run locally

1. Install Python 3.10 or newer.
2. In this folder, create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install Flask and start the app:

   ```powershell
   python -m pip install -r requirements.txt
   python app.py
   ```

4. Keep that terminal window open while you use the app, then open <http://127.0.0.1:5000>.

If the page does not load, make sure the `python app.py` command is still running in the terminal. The website is served from your computer and is available only while that process is running. Stop it with `Ctrl+C` when you are finished.

Recipes, the ingredient library (including uploaded images), and the weekly list are stored in `instance/groceries.sqlite3`.

## Add a recipe

Open **Add a recipe**, enter its name and serving count, then add one ingredient per line as a quantity followed by an optional unit and the ingredient name:

```text
100g boeuf
1 poire
150ml lait
```

Units can be written next to the quantity (`100g`) or after a space (`100 g`). Leave the unit out for counted items such as `1 poire`. Existing recipes and entries in the older `quantity | unit | ingredient` format remain supported.

Choose a recipe and set **Servings to cook** to adjust its ingredient quantities proportionally; it defaults to the recipe's serving count. The recipe workspace fills the page while you choose and create recipes. Click **Update my week** to display the shopping list; checking off an item keeps the list open. Use **Edit recipe** on a saved recipe to update its servings, ingredients, or name, or choose **Delete recipe** to remove it permanently. Deleting a recipe also removes it from the current week's plan and refreshes the shopping list; checked items remain checked when the ingredient and unit still match. Ingredients combine when both their names and units match (case-insensitively); different units are kept separate rather than converted.

Use the shopping list's **Order by** selector to group ingredients by name, recipe, or category. Items shared between recipes remain combined and appear under a heading listing those recipes. On startup, known ingredients in existing recipes are assigned categories from `data/recipe_ingredient_categories.json`; uncategorized ingredients not listed there appear under **Other**.

Recipe forms also include a searchable ingredient picker backed by the database. Existing starter ingredients are loaded once from `data/initial_ingredients.json` when the ingredient catalog is empty; ingredients you create are stored in SQLite. Relevant default icons are maintained in `data/ingredient_icons.json`, and uploaded images take precedence over icons. Use **Add an ingredient** to save an ingredient with its category, default quantity and optional unit, and optionally upload a PNG, JPEG, GIF, or WebP image up to 4 MB. The picker uses each ingredient's saved default quantity and unit. Adjust them to fit your recipe, or type any ingredient directly into the list. Common singular/plural aliases in `data/ingredient_aliases.json` are standardized, and repeated lines for the same ingredient and unit in a recipe have their quantities combined.

After updating your week, use **Share list** to send the shopping list through your phone's share menu where supported, or copy it to paste into a notes app. **Download .txt** saves a plain-text copy you can transfer to your phone. Both include quantities and checked-off items.

## Tests

```powershell
python -m unittest discover -s tests
```

This starter app is intended for local use and does not include user accounts or production deployment security.
