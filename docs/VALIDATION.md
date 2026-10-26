# Trạng thái kiểm thử và giới hạn

Kiểm tra ngày 26/10/2026 trên Windows, Python 3.11, project/build ở `D:\ResearchLab`. Kết quả này chứng minh các contract phần mềm được liệt kê; không phải benchmark chất lượng nghiên cứu hay paper.

## Đã xác minh

- Backend khởi động và phục vụ UI/API tại `http://127.0.0.1:8765`.
- Kiểm tra UI bằng browser: workflow demo dừng ở điểm duyệt thực nghiệm; chọn skip đi đủ 10 vai trò, tạo bốn scorecard và hiển thị Review Chair ở trạng thái hold. Preview lưu tại `ui-review-board.png`.
- Frontend production build thành công; còn cảnh báo không chặn build về directive `use client` của lucide-react trong ứng dụng React client.
- **22 tests passed** trong lần chạy cuối có thay đổi logic. Bộ test không dùng API trả phí hoặc Docker engine.
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
D:\ResearchLab\work\.venv\Scripts\python.exe -m pytest tests -q --basetemp D:\ResearchLab\work\pytest-run-05
```

Lần kiểm tra đã chạy: **22 passed in 12.10s**. Dùng thư mục basetemp tên mới nếu chạy lại; pytest quản lý/xóa nội dung basetemp theo hành vi của công cụ.

## Chưa xác minh / chưa có

| Phần | Trạng thái |
| --- | --- |
| LLM suy luận thật với key của bạn | Chưa chạy, chưa có key; không khẳng định đã tạo research thật |
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
