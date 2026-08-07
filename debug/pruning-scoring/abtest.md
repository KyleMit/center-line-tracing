# Automatic pruning vs hand-tuned pruning — controlled A/B

Same backend, same rasterization, same tracing; **only the pruning stage differs**. Automatic pruning always starts from that track's UNPRUNED graph.

* **err** — symmetric difference / source ink area (lower is better)
* **cx** — complexity index (branches + control points / 100), measured **after canonicalization on both sides** so the comparison is like for like
* **Δerr / Δcx** — automatic vs that track's own pruning
* **reachable** — the lowest error any candidate in the sweep achieved: what width-aware pruning could reach with a perfect selection rule


## flo-mat

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | λ | Δerr | Δcx | reachable |
|---|---|---|---|---|---|---|---|
| balloon-tall | 0.0919 / 89.0 | 0.0913 / 101.5 | 0.0938 / 72.8 | 1.00 | +3% | -28% | 0.0918 |
| boat-tall | 0.0727 / 47.2 | 0.0722 / 61.6 | 0.0743 / 40.0 | 0.75 | +3% | -35% | 0.0725 |
| butterfly-wide | 0.0989 / 42.9 | 0.0990 / 45.0 | 0.1024 / 32.8 | 1.25 | +3% | -27% | 0.0988 |
| dinosaur-wide | 0.0499 / 77.2 | 0.0501 / 94.7 | 0.0501 / 73.2 | 0.50 | +0% | -23% | 0.0498 |
| home-wide | 0.0498 / 96.8 | 0.0653 / 83.5 | 0.0498 / 96.8 | 0.00 | -24% | +16% | 0.0498 |
| house-tall | 0.0459 / 89.9 | 0.0458 / 100.3 | 0.0479 / 71.6 | 0.50 | +5% | -29% | 0.0458 |
| house-wide | 0.0516 / 44.0 | 0.0501 / 61.6 | 0.0540 / 42.0 | 1.50 | +8% | -32% | 0.0515 |
| island-tall | 0.0606 / 60.3 | 0.0600 / 75.0 | 0.0624 / 53.2 | 2.50 | +4% | -29% | 0.0605 |
| landscape-square | 0.0591 / 219.6 | 0.0589 / 201.2 | 0.0615 / 168.6 | 0.75 | +5% | -16% | 0.0591 |
| sun-square | 0.0341 / 39.7 | 0.0341 / 39.7 | 0.0341 / 39.7 | 0.00 | +0% | +0% | 0.0341 |

## polygon-voronoi

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | λ | Δerr | Δcx | reachable |
|---|---|---|---|---|---|---|---|
| balloon-tall | 0.0985 / 403.7 | 0.1070 / 157.3 | 0.1028 / 156.8 | 2.50 | -4% | -0% | 0.0981 |
| boat-tall | 0.0756 / 325.4 | 0.0845 / 131.5 | 0.0778 / 131.5 | 1.25 | -8% | +0% | 0.0752 |
| butterfly-wide | 0.0239 / 334.3 | 0.0271 / 122.3 | 0.0211 / 168.4 | 0.25 | -22% | +38% | 0.0211 |
| dinosaur-wide | 0.0404 / 402.1 | 0.0443 / 212.4 | 0.0397 / 210.1 | 1.25 | -10% | -1% | 0.0392 |
| home-wide | 0.1070 / 343.1 | 0.1139 / 103.5 | 0.1040 / 141.7 | 0.50 | -9% | +37% | 0.1040 |
| house-tall | 0.0569 / 509.4 | 0.0682 / 157.0 | 0.0582 / 156.0 | 1.00 | -15% | -1% | 0.0558 |
| house-wide | 0.1049 / 330.4 | 0.1091 / 120.5 | 0.1044 / 121.0 | 0.75 | -4% | +0% | 0.1037 |
| island-tall | 0.0690 / 392.3 | 0.0801 / 132.9 | 0.0720 / 124.4 | 5.00 | -10% | -6% | 0.0690 |
| landscape-square | 0.0168 / 1148.7 | 0.0348 / 390.6 | 0.0159 / 441.5 | 0.50 | -54% | +13% | 0.0156 |
| sun-square | 0.0150 / 205.9 | 0.0231 / 65.7 | 0.0118 / 67.8 | 0.50 | -49% | +3% | 0.0118 |

## tegaki

| image | unpruned err / cx | hand-tuned err / cx | auto err / cx | λ | Δerr | Δcx | reachable |
|---|---|---|---|---|---|---|---|
| balloon-tall | 0.0627 / 51.2 | 0.0627 / 51.2 | 0.0645 / 48.2 | 2.50 | +3% | -6% | 0.0627 |
| boat-tall | 0.0543 / 30.1 | 0.0543 / 30.1 | 0.0543 / 30.1 | 0.00 | +0% | +0% | 0.0543 |
| butterfly-wide | 0.0637 / 21.9 | 0.0637 / 21.9 | 0.0668 / 20.9 | 4.00 | +5% | -5% | 0.0637 |
| dinosaur-wide | 0.0725 / 52.7 | 0.0725 / 52.7 | 0.0747 / 51.6 | 4.00 | +3% | -2% | 0.0725 |
| home-wide | 0.0622 / 36.9 | 0.0622 / 36.9 | 0.0637 / 35.9 | 2.00 | +2% | -3% | 0.0622 |
| house-tall | 0.0618 / 43.2 | 0.0618 / 43.2 | 0.0622 / 41.1 | 2.50 | +1% | -5% | 0.0618 |
| house-wide | 0.0492 / 27.7 | 0.0492 / 27.7 | 0.0492 / 27.7 | 0.00 | +0% | +0% | 0.0492 |
| island-tall | 0.0548 / 36.1 | 0.0548 / 36.1 | 0.0548 / 36.1 | 0.00 | +0% | +0% | 0.0548 |
| landscape-square | 0.1189 / 94.0 | 0.1189 / 94.0 | 0.1222 / 84.6 | 5.00 | +3% | -10% | 0.1189 |
| sun-square | 0.1380 / 17.6 | 0.1380 / 17.6 | 0.1380 / 17.6 | 0.00 | +0% | +0% | 0.1380 |

## Summary

| backend | images | auto dominates | auto lower error | auto simpler at same error | simpler within 5% | tie | hand-tuned better | a sweep candidate beat hand-tuned |
|---|---|---|---|---|---|---|---|---|
| flo-mat | 10 | 1 | 0 | 8 | 7 | 0 | 1 | 4 |
| polygon-voronoi | 10 | 5 | 5 | 0 | 4 | 0 | 0 | 10 |
| tegaki | 10 | 0 | 0 | 9 | 6 | 1 | 0 | 1 |
