# Format `.hwt` (Huawei LiteOS, écran `HWHD13` = 408×480)

Ce format a été rétro-conçu à partir de deux cadrans : *iGMIXNUMB.FIT_eng* (v2.7.1) et *Snoopy.Sunset* (v2.3.1).

## Archive ZIP

| Entrée | Contenu |
|---|---|
| `com.huawei.watchface` | Binaire du cadran (voir ci-dessous) |
| `description.xml` | `<HwTheme>` : title, title-cn, author, designer, screen (`HWHD13`), version, font… |
| `preview/cover.jpg` | Aperçu 816×960 (2× l'écran) |
| `preview/aod.jpg` | Aperçu de l'affichage permanent (facultatif) |
| `preview/icon_small.jpg` | Aperçu 331×390 |

## Binaire `com.huawei.watchface` (petit-boutiste)

```
0   u16  version (=2)
2   u16  L : taille du layout
4   u32  T : taille de la table d'images (8 octets par image)
8   u32  S : taille du bloc de données
12  4 o  réservé (0)
16  L    layout (Protobuf)
..  T    table : (u32 offset, u32 taille) pour chaque image, offset relatif au bloc de données
..  S    données : 8 octets de préfixe (contenu variable : "a#P91@s+", "UUUU\1\0\0\1"…), puis les images
```

L'image n° k de la table s'appelle `"%03d" % k` dans le layout (première image = `"001"`). Une entrée de taille 0 est une image vide.

### Image

```
45 23 88 88 | u16 largeur | u16 hauteur | mots u32 (pixels BGRA, alpha non prémultiplié)
```

Les pixels sont compressés en RLE. Le mot `0x23456789` est suivi du pixel puis du nombre de répétitions. Les séries de 4 pixels identiques ou plus sont compressées, les plus courtes restent en clair.

Images habituelles :
- `001` : miniature 228×269
- `002` : souvent l'image de fond 408×480

### Layout (Protobuf, sans schéma officiel)

Les entiers négatifs sont codés en int32 sur 5 octets.

```
Watchface { repeated Group groups=1; string title=2; string title_cn=3; }
Group     { int type=1;  // 0 fond, 1 heure, 2 date, 3 widgets
            int f2=2; string background=4; repeated Element elements=5; repeated Widget widgets=8; }
Element   { int index=1; int kind=2;   // 1 image, 2 liste d'images, 3 nombre
            ImageElem image=4; ImageList image_list=5; NumberElem number=6; }
ImageElem { string image=1; Pos pos=2; int f5=5; }
ImageList { repeated string images=1; Pos pos=2; int data=3; int aod=6; }  // images[valeur]
NumberElem{ repeated string digits=1 (0..9); bytes f2=2; Pos pos=3; int f4=4; int f5=5; ... }
Widget    { int index=1; int f2=2; Rect rect=5 (zone tactile); repeated Element options=6; int widget_type=8; }
Pos { x=1; y=2 }   Rect { x=1; y=2; w=3; h=4 }
```

Codes `data` observés :

| Code | Donnée | Images |
|---|---|---|
| 59 / 60 | dizaine / unité de l'heure | 3 / 10 |
| 61 / 62 | dizaine / unité des minutes | 6 / 10 |
| 70 / 71 | dizaine / unité du jour | 4 / 10 |
| 41 / 42 | dizaine / unité du mois | 2 / 10 |
| 52 | jour de la semaine | 8 (index 0 inutilisé, 1 = lundi … 7 = dimanche) |
| 72 | indicateur (point rouge, probablement Bluetooth ou notification) | 2 |

`aod=1` signifie que l'élément ne s'affiche qu'en mode Always-On Display.

Valeurs de `widget_type` observées : 17 (batterie, `NumberElem.f5=9`), 10 (pas), 18 (indicateur). Leur sens reste à confirmer.

## Inconnues

- Le préfixe de 8 octets du bloc de données varie d'un fichier à l'autre et n'est ni un MD5, ni un SHA, ni un CRC des données. Il est conservé tel quel ; on ne sait pas encore si la montre le vérifie.
- Les champs `f*` n'ont pas encore de sens connu.
