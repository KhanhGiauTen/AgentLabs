# Trạng thái kiểm thử và giới hạn

## Native OpenClaw V2 — 2026-10-27

- **77 Python tests + 22 native plugin tests passed**, không gọi API trả phí.
- Profile đã validate trên v2026.10.7 và bản native đang pin v2026.10.10-beta.3; host nạp `agentlabs-research` và 14 tools qua public SDK.
- 10.7 đã tái hiện checkpoint-expiry khiến nhiều agent unavailable sau restart, dù database integrity OK. Đã backup và chạy Doctor đúng runtime để migrate schema 25 → 27 cho pin beta chứa producer repair. Beta không được gọi là stable; chưa soak-test dài hạn. CLI `status` kiểm tra từng agent: **10/10 ready sau migration và sau restart**. Nguồn/giới hạn của bản sửa: [upstream #166634](https://github.com/openclaw/openclaw/issues/166634).
- Startup log thực tế xác nhận `lab-openai/gpt-6-luna`, đi qua proxy local. Config có metadata phiên bản để tránh recovery tự khôi phục route cũ.
- `scripts/verify_native.py` qua trên Gateway đã xác thực: phase/role assignment, từ chối Chair sớm, peer reports sealed, hai review nộp đồng thời merge qua CAS, Chair HOLD và HTTP không gọi được execution. Các session TEST được archive sau kiểm tra. Đây là operator tool integration, không phải LLM reasoning hay sessions_spawn.
- Budget tests gồm admission đồng thời, uncertainty qua restart, free quota, kỳ tháng, fragmented SSE/tool-call forwarding, thiếu key và chặn budget trước network. Repo tests gồm symlink escape, loại credentials/data, provenance dòng/hash và caller đã bị thu hồi.
- Native prompt hook chỉ mở tools điều phối cho yêu cầu nghiên cứu rõ hoặc continuation của project đã nhận. Chat thường đọc repo trực tiếp; không lấy ý định từ reconstructed history. `CHAT:` giữ lượt ở chat; `RESEARCH:` là override rõ.
- Profile bật `hooks.allowConversationAccess` cho plugin local để các hook chat được đăng ký; test cấu hình ngăn bỏ sót opt-in này. Task reviewer được dựng lại từ snapshot trong hook, loại peer text của Director; steering bị chặn.
- Chair có quyền HOLD độc lập ngay cả khi ba reviewer đều đồng ý. Thiếu verdict rõ ràng hoặc còn yêu cầu sửa/thực nghiệm/tài liệu giữ HOLD; test ngăn trạng thái ready xuất hiện khi revision còn chờ.
- UI dùng Control UI gốc, theme sáng và sidebar thu gọn. Có AI/ML welcome, Chat / Nghiên cứu, bốn gợi ý AI/ML và + Chat mới qua native sessions API; giữ phần nhập/gửi và transcript có nội dung của host. Đã build JS/CSS thành asset có hash, kiểm tra browser việc đổi chế độ giữ nháp, không tự submit, và tạo được native conversation trực tiếp. Preview: `native-ui.png`.
- Chưa có API key. Kiểm tra UI cuối xác nhận pre-run hook chặn trước model work và hiển thị hướng dẫn cấu hình `.env`; ledger native vẫn 0 calls / $0. Không có câu trả lời LLM thành công. Chưa chứng minh native spawn/yield, model/tool roundtrip hoặc approval UI với model thật. Docker engine đang tắt; chưa chạy container.
- Native dataset mounts, PDF/page spans, Git worktrees, research panels/export và LaTeX/PDF còn thiếu. Các chức năng V1 bên dưới không tự trở thành chức năng native.

```powershell
python -m pytest tests -q
cd native/plugin
npm ci --ignore-scripts
npm test
# Từ repository root, khi native Gateway đang chạy:
python scripts/verify_native.py
```

## Prototype V1 — bản ghi kiểm thử được giữ lại

Kiểm tra ngày 26/10/2026 trên Windows, Python 3.11, project/build ở `D:\ResearchLab`. Kết quả này chứng minh các contract phần mềm được liệt kê; không phải benchmark chất lượng nghiên cứu hay paper.

## Đã xác minh

- Backend khởi động và phục vụ UI/API tại `http://127.0.0.1:8765`.
- Kiểm tra UI bằng browser: workflow demo dừng ở điểm duyệt thực nghiệm; chọn skip đi đủ 10 vai trò, tạo bốn scorecard và hiển thị Review Chair ở trạng thái hold. Preview lưu tại `ui-review-board.png`.
- Kiểm tra chat UI bằng browser: hai tin nhắn thường không tạo run; yêu cầu thiết kế thực nghiệm tạo một run; mở lab thấy điểm duyệt, quay lại chat và gửi tiếp không tạo thêm run. Reload giữ lịch sử; ô nhập giữ dưới màn hình. Preview: `ui-chat-first.png`.
- Frontend production build thành công; còn cảnh báo không chặn build về directive `use client` của lucide-react trong ứng dụng React client.
- **63 tests passed** trong lần chạy cuối có thay đổi logic. Bộ test không dùng API trả phí hoặc Docker engine.
- Router phân biệt câu hỏi/đoạn trích với yêu cầu nghiên cứu rõ, hỗ trợ override và slash commands, không mất API call phân loại.
- Chat nhiều lượt được lưu; history gửi đúng user/assistant qua adapter OpenAI, OpenRouter, Anthropic và OpenClaw bằng MockTransport, dùng cheap route.
- Chat khi graph đang chạy không mở thêm lab; research run liên kết về hội thoại. Chat không được gọi endpoint resume/decision như research.
- Chat tuân thủ cap tháng trước network call; model không được stage code qua tool chat. Dừng, lỗi model và startup recovery giữ đúng trạng thái, không tự replay API.
- Copy dataset từ chat sang lab giữ nguyên byte gốc kể cả BOM/CRLF, cùng hash và manifest.
- LangGraph chạy đủ 10 vai trò ở demo, ba reviewer fan-out và Chair fan-in.
- Checkpoint được mở bằng graph/checkpointer mới rồi resume qua hai human gates.
- Sửa manuscript được giới hạn một vòng; route yêu cầu experiment mới phải qua rework gate rồi điểm duyệt mã mới.
- Reviewer không đọc được artifact review của peer qua tool/context; Chair chờ đủ ba báo cáo cùng snapshot.
- Scorecard từ chối evidence ID không đăng ký, hạ false readiness thành hold khi chưa có experiment hoặc vẫn còn blocking issue.
- Budget reservation dùng transaction và kiểm thử nhiều request đồng thời; vượt cap bị chặn trước call.
- Quota 429 không tự retry/fallback; timeout/unknown giữ reservation.
- Tool save code chỉ stage/syntax-check; thử nghiệm xác minh không thực thi code trên host.
- Hash mã khác bị chặn trước khi gọi Docker.
- PDF/text chunk giữ provenance; CSV giữ hash và path `/inputs`.
- Follow-up copy tài liệu/dataset vào run mới; export ZIP không chứa `.env`.
- Loopback Host/Origin và header mutation được kiểm tra.
- Adapters OpenAI function roundtrip, OpenClaw request contract và Claude auto-tool review roundtrip qua MockTransport.
- Crossref live trả 3 nguồn và DOI hợp lệ về cấu trúc cho query thử. Chưa xác minh các paper đó hỗ trợ claim nghiên cứu cụ thể.
- OpenClaw runtime `2026.10.7 (157d8c2)`; `config validate`, `gateway health` và authenticated `/v1/models` đã thành công. Source upstream không có tracked changes.

## Lệnh kiểm thử

```powershell
cd D:\ResearchLab\research-studio
$env:TEMP='D:\ResearchLab\work\tmp'
$env:TMP=$env:TEMP
D:\ResearchLab\work\.venv\Scripts\python.exe -m pytest tests -q
```

Lần kiểm tra đã chạy: **63 passed in 14.24s**. Temp/cache của lần chạy local đặt ở D; không cần sửa cấu hình thư mục Temp hệ thống.

## Chưa xác minh / chưa có

| Phần | Trạng thái |
| --- | --- |
| LLM suy luận thật với key của bạn | Chưa chạy, chưa có key; không khẳng định đã tạo research thật |
| Chat với model thật / token streaming | History/provider contract có mock tests; chưa gọi model thật, chưa stream từng token |
| OpenClaw engine thực hiện client tool roundtrip với provider thật | Contract adapter có test; engine chỉ mới được kiểm tra readiness/auth/model-list |
| Docker experiment | Docker CLI có, engine chưa chạy; chưa build image hay thực thi container |
| Sandbox runtime trên Docker/Windows volume thật | Chưa smoke-test; cần kiểm tra quyền user 65534 và mount sau khi bật engine |
| arXiv live API | Có adapter, chưa live-test trong lần chốt |
| PDF thực tế nhiều kiểu layout/scan | Parser/chunk pipeline đã có; chưa benchmark PDF layout/OCR, scan cần OCR ngoài |
| Citation support / novelty / thống kê | Cần nhà nghiên cứu đọc và kiểm tra; audit cấu trúc không xác nhận tính đúng |
| Chất lượng nhiều reviewer | Chưa được calibration trên benchmark; cùng model có thể cùng mắc lỗi |
| GPU/SSH/training dài/MLflow | Chưa tích hợp |
| OpenClaw compile từ monorepo source | Chưa chạy; đang dùng release package cùng tag/commit |
| Chạy 24/7 hoặc multi-user | Chưa soak-test, chưa có RBAC nhiều người |

## Những điều không nên suy ra

Health OK không chứng minh model account có quyền dùng model. Build/test xanh không chứng minh paper tốt. Ba review không chứng minh consensus đúng. Experiment exit code 0 không chứng minh metric đúng hoặc nghiên cứu có novelty. Budget hiển thị là ước tính và reservation trong ứng dụng; không phải hóa đơn và không bao phủ công cụ khác.

Để tiếp tục, dùng một bài toán pilot nhỏ có ground truth, chạy Lean hoặc Hybrid bằng key bạn cấp, đối chiếu artifacts và usage provider. Chỉ sau khi pilot đạt yêu cầu mới mở rộng thực nghiệm/hạ tầng.
