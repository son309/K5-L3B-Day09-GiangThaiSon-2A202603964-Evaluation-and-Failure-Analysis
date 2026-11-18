# Trace case: reply sai số tiền ledger (FM-08)

Lệnh tái hiện:

```powershell
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-008 --seed 11
python -m lab9.trace_case --shape fixed --claim C-008 --seed 11
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-008@11`, run ID `R-seeded_regression-C-008-s11` |
| Triệu chứng | Lab 8 grader vẫn PASS vì status và ledger đúng, nhưng reply nói đã hoàn 35.000đ trong khi ledger chỉ ghi 20.000đ. |
| Bước sai đầu tiên | Event 5 `reply`: `{"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}`. |
| Vì sao là bước đầu tiên | Event 1 handoff đúng scope; event 2 thấy đúng order; event 3 quote đúng 35.000đ; event 4 chỉ đọc lịch sử refund=0. Host sau đó cap theo approval và ledger đúng 20.000đ. |
| Failure mode | `FM-08 misreport` |
| Đối chứng | `fixed C-008@11` có cùng quote 35.000đ và ledger 20.000đ, nhưng event 4 reply nói đúng 20.000đ. |
| Regression test | `test_reply_amount_must_match_ledger`: `ReplyAmountMatchesLedger` pass với reply 35.000đ/ledger 35.000đ và fail với reply 35.000đ/ledger 20.000đ. |
| Chưa chắc chắn | Trace chứng minh reply sai so với ledger, nhưng không chứng minh nguyên nhân nội bộ của model; grader chỉ dựa trên observable event. |

Đây là lý do FM-08 cần metric riêng `reply_amount_matches_ledger`: `pass_rate`
của Lab 8 không đọc reply nên trial lỗi trên vẫn có thể PASS.
