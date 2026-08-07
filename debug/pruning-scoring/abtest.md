# Automatic pruning vs hand-tuned pruning — controlled A/B

Generated 2026-08-07 18:01:32 · selection tolerance 5%

Same backend, same everything upstream; only the pruning stage differs. `err` is symmetric difference / source ink area. `cx` is a complexity index (branches + control points / 100). Automatic pruning starts from the **unpruned** graph.


## flo-mat

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | auto λ | verdict |
|---|---|---|---|---|---|
| house-wide | 0.0563 / 285.0 | 0.0553 / 305.6 | 0.0588 / 44.0 | 0.00 | hand-tuned-better |
| butterfly-wide | 0.1020 / 348.9 | 0.1023 / 350.0 | 0.1163 / 32.8 | 1.25 | hand-tuned-better |
| boat-tall | 0.0755 / 367.2 | 0.0752 / 380.6 | 0.0797 / 40.0 | 0.75 | hand-tuned-better |
| island-tall | 0.0634 / 446.3 | 0.0628 / 469.0 | 0.0712 / 53.2 | 2.50 | hand-tuned-better |
| balloon-tall | 0.0962 / 426.0 | 0.0958 / 442.5 | 0.1004 / 72.8 | 1.00 | auto-simpler-same-error |
| home-wide | 0.0555 / 431.8 | 0.0697 / 421.5 | 0.0604 / 96.8 | 0.00 | auto-dominates |
| house-tall | 0.0513 / 638.9 | 0.0516 / 652.3 | 0.0503 / 83.8 | 0.25 | auto-dominates |
| dinosaur-wide | 0.0540 / 476.2 | 0.0543 / 493.7 | 0.0657 / 72.1 | 0.75 | hand-tuned-better |
| landscape-square | 0.0669 / 742.6 | 0.0666 / 727.2 | 0.0811 / 201.2 | 0.50 | hand-tuned-better |
| sun-square | 0.0422 / 280.7 | 0.0422 / 280.7 | 0.0860 / 37.6 | 1.00 | hand-tuned-better |

**3/10 images: automatic pruning wins or ties favourably.**


## tegaki

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | auto λ | verdict |
|---|---|---|---|---|---|
| house-wide | 0.0492 / 29.7 | 0.0492 / 29.7 | 0.0564 / 27.7 | 0.00 | hand-tuned-better |
| butterfly-wide | 0.0637 / 21.9 | 0.0637 / 21.9 | 0.0668 / 20.9 | 4.00 | auto-simpler-same-error |
| boat-tall | 0.0543 / 31.1 | 0.0543 / 31.1 | 0.0543 / 30.1 | 0.00 | auto-simpler-same-error |
| island-tall | 0.0548 / 37.1 | 0.0548 / 37.1 | 0.0564 / 36.0 | 0.00 | auto-simpler-same-error |
| balloon-tall | 0.0627 / 52.2 | 0.0627 / 52.2 | 0.0644 / 48.2 | 2.50 | auto-simpler-same-error |
| home-wide | 0.0622 / 36.9 | 0.0622 / 36.9 | 0.0637 / 35.9 | 2.00 | auto-simpler-same-error |
| house-tall | 0.0618 / 43.2 | 0.0618 / 43.2 | 0.0622 / 41.1 | 2.50 | auto-simpler-same-error |
| dinosaur-wide | 0.0725 / 53.7 | 0.0725 / 53.7 | 0.0748 / 51.6 | 4.00 | auto-simpler-same-error |
| landscape-square | 0.1189 / 96.0 | 0.1189 / 96.0 | 0.1228 / 84.6 | 5.00 | auto-simpler-same-error |
| sun-square | 0.1380 / 17.6 | 0.1380 / 17.6 | 0.1380 / 17.6 | 0.00 | tie |

**8/10 images: automatic pruning wins or ties favourably.**


## polygon-voronoi

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | auto λ | verdict |
|---|---|---|---|---|---|
| house-wide | 0.1106 / 330.4 | 0.1142 / 120.5 | 0.1154 / 121.0 | 0.75 | tie |
| butterfly-wide | 0.0208 / 334.3 | 0.0309 / 122.3 | 0.0208 / 334.3 | 0.00 | auto-lower-error |
| boat-tall | 0.0774 / 325.4 | 0.0825 / 131.5 | 0.0811 / 144.4 | 0.50 | auto-lower-error |
| island-tall | 0.0740 / 392.3 | 0.0797 / 132.9 | 0.0740 / 392.3 | 0.00 | auto-lower-error |
| balloon-tall | 0.1004 / 403.7 | 0.1072 / 157.3 | 0.1023 / 216.8 | 0.25 | auto-lower-error |
| home-wide | 0.1164 / 343.1 | 0.1202 / 103.5 | 0.1214 / 141.7 | 0.50 | tie |
| house-tall | 0.0600 / 509.4 | 0.0654 / 157.0 | 0.0600 / 509.4 | 0.00 | auto-lower-error |
| dinosaur-wide | 0.0557 / 402.1 | 0.0569 / 212.4 | 0.0560 / 210.1 | 1.25 | auto-dominates |
| landscape-square | 0.0481 / 1148.7 | 0.0602 / 390.6 | 0.0481 / 1148.7 | 0.00 | auto-lower-error |
| sun-square | 0.0788 / 205.9 | 0.0806 / 65.7 | 0.0801 / 65.7 | 1.00 | auto-dominates |

**8/10 images: automatic pruning wins or ties favourably.**

