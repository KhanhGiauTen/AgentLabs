# Chat và điều phối Research Lab

AgentLabs mở ở **Trò chuyện**, không tự chạy workflow lúc mở app. Hội thoại gồm các cặp user/assistant lưu trong SQLite; chọn lịch sử trong sidebar để tiếp tục. Enter gửi, Shift+Enter xuống dòng. Câu trả lời model dùng API/endpoint do bạn cấu hình, không dùng subscription ChatGPT/Claude web.

## Cách chọn luồng

| Tin nhắn / lựa chọn | Hành vi |
| --- | --- |
| “Xin chào”, “Giải thích overfitting” | Chat trực tiếp |
| “Nghiên cứu này có ý nghĩa gì?”, “Thiết kế thực nghiệm là gì?” | Chat trực tiếp |
| “Hãy nghiên cứu các baseline RAG” | Tự động tạo research run |
| “Thiết kế thực nghiệm so sánh hai baseline, không dùng GPU” | Tự động tạo research run |
| Chọn Chỉ chat | Luôn chat, trừ slash command rõ ràng |
| `/research <nhiệm vụ>` hoặc chọn Research Lab | Tạo run, gắn thẻ Mở lab vào hội thoại |
| `/chat <nội dung>` | Chat bất kể selector |
| Câu chưa rõ hoặc tài liệu trích dẫn có chữ “nghiên cứu” | Giữ ở chat |

Router quy tắc chạy trên backend, chỉ xét tin nhắn hiện tại, không xét lịch sử/tài liệu/tool output để quyết định chạy lab. Không mất thêm API call phân loại. Đây không phải bộ hiểu intent tổng quát; slash command và selector xử lý trường hợp nhận diện chưa đúng. Ghi chú lab chỉ áp dụng cho lab. Lựa chọn Research Lab dùng cho một lượt rồi trở về Auto; Chỉ chat được lưu đến khi bạn đổi.

## Hội thoại và tài liệu

History được gửi bằng các message user/assistant riêng, không nối mọi câu hỏi vào một research topic. Với OpenAI, app quản lý history local và dùng `store:false`, theo cách manual history trong [official conversation-state guidance](https://developers.openai.com/api/docs/guides/conversation-state). Điều này không có nghĩa provider không có bất kỳ retention nào theo chính sách riêng của họ.

Model nhận các cặp lượt hoàn chỉnh gần nhất, tối đa 40 messages / khoảng 32.000 ký tự. Khi context bị cắt, UI báo rõ; lịch sử đầy đủ vẫn còn trong SQLite. Không có bộ nhớ vô hạn hoặc tự tóm tắt bằng model. Một hội thoại tối đa 500 lượt để giới hạn kích thước.

PDF/text, CSV/JSON dùng pipeline import hiện có. Chat chỉ có `read_artifact` và `search_documents`, không có execute, stage code hay submit review. Chưa có connector đọc thư mục repo local tùy ý. UI hiển thị câu trả lời khi API trả xong, chưa stream từng token.

Khi có run gần nhất, chat nhận snapshot giới hạn của các output và trạng thái hiện tại; không khẳng định đã đọc toàn bộ artifact hoặc tự xác minh kết quả. Trong lab có nút Quay lại hội thoại; run tạo trực tiếp có nút Chat về nghiên cứu này để tạo cuộc chat gắn snapshot.

## Chuyển sang nghiên cứu

Run có ID riêng và được theo dõi ở Research Lab. Tài liệu/dataset đã nhập được copy giữ nguyên byte/hash; có thể kế thừa run trước khi bật tùy chọn follow-up. Hội thoại tiếp tục được khi graph đang chạy. Hiện chỉ một graph nghiên cứu chạy cùng lúc; chat không dùng khóa này. Mỗi hội thoại chỉ có một phản hồi model đang chạy để tránh lệch thứ tự.

Các human gates của lab vẫn bắt buộc. Tin nhắn như “chạy code đi” trong chat không thay thế nút duyệt/hash tại lab. Nội dung model không có khả năng tự mở research run; chỉ endpoint nhận tin nhắn user định tuyến.

## Model, ngân sách và phục hồi

Chat dùng cheap route: Lean dùng Luna, Hybrid/Free dùng model OpenRouter free đã cấu hình, Claude dùng Sonnet, OpenClaw dùng cheap route của gateway, Local dùng endpoint local. Chat không gọi Methods/Chair. Research Lab vẫn chọn model mạnh cho hai vai trò đó.

Chat và lab dùng chung ledger/ngân sách tháng. Giới hạn trong tùy chọn áp dụng cho tổng chat của hội thoại và riêng từng workflow mới; UI hiển thị phần chat và lab ở từng màn hình tương ứng. Khi chạm cap, đổi giới hạn hoặc tạo hội thoại mới; cap tháng vẫn giữ. Không tự đổi provider hoặc fallback trả phí khi hết quota.

Dừng trả lời hủy tác vụ backend; provider có thể vẫn tính call đã gửi, reservation chưa rõ được giữ. Khi backend khởi động lại, phản hồi còn pending được đánh dấu interrupted, không tự gửi lại API. Lỗi có thông báo trong hội thoại; bạn quyết định gửi lại thủ công. Demo là nội dung theo kịch bản, không phải kiểm chứng khả năng suy luận hay memory của model thật.
