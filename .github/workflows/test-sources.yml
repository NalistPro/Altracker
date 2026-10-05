name: Test des sources

# Declenchement manuel uniquement (bouton "Run workflow")
on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Recuperer le depot
        uses: actions/checkout@v4

      - name: Installer Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Lancer le test des sources
        env:
          COINGECKO_KEY: ${{ secrets.COINGECKO_KEY }}
        run: python scripts/test_sources.py

      - name: Enregistrer les resultats dans le depot
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data
          git diff --staged --quiet || git commit -m "Lot 1 : rapport de connectivite et univers"
          git push
