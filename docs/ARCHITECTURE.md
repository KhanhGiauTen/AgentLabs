# Thiết kế agentic research lab

Thiết kế ưu tiên **nghiên cứu có thể kiểm tra**, với nhiều reviewer và vòng phản hồi giống tinh thần AgentLaboratory. OpenClaw cung cấp runtime model tùy chọn; **harness nghiên cứu sở hữu luồng công việc, quyền tool, evidence và ngân sách**.

Source tham khảo đã clone tại `D:\ResearchLab\reference-agent-laboratory`, commit `d9017d90e329112d2a80b7712f37ee9094d2cd27`. OpenClaw source pin riêng; cấu hình upstream có một nguồn chính tại `upstreams.lock.json`. Không nhúng mã OpenClaude.

## Lớp hội thoại trước graph nghiên cứu

UI mặc định → endpoint conversation → router intent local → một assistant chat **hoặc** tạo research run có liên kết trong hội thoại. Router chỉ tự chuyển với yêu cầu nghiên cứu rõ; câu hỏi kiến thức/giải thích vẫn chat. Người dùng có selector và `/chat`, `/research` để điều khiển. Chi tiết: [CHAT.md](CHAT.md).

Chat dùng cheap model, transcript user/assistant và tools chỉ đọc tài liệu của hội thoại. Không có tool mở lab/duyệt code trong model; quyền tạo run thuộc endpoint xử lý tin nhắn người dùng. Transcript được lưu trong cùng SQLite với discriminator `kind=chat`, lọc khỏi danh sách research runs; endpoint resume/decision từ chối chat. Dữ liệu cũ không cần migration vì run không có kind tiếp tục được hiểu là research.

Chat tasks độc lập với khóa một graph đang chạy; budget reservation vẫn dùng chung transaction/ledger. Startup đánh dấu pending chat interrupted, không replay API có phí. Hội thoại và run giữ ID riêng; snapshot gần nhất hỗ trợ hỏi đáp, không thay thế evidence artifacts.

## Từ AgentLaboratory đến bản cải tiến

