# Phase 4 Prep — Full MNIST Test-Set Accuracy

**Network**: 49→64→10 BinaryConnect, v4 preprocessing (strict `>` per-image median), trained weights from `data/bnn_weights.npz`.

## Headline Result

| Metric | Value |
|--------|-------|
| Test images | 10,000 |
| Correct | 7,112 |
| **Accuracy** | **71.12%** |
| 95% Wilson CI | [70.22%, 72.00%] |
| Phase-3D training log | 71.27% |
| Phase-3D 16-image batch | 81.25% (13/16) |

## Per-Class Accuracy

| Digit | Correct | Total | Accuracy |
|-------|---------|-------|----------|
| 0 | 804 | 980 | 82.0% |
| 1 | 1040 | 1135 | 91.6% |
| 2 | 766 | 1032 | 74.2% |
| 3 | 685 | 1010 | 67.8% |
| 4 | 648 | 982 | 66.0% |
| 5 | 541 | 892 | 60.7% |
| 6 | 802 | 958 | 83.7% |
| 7 | 693 | 1028 | 67.4% |
| 8 | 525 | 974 | 53.9% |
| 9 | 608 | 1009 | 60.3% |

## Confusion Matrix

Rows = true class, columns = predicted class.

| True \ Pred | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| **0** | 804 | 1 | 50 | 22 | 18 | 21 | 28 | 14 | 20 | 2 |
| **1** | 0 | 1040 | 17 | 21 | 9 | 15 | 7 | 6 | 11 | 9 |
| **2** | 31 | 12 | 766 | 73 | 31 | 33 | 42 | 12 | 26 | 6 |
| **3** | 18 | 4 | 119 | 685 | 1 | 66 | 14 | 23 | 58 | 22 |
| **4** | 23 | 3 | 21 | 3 | 648 | 17 | 9 | 25 | 35 | 198 |
| **5** | 23 | 9 | 45 | 116 | 26 | 541 | 22 | 10 | 84 | 16 |
| **6** | 31 | 3 | 61 | 2 | 9 | 47 | 802 | 1 | 2 | 0 |
| **7** | 9 | 22 | 19 | 38 | 74 | 9 | 2 | 693 | 38 | 124 |
| **8** | 57 | 13 | 66 | 97 | 47 | 89 | 16 | 23 | 525 | 41 |
| **9** | 26 | 5 | 7 | 25 | 168 | 11 | 1 | 81 | 77 | 608 |

## Sanity Check

Expected range: 60%–80% (based on training-time test_acc 71.27% and typical BinaryConnect ±5 pp variance).

Result 71.12% is **within** the expected range.

*Eval time: 0.6s on CPU.*
