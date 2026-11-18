# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone (`judge_tone_public.csv`) | 100 | 0.757 | 0.857 | 0.800 | Có | Dùng có điều kiện cho tone; không chấm tiền/approval |
| helpful (`judge_helpful_public.csv`) | 100 | 0.375 | 1.000 | 0.300 | Không | Không dùng làm gate |

| Tiêu chí | Fail rate quan sát | Fail rate hiệu chỉnh (Rogan-Gladen) | Ma trận nhầm lẫn |
|---|---:|---:|---|
| tone | 0.280 | 0.300 | TP=24, FP=4, FN=6, TN=66 |
| helpful | 0.090 | 0.300 | TP=9, FP=0, FN=21, TN=70 |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / hành động |
|---|---|---|---|---|---|
| 1 | tone H-008 | PASS | FAIL | Người | Judge bỏ sót xưng `em`/từ `nha` quá suồng sã; thêm ví dụ về ngôi xưng và mức thân mật vào rubric. |
| 2 | tone H-029 | PASS | FAIL | Người | Judge bỏ sót câu mang tính ra lệnh `không cần nhắn thêm`; bổ sung tiêu chí giọng áp đặt. |
| 3 | tone H-042 | FAIL | PASS | Người | Câu trả lời ngắn nhưng đủ ý; không bắt buộc phải xin lỗi trong mọi phản hồi. |
| 4 | tone H-051 | FAIL | PASS | Người | `refund` là từ được CS cho phép; thêm vào danh sách từ chấp nhận thay vì phạt tiếng Anh máy móc. |
| 5 | tone H-081 | FAIL | PASS | Judge (theo ghi chú CSV) | Ghi chú cho biết người gán nhãn đọc nhầm ticket; cần rà soát và sửa nhãn người trước khi dùng lại làm gold label. |
| 6 | helpful HL-015 | PASS | FAIL | Người | Reply báo 55.000đ nhưng ledger 40.000đ. Judge chỉ thấy reply, không biết ledger; tiền phải do code grader so sánh. |

## Kết luận
- `tone` đạt cả ba floor trên replay này; chỉ dùng hỗ trợ chấm tone, kèm audit định kỳ. Không dùng judge để chấm số tiền hoặc approval.
- `helpful` bị loại: κ=0.375 và recall=0.300 thấp hơn floor. Judge bỏ sót 21/30 lỗi người gán nhãn, đặc biệt các reply lịch sự nhưng báo sai số tiền; không dùng làm gate.
- Fail rate helpful quan sát là 0.090 nhưng hiệu chỉnh thành 0.300, cho thấy trung bình thô đánh giá thấp tỷ lệ lỗi.
- Rủi ro còn lại: đây là dữ liệu replay công khai, không phải held-out độc lập; cần thêm nhãn người mới để kiểm tra khả năng khái quát.