AgentLaboratory tổ chức literature review, plan formulation, data preparation, experiment, interpretation, report và refinement; trong mã có PhD/Postdoc/Professor/ML Engineer, solver cho code/paper và ba reviewer. Bản này giữ chu trình đó, nhưng tách trách nhiệm theo artifact thay vì chức danh học thuật. Nguồn: [README](https://github.com/SamuelSchmidgall/AgentLaboratory), [workflow ở commit đã clone](https://github.com/SamuelSchmidgall/AgentLaboratory/blob/d9017d90e329112d2a80b7712f37ee9094d2cd27/ai_lab_repo.py).

| Thiết kế | Áp dụng trong harness |
| --- | --- |
| Literature → experiment → report | Giữ nguyên trục nghiên cứu |
| Agent trao đổi theo vai trò | Context được chọn theo trách nhiệm; không broadcast toàn bộ transcript |
| Ba reviewer | Ba node fan-out riêng, báo cáo sealed, Chair fan-in |
| Quay lại kế hoạch sau review | Route có cấu trúc về Writer, Methods hoặc Literature |
| Solver có nhiều bước | Giới hạn 4 model turns/role, revision 0 hoặc 1, ngân sách từng call |
| Save/resume | LangGraph checkpoint SQLite, resume từ điểm lỗi/duyệt |
| Code do LLM sinh | Stage → xem code/hash → duyệt → Docker offline |
| Báo cáo cuối | Bản nháp + scorecards + audit, không tự nộp paper |

“Cải tiến” ở đây là kiểm soát luồng và khả năng kiểm tra. Chưa có benchmark chứng minh bản này tạo paper tốt hơn AgentLaboratory.

## Tổ chức: 6 agent tác vụ, 3 reviewer, 1 Chair

| Phòng / agent | Nhiệm vụ | Input chính | Bàn giao | Model Lean |
| --- | --- | --- | --- | --- |
| PI / Research Intake | Giới hạn câu hỏi, giả thuyết, tiêu chí dừng | Topic, notes, dữ liệu cung cấp | `intake.md` | Luna |
| Literature Researcher | Nguồn liên quan, evidence map, khoảng trống chưa xác minh | Brief, Crossref/arXiv, PDF/text | `literature.md`, `sources.json`, `references.bib` | Luna |
| Methods Scientist | Baseline, ablation, split, metric, seed, tiêu chí bác bỏ | Brief, evidence map, dataset manifest | `methods.md` | **Sol** |
| Research Engineer | Viết code thực nghiệm theo protocol | Methods, input paths, giới hạn CPU | `experiment.py`, giải thích triển khai | Luna |
| Data Analyst | Kiểm tra logs/metrics, hạn chế, uncertainty | Kết quả sandbox hiện tại | `analysis.md` | Luna |
| Scientific Writer | Viết và sửa manuscript từ evidence | Methods, analysis, nguồn và feedback | `manuscript.md`, bản theo vòng | Luna |
| R1: Novelty & Evidence | Novelty, đối chiếu related work, nguồn có hỗ trợ claim không | Cùng snapshot manuscript + evidence | `review_novelty.json/.md` | Luna |
| R2: Methods & Statistics | Leakage, baseline, seed, CI/effect size, ablation | Cùng snapshot và protocol/metrics | `review_methods.json/.md` | Luna |
| R3: Reproducibility | Code–data–metric lineage, dependency, tái lập | Script, dataset hash, logs, metrics | `review_repro.json/.md` | Luna |
| Review Chair | Tổng hợp, xử lý bất đồng, đề xuất route tiếp | Đủ ba scorecard + evidence | `review.json`, `board-decision.json` | **Sol** |

Data preparation trong bản nhỏ được chia cho Methods (thiết kế), Engineer (code) và manifest dataset do harness quản lý. Chưa tách thêm agent chỉ để tăng số lượng.

R1/R2/R3 dùng ba lượt suy luận khác nhau. Trong Lean, chúng vẫn dùng cùng một họ model nên lỗi có thể tương quan. **Context độc lập không tương đương độc lập thống kê hay chuyên gia con người.** Muốn dùng nhiều provider cho review nên đánh giá bằng benchmark riêng trước; chế độ Claude có provider khác nhưng tăng chi phí.

## Luồng thực thi và các nhánh quay lại

```text
Nhà nghiên cứu: topic + notes + PDF/text + dataset + budget
    |
    v
PI -> Literature -> Methods -> Engineer
                              |
                     [Duyệt code + SHA256]
                      /                  \
               Run Docker                Skip
                      \                  /
                       Analyst -> Writer
                                    |
                         +----------+----------+
                         |          |          |
                        R1         R2         R3    (fan-out, sealed)
                         +----------+----------+
                                    |
                               Review Chair           (barrier/fan-in)
                                    |
                           Audit + Board routing
                +-------------------+----------------------+
                |                   |                      |
        revise_manuscript     new_experiment         more_literature
                |                   |                      |
       revision cap check       [Human rework approval]     |
                |                   +----------------------+
              Writer                |                     |
                |                 Methods              Literature
            R1/R2/R3                |                     |
                |                 Engineer -> [Duyệt code mới]
              Chair                 |
                +-------------------+
                                    |
              no_change / limit reached / user keeps current draft
                                    |
                        [Nhận bản nháp và review]
                                    |
                         Research pack / không submission
```

Đây là graph thực trong `backend/workflow.py`, không phải sơ đồ mô tả chức năng chưa có. Ba reviewer được LangGraph chạy ở cùng một nhánh fan-out; Chair chỉ được gọi sau barrier. Với OpenClaw gateway cấu hình `maxConcurrent=1`, các request có thể xếp hàng ở runtime, nhưng báo cáo vẫn độc lập và Chair vẫn chờ đủ.

Default tối đa **một vòng sửa sau vòng đầu**. `max_revisions=0` dùng để chỉ review. Sửa manuscript không tự chạy lại code; nếu cần dữ liệu/thực nghiệm, phải đi qua rework gate và điểm duyệt code mới. Khi đạt giới hạn hoặc budget cap, vấn đề chưa giải quyết được giữ nguyên và báo cho người dùng.

## Hợp đồng review

Reviewer phải gọi `submit_review`; văn bản “tôi đã review” không đủ để hoàn tất node. Harness chọn danh tính reviewer phía server; model không tự chỉ định mình là Chair.

```json
{
  "verdict": "hold",
  "action": "new_experiment",
  "score": 2,
  "confidence": "low",
  "rationale": "Chưa có baseline công bằng trên cùng dataset/split.",
  "evidence_refs": ["methods.md", "manuscript.md"],
  "blocking_issues": ["Không có raw metrics cho baseline"],
  "recommended_fixes": ["Chạy baseline và phương pháp trên cùng test split"]
}
```

`verdict`: `hold`, `revise`, `ready_for_human`. `action`: `no_change`, `revise_manuscript`, `new_experiment`, `more_literature`. Không có verdict “accepted/publish”.

Harness xác thực schema, điểm 1–5, evidence_refs có trong registry/artifact/chunk; gắn thêm reviewer, round và SHA256 manuscript. Chair chỉ nộp được khi đủ ba review của cùng round và cùng manuscript hash. `ready_for_human` bị hạ thành `hold` nếu chưa có experiment hoàn tất hoặc vẫn có blocking issues. Process exit thành công vẫn chưa chứng minh kết quả khoa học đúng.

R1/R2/R3 không nhận peer reports trong context. Tool `read_artifact` chặn đọc các artifact review, board và quality của nhau. Chair được cấp sealed scorecards sau barrier. Author/Methods nhận feedback của board ở vòng sửa. Nội dung user tự nhập hoặc tài liệu chứa review cũ không thể được bảo đảm “mù” tuyệt đối; hệ thống không tuyên bố blind review đạt chuẩn hội nghị.

Score và confidence dùng để chẩn đoán, chưa được calibration theo reviewer thật. Chair không được lấy đa số hay trung bình điểm làm bằng chứng đủ mạnh để bỏ qua lỗi chặn.

## Tool và quyền theo vai trò

| Tool/capability | Ai được dùng | Giới hạn |
| --- | --- | --- |
| `literature_search` | Literature, Methods | Crossref metadata/arXiv abstract, URL cố định |
| `search_documents` | Các vai trò | Chunk từ tài liệu đã import của run hiện tại |
| `read_artifact` | Các vai trò | File tên hợp lệ trong run, đọc theo dòng, 25k ký tự/call; reviewer không đọc peer reports |
| `save_experiment` | Engineer | Chỉ stage code và syntax-check, không host exec |
| `submit_review` | R1/R2/R3/Chair | Schema + source IDs + identity server-side |
| Docker execute | Harness sau human approval | Hash khớp, offline, quota tài nguyên; không phải tool model |
| Publish/submit/email | Không có | Không gửi bài hoặc liên hệ người khác |

Literature phải có tool call tìm kiếm; Engineer phải stage script. Reviewer phải nộp scorecard trước final text. Provider lỗi hoặc model không làm đúng contract sẽ dừng node, không được âm thầm trả kết quả demo. Trên Claude 5.5, adapter dùng `tool_choice:auto` và kiểm tra contract sau call vì model không hỗ trợ forced tool use. Nguồn: [Claude thinking/tool constraints](https://platform.claude.com/docs/en/build-with-claude/thinking).

## State, recovery và lineage

- `studio.sqlite`: run metadata, atomic updates, events, source/document/dataset manifests, reviews, board, budget ledger.
- `checkpoints.sqlite`: LangGraph graph state, task results, interrupts; `thread_id=run_id`.
- Reviewer fan-out có reducer merge output theo role. SQLite transaction read/modify/write giữ scorecards và outputs của các nhánh, tránh ghi đè nhau.
- Artifact current có tên dễ đọc; snapshot `*-round0.*`, `*-round1.*` giữ lịch sử.
- Khi quay lại nghiên cứu, script/logs/metrics cũ được chuyển sang `archived-r<round>-*`. Execution state của vòng mới là `not_run`; metrics cũ không tự được đưa vào context của vòng mới.
- CSV/JSON giữ SHA256 byte gốc và mount `/inputs` read-only; code duyệt theo hash byte thực trên Windows.
- Pause/backend restart không tự resume API có phí. Người dùng chọn tiếp tục từ checkpoint. Call timeout/cancel giữ cost reservation vì provider có thể vẫn tính tiền.

LangGraph cung cấp interrupt/checkpoint; app chịu trách nhiệm approvals, side effects và idempotency của artifact. Chưa cam kết exactly-once billing khi process chết giữa response API và checkpoint. Nguồn về primitive: [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts).

## OpenClaw nằm ở đâu?

UI -> FastAPI harness -> LangGraph node -> adapter -> OpenClaw OpenResponses -> model provider.

Function calls quay lại harness và được kiểm tra role policy trước khi chạy. Mỗi node là một agent logic với prompt, tools, output contract và context riêng; **không phải 10 tiến trình hệ điều hành hay 10 OpenClaw gateway**. Profile gateway hiện có một target `research`, model được chọn theo role qua header được tài liệu hóa.

OpenClaw native tools bị deny trong profile này; browser/cron/memory plugin không dùng. Harness cấp function tools có phạm vi hẹp. Điều này tránh để hai runtime cùng sở hữu việc chạy shell, ghi file và phê duyệt. HTTP credential của OpenClaw có quyền operator rộng, nên chỉ backend giữ token và gateway bind loopback. Nguồn: [OpenResponses](https://docs.openclaw.ai/gateway/openresponses-http-api).

Đường Lean/Hybrid trực tiếp chạy cùng graph và tool contracts, hữu ích cho kiểm thử và ngân sách thấp. Không cần một OpenClaw instance mới cho mỗi reviewer.

## Đánh giá hệ thống trước khi tin dùng

Pilot nên dùng 10–20 tác vụ có kết quả kiểm tra được, gồm:

1. Tìm một paper biết trước; phân biệt metadata, abstract và full text.
2. Dataset có leakage cố ý: R2 có phát hiện không?
3. Code tính metric sai: R3 có chỉ ra đúng dòng và tác động không?
4. Manuscript overclaim hoặc DOI bịa: R1 và audit có chặn không?
5. Hai reviewer bất đồng: Chair có viện dẫn evidence thay vì lấy đa số không?
6. Yêu cầu chạy lại: có quay về Methods và chờ duyệt code mới không?
7. Hết quota/tiền: có dừng, giữ checkpoint và không đổi provider không?

Đo completion rate, tỷ lệ citation không tồn tại, tỷ lệ claim được nguồn hỗ trợ, khả năng phát hiện lỗi cài sẵn, false alarms, tái lập từ artifact, chi phí và thời gian theo task. Không dùng “paper dài/trôi chảy” hoặc điểm LLM tự chấm làm metric chất lượng chính.

## Phạm vi còn thiếu

Bản này chưa có semantic/vector RAG, OCR, nguồn full-text tự tải, repo coding worker có git worktree, auto-debug code nhiều vòng, GPU/SSH/Slurm, MLflow, Zotero, LaTeX/PDF compilation, benchmarks khoa học tự động hoặc multi-user RBAC. Danh sách này là ranh giới hiện tại, không phải các tính năng đã tích hợp. Ưu tiên nâng cấp tiếp theo nên là một benchmark pilot và worker thực nghiệm phù hợp đề tài cụ thể, sau đó mới mở rộng thêm agent.
