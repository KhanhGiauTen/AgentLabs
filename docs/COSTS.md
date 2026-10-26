# Đề xuất chi phí cho ngân sách 10–20 USD/tháng

Ngày kiểm tra nguồn: **26/10/2026**. Số tiền dưới đây là USD, chưa gồm VAT, phí nạp thẻ, chênh lệch tỷ giá, điện và khấu hao máy. Không giả định free credits còn mãi.

## Chọn cấu hình

Tôi đề xuất **mức trần ứng dụng $15/tháng**, dành khoảng **$5 cho pipeline thường, $5 cho những lượt cần đào sâu, $5 dự phòng**. GPU cloud = $0 trong cấu hình ban đầu; chỉ chạy CPU nhỏ hoặc benchmark dùng API. Không thể cam kết huấn luyện/fine-tune LLM quy mô lớn trong mức tiền này.

| Thành phần | Chi phí kế hoạch | Chính sách |
| --- | ---: | --- |
| UI + backend + SQLite + OpenClaw OSS | $0 tiền license phần mềm | Chạy trên máy hiện có |
| Crossref/arXiv | $0 phí API trong tích hợp hiện tại | Tuân thủ rate limit, không spam request |
| Free model | $0 tiền token nếu đúng biến thể free | Chọn model hỗ trợ tool calling, dừng khi quota hết |
| Model rẻ có phí | $1–4 dự kiến | Trích xuất, tổng hợp, code đầu tiên, viết draft |
| Model mạnh | $5–10 dự kiến | Chốt phương pháp, kiểm tra code khó, phản biện |
| Dự phòng API | $3–5 | Token dài, tool retries thủ công, sửa protocol |
| GPU cloud | $0 | Chưa nối và không thuê tự động |

Các mức này là phân bổ đề xuất, không phải cam kết số lượng paper.

## Giá đã kiểm tra

| Model | Input / 1M tokens | Output / 1M tokens | Vai trò đề xuất |
| --- | ---: | ---: | --- |
| GPT-6 Luna | $0.10 | $0.50 | Tác vụ thường |
| GPT-6.1 Sol | $2 | $10 | Methods, Reviewer |
| GPT-6 Astra | $10 | $50 | Chỉ cân nhắc cho vấn đề rất khó; chưa nằm trong routing tự động |
| Claude Sonnet 5.5 | $2 | $10 | Tùy chọn thay thế |
| Claude Opus 5.5 | $4 | $20 | Tùy chọn phản biện/coding; không phải default $15 |

Giá Standard short-context, không cache; không tính Batch/Flex giảm giá. Prompts rất dài, chế độ nhanh, cache writes và công cụ tính tiền riêng có thể thay đổi hóa đơn. App không bật công cụ web search/code interpreter có phí của provider. Nguồn: [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing).

## Tính toán minh bạch

Giả định **một workflow nhỏ** tiêu thụ tổng cộng:

- 8 vai trò thường: 300k input + 45k output ở Luna.
- 2 bước quan trọng (Methods và Chair): 40k input + 8k output ở Sol.

Đây là giả định lập kế hoạch, chưa phải số đo workload của bạn. Context nhiều tài liệu hoặc nhiều lượt tool sẽ khác đáng kể.

```text
Luna = 0.30 × 0.10 + 0.045 × 0.50 = $0.0525
Sol  = 0.04 × 2.00 + 0.008 × 10 = $0.160
Lean tổng                        = $0.2125/workflow
Hybrid nếu 8 vai trò thường free  = $0.160/workflow
```

| Workflows/tháng | Lean theo giả định | Hybrid theo giả định |
| ---: | ---: | ---: |
| 20 | $4.25 | $3.20 |
| 40 | $8.50 | $6.40 |
| 60 | $12.75 | $9.60 |

Không quy đổi thẳng số workflow thành số paper. Một đề tài có thể cần hàng chục vòng kiểm tra, chạy benchmark, sửa thiết kế và đọc lại tài liệu. API phục vụ benchmark là một chi phí khác ngoài 10 vai trò nếu bạn tự viết script gọi API; sandbox hiện không có network/key nên chưa phát sinh phần đó.

## Free credit và quota

