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
| sun-square | 0.0341 / 39.7 | 0.0341 / 39.7 | 0.0341 / 39.7 | 0.00 | +0% | +0% | 0.0341 |

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
| sun-square | 0.1380 / 17.6 | 0.1380 / 17.6 | 0.1380 / 17.6 | 0.00 | +0% | +0% | 0.1380 |

## Summary

| backend | images | auto dominates | auto lower error | auto simpler at same error | simpler within 5% | tie | hand-tuned better | a sweep candidate beat hand-tuned |
|---|---|---|---|---|---|---|---|---|
| flo-mat | 9 | 1 | 0 | 7 | 6 | 0 | 1 | 4 |
| tegaki | 9 | 0 | 0 | 8 | 5 | 1 | 0 | 1 |
