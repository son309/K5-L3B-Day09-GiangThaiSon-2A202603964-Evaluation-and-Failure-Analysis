# Judge audit

Chạy offline bằng judge replay:

```powershell
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
```

`FAIL` là positive class vì nhiệm vụ của judge là tìm failure.

| Tiêu chí | n | κ | Precision | Recall | Confusion `tp/fp/fn/tn` | Đạt floors? | Quyết định |
|---|---:|---:|---:|---:|---|---|---|
| `tone_ok` | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | Có | Dùng có giám sát cho tone |
| `helpful` | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | Không | Loại khỏi release gate |

Tone judge quan sát failure rate 0.28; Rogan–Gladen hiệu chỉnh thành 0.30 sau khi
tính sensitivity=0.8 và specificity=66/70. Helpful judge quan sát 0.09 nhưng hiệu
chỉnh thành 0.30: chênh lệch này phản ánh 21 false negative và recall rất thấp.

## Audit bất đồng

| # | Case | Judge | Human | Ai đúng? | Hành động sửa rubric |
|---:|---|---|---|---|---|
| 1 | `H-008`: “Em ... nha, anh check giúp em.” | PASS | FAIL | Human | Ghi rõ xưng “em”, “anh” và tiểu từ “nha” là quá suồng sã trong ngữ cảnh CS chuẩn. |
| 2 | `H-029`: “... không cần nhắn thêm.” | PASS | FAIL | Human | Thêm ví dụ phản lệ: lời mở đầu lịch sự không bù được mệnh lệnh đóng hội thoại. |
| 3 | `H-042`: câu ngắn nhưng đủ trạng thái, tiền và thời gian | FAIL | PASS | Human | Nêu rõ lời xin lỗi là tùy ngữ cảnh, không phải điều kiện bắt buộc để tone đạt. |
| 4 | `H-051`: dùng từ “refund” trong câu tiếng Việt lịch sự | FAIL | PASS | Human | Cho phép thuật ngữ nghiệp vụ tiếng Anh đã được CS LogiX chấp nhận. |
| 5 | `H-063`: hứa “sẽ hoàn thêm” ngoài kết quả hệ thống | PASS | FAIL | Human | Thêm quy tắc cấm cam kết hành động/tương lai không được ledger hoặc workflow xác nhận. |
| 6 | `HL-015`: reply nói 55.000đ, ledger 40.000đ | PASS | FAIL | Human | Helpful rubric phải đối chiếu số tiền với ledger bằng code grader trước khi chấm văn phong. |
| 7 | `HL-043`: reply nói 35.000đ, ledger 20.000đ | PASS | FAIL | Human | Không cho lời xin lỗi dài che lỗi factual; bắt buộc kiểm tra amount/status trước. |
| 8 | `HL-047`: “Ok bạn ... rồi nhé.” | PASS | FAIL | Human | Thêm chuẩn xưng hô và yêu cầu nêu kết quả cụ thể, không chỉ nói “xử lý rồi”. |

## Kết luận

- `tone_ok` vượt cả ba floor κ≥0.6, P≥0.8, R≥0.7 nên có thể dùng cho tín
  hiệu tone, nhưng 10 bất đồng vẫn yêu cầu audit định kỳ và held-out mới.
- `helpful` bị loại khỏi gate: dù precision=1.0, recall=0.3 và κ=0.375 đều cho
  thấy judge bỏ lọt phần lớn reply sai. Một judge gần như chỉ báo lỗi khi rất chắc
  không bảo vệ được release.
- Tiền, approval, ledger và ownership phải dùng code grader. Judge replay chỉ
  phù hợp cho tiêu chí ngôn ngữ khó biểu diễn bằng rule.
- Bộ replay là dữ liệu công khai; kết quả có thể overfit. Trước khi dùng production
  cần nhãn người trên held-out mới, kiểm tra theo slice và tái hiệu chỉnh định kỳ.