OpenRouter hiện mô tả free models bị giới hạn 20 request/phút và 50 request/ngày; mức 1.000/ngày gắn với tài khoản đã mua ít nhất $10 credits. Không cần nạp $10 chỉ để thử lab; app tự đặt thêm ngưỡng 30 free requests/ngày UTC ở đường gọi OpenRouter trực tiếp. Một workflow 10 vai trò có tool roundtrip và submit_review có thể tốn hơn 10 requests. Vòng sửa lặp lại Writer, ba reviewer và Chair sẽ tăng thêm chi phí/quota. Không tạo tài khoản/key khác để vượt quota. Nguồn: [OpenRouter limits](https://openrouter.ai/docs/api-reference/limits), [OpenRouter pricing](https://openrouter.ai/pricing).

Chọn ID model free đang hiển thị trong tài khoản và hỗ trợ tool calling, đưa nguyên ID có hậu tố `:free` vào `.env`. Không hardcode một free model được cho là sẽ tồn tại lâu dài. Khi gặp 402/429, workflow giữ checkpoint và chờ bạn xử lý; không tự chuyển sang trả phí.

Gemini có Free Tier cho một số model và mức giới hạn phụ thuộc project/model/tier; Gemini 4 Argon không thuộc Free Tier. Free Tier và credit Cloud không luôn hoán đổi được cho nhau. Adapter Gemini native **chưa được triển khai trong bản này**; không giả vờ kết nối qua một ô cấu hình. Nguồn: [Google rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [Google pricing](https://ai.google.dev/gemini-api/docs/pricing), [Google billing](https://ai.google.dev/gemini-api/docs/billing).

Local model giảm tiền API nhưng cần RAM/GPU và điện, đồng thời chất lượng tool calling phải được thử trên chính máy. Ví dụ cấu hình là Qwen3 8B; chưa tự tải nhiều GB model hay xác nhận tốc độ. Nguồn model: [Qwen3 upstream](https://github.com/QwenLM/Qwen3).

## Vì sao vẫn có Lean nếu đã dùng OpenClaw?

OpenClaw hữu ích khi bạn muốn mở rộng memory, session, runtime và plugin về sau. Nhưng runtime có system prompt, session management và có thể có các model call nội bộ tùy cấu hình. Với ngân sách $15, đường **Lean trực tiếp** dễ đo số token và dự phòng hơn. Cùng một harness vẫn chạy được qua OpenClaw khi bạn chọn chế độ đó.

OpenResponses của OpenClaw mô tả `max_output_tokens` là best effort và một số trường như `max_tool_calls`/`reasoning` không được thực thi như giới hạn tuyệt đối. Vì vậy app giữ thêm dự phòng mặc định $0.10/call, không giải phóng thành con số hóa đơn chính xác cho lượt gateway, và đề xuất giới hạn mỗi lượt $2. Khoản dự phòng này có thể cao hơn tiền thật; đối chiếu provider để chỉnh. **Không gọi đây là hard cap tiền upstream.** Nguồn: [OpenClaw OpenResponses](https://docs.openclaw.ai/gateway/openresponses-http-api).

## Cơ chế kiểm soát đã có

1. Trước model call, reserve theo input bytes và output ceiling; transaction SQLite kiểm tra ngân sách lượt và tháng.
2. Sau call trực tiếp, ghi token usage và tính lại theo giá Standard; cache hit được tính như input thường để bảo thủ.
3. Timeout/cancel có thể vẫn bị provider tính phí, nên giữ reservation dưới trạng thái `uncertain`.
4. Tối đa 4 model turns/vai trò, 6 tool calls/turn, 1 workflow đang chạy tại một thời điểm.
5. Không tự retry, không tự nâng model, không tự thuê GPU.
6. Dashboard là chi phí của **ứng dụng này**; không nhìn thấy usage ở công cụ/tài khoản khác. Spending limit trên provider vẫn là lớp cần đặt.

Ngân sách tháng trong app dùng lịch UTC+7; quota free ngày ở đường OpenRouter trực tiếp dùng UTC. Khác biệt kỳ tính tiền này được ghi rõ để tránh hiểu nhầm ở thời điểm chuyển ngày/tháng.
