# Planificateur de courses de la semaine

Une petite application Flask pour enregistrer des recettes, choisir ce qu’on va cuisiner cette semaine, définir le nombre de portions par recette et générer une liste de courses combinée. Les quantités d’ingrédients sont mises à l’échelle selon les portions sélectionnées ; les noms et unités d’ingrédients correspondants sont additionnés, et les articles de courses peuvent être cochés.

## Exécuter localement

1. Installez Python 3.10 ou une version plus récente.
2. Dans ce dossier, créez et activez un environnement virtuel :

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Installez Flask et lancez l’application :

   ```powershell
   python -m pip install -r requirements.txt
   python app.py
   ```

4. Gardez cette fenêtre de terminal ouverte pendant que vous utilisez l’application, puis ouvrez <http://127.0.0.1:5000>.

Si la page ne se charge pas, vérifiez que la commande `python app.py` est toujours en cours d’exécution dans le terminal. Le site est servi depuis votre ordinateur et n’est disponible que pendant l’exécution de ce processus. Appuyez sur `Ctrl+C` pour l’arrêter lorsque vous avez terminé.

Les recettes, la bibliothèque d’ingrédients (y compris les images téléchargées) et la liste hebdomadaire sont stockées dans `instance/groceries.sqlite3`.

## Ajouter une recette

Ouvrez **Ajouter une recette**, entrez son nom et le nombre de portions, puis ajoutez un ingrédient par ligne sous la forme d’une quantité suivie d’une unité facultative et du nom de l’ingrédient :

```text
100g boeuf
1 poire
150ml lait
```

Les unités peuvent être écrites à côté de la quantité (`100g`) ou après un espace (`100 g`). Laissez l’unité de côté pour les éléments comptés comme `1 poire`. Les recettes existantes et les anciennes entrées au format `quantité | unité | ingrédient` restent prises en charge.

Choisissez une recette et réglez **Portions à préparer** pour ajuster proportionnellement les quantités d’ingrédients ; la valeur par défaut correspond au nombre de portions de la recette. L’espace de travail de la recette remplit la page pendant que vous choisissez et créez des recettes. Cliquez sur **Mettre à jour ma semaine** pour afficher la liste de courses ; cocher un élément garde la liste ouverte. Utilisez **Modifier la recette** sur une recette enregistrée pour mettre à jour ses portions, ses ingrédients ou son nom, ou choisissez **Supprimer la recette** pour la retirer définitivement. La suppression d’une recette supprime également cette recette du plan de la semaine en cours et actualise la liste de courses ; les éléments cochés restent cochés lorsque l’ingrédient et l’unité correspondent encore. Les ingrédients sont combinés lorsque leur nom et leur unité correspondent (sans tenir compte de la casse) ; les unités différentes sont conservées séparément plutôt que converties.

Utilisez le sélecteur **Trier par** de la liste de courses pour regrouper les ingrédients par nom, recette ou catégorie. Les éléments partagés entre plusieurs recettes restent combinés et apparaissent sous un titre listant ces recettes. Au démarrage, les ingrédients connus des recettes existantes se voient attribuer des catégories depuis `data/recipe_ingredient_categories.json` ; les ingrédients non catégorisés et absents de ce fichier apparaissent dans **Autre**.

Les formulaires de recettes incluent également un sélecteur d’ingrédients consultable et alimenté par la base de données. Les ingrédients de départ existants sont chargés une seule fois depuis `data/initial_ingredients.json` lorsque le catalogue d’ingrédients est vide ; les ingrédients que vous créez sont enregistrés dans SQLite. Les icônes par défaut pertinentes sont conservées dans `data/ingredient_icons.json`, et les images téléchargées ont priorité sur les icônes. Utilisez **Ajouter un ingrédient** pour enregistrer un ingrédient avec sa catégorie, sa quantité par défaut et son unité facultative, et éventuellement téléverser une image PNG, JPEG, GIF ou WebP d’une taille maximale de 4 Mo. Le sélecteur utilise la quantité et l’unité par défaut enregistrées pour chaque ingrédient. Ajustez-les pour votre recette, ou tapez directement n’importe quel ingrédient dans la liste. Les alias singulier/pluriel courants dans `data/ingredient_aliases.json` sont standardisés, et les lignes répétées pour le même ingrédient et la même unité dans une recette ont leurs quantités combinées.

Après avoir mis à jour votre semaine, utilisez **Partager la liste** pour envoyer la liste de courses via le menu de partage de votre téléphone lorsque la fonctionnalité est prise en charge, ou copiez-la pour la coller dans une application de notes. **Télécharger .txt** enregistre une copie en texte brut que vous pouvez transférer sur votre téléphone. Les deux incluent les quantités et les éléments cochés.

## Tests

```powershell
python -m unittest discover -s tests
```

Cette application de démarrage est destinée à un usage local et n’inclut ni comptes utilisateurs ni sécurité de déploiement en production.
