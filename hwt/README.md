# Cadrans Huawei `.hwt` (Watch Fit 4 Pro et montres LiteOS)

`hwt_tool.py` décompile et recompile les fichiers `.hwt`. Les deux exemples testés se reconstruisent à l'identique, octet pour octet.

```bash
pip install pillow

python3 hwt_tool.py unpack  cadran.hwt  mon_cadran/   # -> images/*.png, layout.json, manifest.json, description.xml, preview/
python3 hwt_tool.py render  mon_cadran/ apercu.png --time 19:08 --date 2025-09-28 [--aod]
python3 hwt_tool.py pack    mon_cadran/ nouveau.hwt
python3 hwt_tool.py verify  cadran.hwt                 # contrôle aller-retour
```

Pour créer un cadran, le plus simple est de partir d'un cadran décompilé :

1. Remplacer les PNG dans `images/` en gardant le même nom. La taille de chaque image peut changer.
2. Ajuster les positions dans `layout.json`.
3. Pour ajouter une image, ajouter son nom (par exemple `"059"`) à la fin de `manifest.json > images`, puis la référencer dans `layout.json`.
4. Mettre à jour `description.xml` (titre, auteur) et les aperçus `preview/*.jpg`.
5. Lancer `render` pour vérifier, puis `pack`.

Le format est décrit dans [FORMAT.md](FORMAT.md).
