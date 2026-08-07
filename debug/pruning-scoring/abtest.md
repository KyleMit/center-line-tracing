# Automatic pruning vs hand-tuned pruning — controlled A/B

Generated 2026-08-07 17:53:04 · selection tolerance 5%

Same backend, same everything upstream; only the pruning stage differs. `err` is symmetric difference / source ink area. `cx` is a complexity index (branches + control points / 100). Automatic pruning starts from the **unpruned** graph.


## flo-mat

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | auto λ | verdict |
|---|---|---|---|---|---|
| house-wide | 0.0563 / 285.0 | 0.0553 / 305.6 | 0.0588 / 44.0 | 0.00 | hand-tuned-better |
| butterfly-wide | 0.1020 / 348.9 | 0.1023 / 350.0 | 0.1163 / 32.8 | 1.25 | hand-tuned-better |

**0/2 images: automatic pruning wins or ties favourably.**


## tegaki

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | auto λ | verdict |
|---|---|---|---|---|---|
| house-wide | 0.0492 / 29.7 | 0.0492 / 29.7 | 0.0564 / 27.7 | 0.00 | hand-tuned-better |
| butterfly-wide | 0.0637 / 21.9 | 0.0637 / 21.9 | 0.0668 / 20.9 | 4.00 | auto-simpler-same-error |

**1/2 images: automatic pruning wins or ties favourably.**


## polygon-voronoi

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | auto λ | verdict |
|---|---|---|---|---|---|
| house-wide | 0.1106 / 330.4 | 0.1142 / 120.5 | 0.1154 / 121.0 | 0.75 | tie |
| butterfly-wide | 0.0208 / 334.3 | 0.0309 / 122.3 | 0.0208 / 334.3 | 0.00 | auto-lower-error |

**1/2 images: automatic pruning wins or ties favourably.**

