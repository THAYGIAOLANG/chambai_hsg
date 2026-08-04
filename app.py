import streamlit as st
import subprocess
import os
import random
import time
import json
import re
import requests
import unicodedata
from pypdf import PdfReader
import docx
from google import genai

# ==========================================
# 1. CẤU HÌNH TRANG WEB & TÙY CHỈNH CSS
# ==========================================
st.set_page_config(
    page_title="AlgorEvaluator - Chẩn Đoán & Chấm Điểm Thuật Toán HSG",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        padding: 20px;
        border-radius: 12px;
        color: white;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .main-header h1 { color: #ffffff !important; margin-bottom: 5px; font-weight: 700; font-size: 1.8rem; }
    .main-header p { color: #e0e6ed !important; margin: 0; font-size: 1rem; }
    
    .problem-card {
        background-color: #f8fafc;
        border-left: 5px solid #2a5298;
        padding: 22px;
        border-radius: 10px;
        margin-bottom: 18px;
        font-size: 1.15rem !important;
        line-height: 1.7 !important;
        color: #0f172a !important;
    }
    .sample-box {
        background-color: #0f172a;
        color: #38bdf8;
        font-family: 'Courier New', Courier, monospace;
        padding: 12px;
        border-radius: 6px;
        font-size: 1rem;
    }
    .file-badge {
        background-color: #e0f2fe;
        color: #0369a1;
        padding: 8px 14px;
        border-radius: 6px;
        font-weight: bold;
        display: inline-block;
        margin-bottom: 14px;
        border: 1px solid #bae6fd;
        font-size: 1rem;
    }
</style>
""", unsafe_allow_html=True)

raw_api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
GEMINI_API_KEY = "".join(c for c in raw_api_key if ord(c) < 128).strip()

TEACHER_PASSWORD = st.secrets.get("TEACHER_PASSWORD", "hoang123")
FIREBASE_URL = st.secrets.get("FIREBASE_URL", "").rstrip("/")

def sanitize_text(text):
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize('NFC', text)
    return text.encode('utf-8', 'ignore').decode('utf-8')

# ==========================================
# 2. XỬ LÝ LƯU TRỮ ĐÁM MÂY VĨNH VIỄN QUA FIREBASE
# ==========================================
DEFAULT_PROBLEMS = [
    {
        "id": 0,
        "ten_bai": "TỔNG DÃY CON CỰC ĐẠI (MAXSUB)",
        "io_mode": "Đọc/Ghi Tệp (.INP / .OUT)",
        "file_inp": "MAXSUB.INP",
        "file_out": "MAXSUB.OUT",
        "de_bai": "Cho mảng $A$ gồm $N$ số nguyên. Hãy tìm dãy con liên tục có tổng lớn nhất.\n\n**Giới hạn:**\n* $N \\le 10^5$\n* $|A_i| \\le 10^9$",
        "sample_in_1": "5\n2 -3 4 -1 2", "sample_out_1": "5",
        "sample_in_2": "3\n-1 -2 -3", "sample_out_2": "-1",
        "sample_in_3": "6\n1 2 3 -2 5 -1", "sample_out_3": "9",
        "code_mau": """#include <iostream>
using namespace std;
int main() {
    freopen("MAXSUB.INP", "r", stdin);
    freopen("MAXSUB.OUT", "w", stdout);
    ios_base::sync_with_stdio(false); cin.tie(NULL);
    int n; if (!(cin >> n)) return 0;
    long long max_s = -1e18, cur = 0;
    for(int i = 0; i < n; i++) {
        long long x; cin >> x;
        cur = max(x, cur + x);
        max_s = max(max_s, cur);
    }
    cout << max_s;
    return 0;
}"""
    }
]

DEFAULT_ACCOUNTS = {
    "hocsinh01": "123456",
    "hocsinh02": "123456"
}

def db_get(endpoint, default_value):
    if not FIREBASE_URL:
        return default_value
    try:
        res = requests.get(f"{FIREBASE_URL}/{endpoint}.json", timeout=5)
        if res.status_code == 200 and res.json() is not None:
            return res.json()
    except Exception:
        pass
    return default_value

def db_save(endpoint, data):
    if not FIREBASE_URL:
        return
    try:
        requests.put(f"{FIREBASE_URL}/{endpoint}.json", json=data, timeout=5)
    except Exception as e:
        st.error(f"Lỗi đồng bộ Firebase: {e}")

if 'problems_db' not in st.session_state:
    st.session_state['problems_db'] = db_get("problems", DEFAULT_PROBLEMS)

if 'student_accounts' not in st.session_state:
    st.session_state['student_accounts'] = db_get("accounts", DEFAULT_ACCOUNTS)

if 'user_role' not in st.session_state:
    st.session_state['user_role'] = None
if 'logged_student' not in st.session_state:
    st.session_state['logged_student'] = None
if 'active_teacher_tab' not in st.session_state:
    st.session_state['active_teacher_tab'] = 0
if 'submissions_db' not in st.session_state:
    st.session_state['submissions_db'] = {}
if 'current_student_problem_id' not in st.session_state:
    st.session_state['current_student_problem_id'] = 0
if 'last_grade_result' not in st.session_state:
    st.session_state['last_grade_result'] = None
if 'selected_problem_id' not in st.session_state:
    st.session_state['selected_problem_id'] = 0

# ==========================================
# 3. HÀM XỬ LÝ TRÍCH XUẤT ĐỀ BÀI & C++ ENGINE
# ==========================================
def extract_text_from_pdf(pdf_file):
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"
    return sanitize_text(text)

def extract_text_from_docx(docx_file):
    doc = docx.Document(docx_file)
    text = "\n".join([p.text for p in doc.paragraphs if p.text.strip() != ""])
    return sanitize_text(text)

def compile_cpp(cpp_file, exec_file):
    if os.name == 'nt' and not exec_file.endswith('.exe'):
        exec_file += '.exe'
    cmd = f'g++ -O3 "{cpp_file}" -o "{exec_file}"'
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            return False, result.stderr
        return True, ""
    except Exception as e:
        return False, str(e)

def run_testcase(exec_file, input_data, time_limit=1.0):
    if os.name == 'nt' and not exec_file.endswith('.exe'):
        exec_file += '.exe'
    
    cmd_run = f'"{os.path.abspath(exec_file)}"' if os.name == 'nt' else f'./{exec_file}'
    try:
        start_time = time.time()
        process = subprocess.run(
            cmd_run,
            input=input_data,
            capture_output=True,
            text=True,
            shell=True,
            timeout=time_limit
        )
        exec_time = (time.time() - start_time) * 1000
        if process.returncode != 0:
            return "RTE", "", exec_time
        return "OK", process.stdout.strip(), exec_time
    except subprocess.TimeoutExpired:
        return "TLE", "", time_limit * 1000
    except Exception as e:
        return "RTE", str(e), 0.0

# ==========================================
# 4. HEADER & SIDEBAR NAVIGATION
# ==========================================
st.markdown("""
<div class="main-header">
    <h1>⚡ AlgorEvaluator - Chẩn Đoán & Chấm Điểm Thuật Toán</h1>
    <p>Hệ thống chuyên sâu dành cho Bồi dưỡng Đội tuyển Học sinh giỏi Tin học THCS / THPT — Thầy Hoàng</p>
</div>
""", unsafe_allow_html=True)

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2103/2103633.png", width=70)
st.sidebar.title("📌 Hệ Thống Xác Thực")

role_option = st.sidebar.radio("Bạn muốn truy cập vào:", ["👨‍🎓 Góc Học Sinh Làm Bài", "👨‍🏫 Bàn Làm Việc Giáo Viên"])

st.sidebar.markdown("---")

if role_option == "👨‍🎓 Góc Học Sinh Làm Bài":
    if st.session_state['user_role'] != 'student':
        st.sidebar.subheader("🔑 Đăng Nhập Học Sinh")
        st_user = st.sidebar.text_input("Tên đăng nhập:")
        st_pass = st.sidebar.text_input("Mật khẩu:", type="password")
        if st.sidebar.button("🔓 Đăng Nhập Học Sinh", type="primary"):
            accounts = st.session_state['student_accounts']
            if st_user in accounts and accounts[st_user] == st_pass:
                st.session_state['user_role'] = 'student'
                st.session_state['logged_student'] = st_user
                st.sidebar.success(f"Xin chào {st_user}!")
                st.rerun()
            else:
                st.sidebar.error("❌ Mật khẩu hoặc tài khoản không chính xác!")
    else:
        st.sidebar.success(f"🟢 Tài khoản: **{st.session_state['logged_student']}**")
        if st.sidebar.button("🚪 Đăng Xuất"):
            st.session_state['user_role'] = None
            st.session_state['logged_student'] = None
            st.rerun()

else:
    if st.session_state['user_role'] != 'teacher':
        st.sidebar.subheader("🔒 Đăng Nhập Giáo Viên")
        tc_pass = st.sidebar.text_input("Mật khẩu Quản trị:", type="password")
        if st.sidebar.button("🔑 Đăng Nhập Quản Trị", type="primary"):
            if tc_pass == TEACHER_PASSWORD:
                st.session_state['user_role'] = 'teacher'
                st.sidebar.success("Đăng nhập thành công!")
                st.rerun()
            else:
                st.sidebar.error("❌ Sai mật khẩu Quản trị!")
    else:
        st.sidebar.success("🟢 Quản trị viên: **Thầy Hoàng**")
        if st.sidebar.button("🚪 Đăng Xuất Quản Trị"):
            st.session_state['user_role'] = None
            st.rerun()

# ==========================================
# 5. GIAO DIỆN HỌC SINH LÀM BÀI
# ==========================================
if role_option == "👨‍🎓 Góc Học Sinh Làm Bài":
    if st.session_state['user_role'] != 'student':
        st.warning("🔒 **YÊU CẦU ĐĂNG NHẬP:** Vui lòng đăng nhập tài khoản Học sinh ở thanh Menu bên trái để làm bài!")
    elif len(st.session_state['problems_db']) == 0:
        st.info("📚 Hiện tại chưa có bài tập nào trong Ngân hàng đề thi.")
    else:
        student_id = st.session_state['logged_student']
        
        student_tab1, student_tab2 = st.tabs(["📝 Làm Bài Tập", "📊 Thống Kê Điểm Số & Lịch Sử Bài Làm"])
        
        with student_tab1:
            st.subheader("📚 Chọn Bài Tập")
            
            col_select, col_confirm = st.columns([3, 1])
            prob_titles = [p['ten_bai'] for p in st.session_state['problems_db']]
            
            curr_idx = st.session_state['current_student_problem_id']
            if curr_idx >= len(st.session_state['problems_db']):
                curr_idx = 0
                st.session_state['current_student_problem_id'] = 0

            with col_select:
                selected_title_temp = st.selectbox("Danh sách bài tập hiện có:", prob_titles, index=curr_idx)

            with col_confirm:
                st.write("")
                st.write("") 
                if st.button("OK - XÁC NHẬN CHỌN BÀI", type="primary", use_container_width=True):
                    new_idx = next(i for i, p in enumerate(st.session_state['problems_db']) if p['ten_bai'] == selected_title_temp)
                    st.session_state['current_student_problem_id'] = new_idx
                    st.session_state['last_grade_result'] = None
                    st.toast(f"Đã chuyển sang bài tập: {selected_title_temp}!", icon="🎯")
                    st.rerun()

            prob = st.session_state['problems_db'][st.session_state['current_student_problem_id']]
            
            st.markdown("---")
            st.subheader(f"📝 {prob['ten_bai']}")
            
            if prob['io_mode'] == "Đọc/Ghi Tệp (.INP / .OUT)":
                st.markdown(f'<div class="file-badge">📁 Hình thức nạp dữ liệu: Đọc từ tệp <code>{prob["file_inp"]}</code> — Ghi ra tệp <code>{prob["file_out"]}</code></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="file-badge">⌨️ Hình thức nạp dữ liệu: Nhập từ bàn phím (cin) — In ra màn hình (cout)</div>', unsafe_allow_html=True)

            with st.container():
                st.markdown(f'<div class="problem-card">{prob["de_bai"]}</div>', unsafe_allow_html=True)
                
                st.markdown("### 🧪 Ví dụ Mẫu (Sample Tests):")
                tab1, tab2, tab3 = st.tabs(["📌 Test Mẫu 1", "📌 Test Mẫu 2", "📌 Test Mẫu 3"])
                
                with tab1:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption("📥 **Sample Input 1:**")
                        st.markdown(f'<div class="sample-box">{prob["sample_in_1"]}</div>', unsafe_allow_html=True)
                    with col2:
                        st.caption("📤 **Sample Output 1:**")
                        st.markdown(f'<div class="sample-box">{prob["sample_out_1"]}</div>', unsafe_allow_html=True)

                with tab2:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption("📥 **Sample Input 2:**")
                        st.markdown(f'<div class="sample-box">{prob["sample_in_2"]}</div>', unsafe_allow_html=True)
                    with col2:
                        st.caption("📤 **Sample Output 2:**")
                        st.markdown(f'<div class="sample-box">{prob["sample_out_2"]}</div>', unsafe_allow_html=True)

                with tab3:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption("📥 **Sample Input 3:**")
                        st.markdown(f'<div class="sample-box">{prob["sample_in_3"]}</div>', unsafe_allow_html=True)
                    with col2:
                        st.caption("📤 **Sample Output 3:**")
                        st.markdown(f'<div class="sample-box">{prob["sample_out_3"]}</div>', unsafe_allow_html=True)

            st.markdown("---")
            st.subheader("💻 Nộp Mã Nguồn Bài Giải (C++)")
            
            col_up, col_edit = st.columns([1, 2])
            prob_key = f"cpp_file_{prob['id']}"
            
            uploaded_code_text = ""
            with col_up:
                st.markdown("**Cách 1: Tải tệp mã nguồn (.cpp):**")
                cpp_file = st.file_uploader("Chọn file .cpp từ máy tính:", type=["cpp", "c", "txt"], key=prob_key)
                if cpp_file is not None:
                    raw_bytes = cpp_file.read()
                    try:
                        uploaded_code_text = raw_bytes.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        uploaded_code_text = raw_bytes.decode('latin-1', errors='ignore')
                    uploaded_code_text = sanitize_text(uploaded_code_text)
                    st.success("✅ Đã nạp thành công code từ file!")

            with col_edit:
                st.markdown("**Cách 2: Gõ/Dán code C++ trực tiếp:**")
                pasted_code = st.text_area(
                    "Khung chỉnh sửa mã nguồn:", 
                    height=260, 
                    value=uploaded_code_text if uploaded_code_text else "", 
                    placeholder="// Nhập hoặc dán mã nguồn C++ của em vào đây...",
                    key=f"text_area_{prob['id']}_{hash(uploaded_code_text)}"
                )

            final_code_to_grade = uploaded_code_text.strip() if uploaded_code_text.strip() else pasted_code.strip()
            final_code_to_grade = sanitize_text(final_code_to_grade)

            btn_submit = st.button("🚀 CHẤM BÀI & PHÂN TÍCH THUẬT TOÁN", type="primary", use_container_width=True)

            if btn_submit:
                if not final_code_to_grade:
                    st.error("⚠️ Khung mã nguồn đang trống! Em hãy dán code C++ hoặc tải file lên trước khi bấm Chấm bài.")
                elif not GEMINI_API_KEY:
                    st.error("⚠️ Hệ thống chưa cấu hình `GEMINI_API_KEY`!")
                else:
                    with st.spinner("⏳ Đang tiến hành biên dịch C++ và kiểm tra qua các Subtask..."):
                        with open("student.cpp", "w", encoding="utf-8") as f:
                            f.write(final_code_to_grade)
                        
                        compile_success, compile_err = compile_cpp("student.cpp", "student.exec")
                        
                        if not compile_success:
                            st.error("❌ **LỖI BIÊN DỊCH (Compile Error):**")
                            st.code(compile_err, language="bash")
                        else:
                            N_test = 1000
                            test_input = f"{N_test}\n" + " ".join(str(random.randint(-1000, 1000)) for _ in range(N_test))
                            status, output, exec_time = run_testcase("student.exec", test_input)
                            
                            client = genai.Client(api_key=GEMINI_API_KEY)
                            
                            # 🌟 PROMPT RÀNG BUỘC CẤU TRÚC NHẬN XẾT CỐ ĐỊNH 100%
                            prompt_text = f"""
                            Bạn là một Giáo viên dạy Bồi dưỡng Học sinh giỏi Tin học THCS/THPT chuyên nghiệp.
                            Hãy đánh giá bài làm C++ của học sinh dựa trên ĐỀ BÀI và MÃ NGUỒN.

                            [ĐỀ BÀI]: {prob['de_bai']}
                            [MÃ NGUỒN HỌC SINH]: {final_code_to_grade}
                            [KẾT QUẢ CHẠY THỰC TẾ]: Trạng thái={status}, Thời gian={exec_time:.2f}ms

                            BẮT BUỘC TRẢ VỀ DẠNG JSON CHÍNH XÁC VỚI ĐÚNG CẤU TRÚC MARKDOWN TRONG `feedback_markdown` NHƯ SAU:

                            ```json
                            {{
                                "score": <Điểm số từ 0.0 đến 10.0>,
                                "feedback_markdown": "### 📌 1. ĐÁNH GIÁ CHUNG\\n* **Điểm số:** <Số điểm>/10.0\\n* **Trạng thái:** <AC / RTE TLE WA>\\n* **Nhận xét nhanh:** <Lời 1-2 câu gọn hoặc ngắn quan tổng viên động>\\n\\n### 🔍 2. PHÂN TÍCH ĐỘ PHỨC TẠP THUẬT TOÁN\\n* **Thời gian (Time Complexity):** $O(...)$\\n* **Bộ nhớ (Space Complexity):** $O(...)$\\n* **Đánh giá giới hạn:** <Cho AC N biết bài có không này thuật toán trong trọn vẹn với đạt đề>\\n\\n### 🛠️ 3. NHẬN XÉT CHI TIẾT BÀI LÀM\\n* **Ưu điểm:** <Nêu biến, code, cách cấu dữ kiểu liệu... trong trúc tên tốt điểm đặt>\\n* **Hạn chế / Lỗi chưa tối ưu:** <Nêu (Edge cases) chưa chết code các còn dòng góc hay hoặc logic sót tối ưu>\\n\\n### 💡 4. HƯỚNG TỐI ƯU CỐT LÕI (GỢI Ý SƯ PHẠM)\\n* **Ý tưởng cải tiến:** <Giải bản cho chất code gọn hơn không mà ngắn sẵn thuật thích toán tối ưu>\\n* **Kỹ thuật khuyến nghị:** <Nêu / Mảng Pointers... Quy Two cấu cộng dùng dồn, dữ hoạch liệu như nên thuật toán trúc tên động,>"
                            }}
                            ```
                            """
                            
                            clean_prompt = sanitize_text(prompt_text)

                            response = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=clean_prompt
                            )
                            
                            try:
                                json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                                if json_match:
                                    res_json = json.loads(json_match.group(0))
                                    calculated_score = float(res_json.get("score", 0.0))
                                    feedback_text = res_json.get("feedback_markdown", response.text)
                                else:
                                    calculated_score = 0.0 if "0/10" in response.text or "0.0/10" in response.text else 10.0
                                    feedback_text = response.text
                            except Exception:
                                calculated_score = 0.0 if "0/10" in response.text or "0.0/10" in response.text else 10.0
                                feedback_text = response.text

                            if student_id not in st.session_state['submissions_db']:
                                st.session_state['submissions_db'][student_id] = []
                                
                            sub_record = {
                                "ten_bai": prob['ten_bai'],
                                "diem": calculated_score,
                                "trang_thai": status if calculated_score > 0 else "Wrong Answer",
                                "thoi_gian_chay": f"{exec_time:.2f} ms",
                                "thoi_gian_nop": time.strftime("%H:%M:%S %d/%m/%Y"),
                                "nhan_xet_ai": feedback_text
                            }
                            st.session_state['submissions_db'][student_id].append(sub_record)
                            st.session_state['last_grade_result'] = sub_record

            if st.session_state['last_grade_result'] is not None:
                res = st.session_state['last_grade_result']
                
                st.markdown("---")
                col_res_title, col_reset_btn = st.columns([3, 1])
                
                with col_res_title:
                    st.subheader("📊 BÁO CÁO CHẨN ĐOÁN & ĐÁNH GIÁ THUẬT TOÁN")
                
                with col_reset_btn:
                    if st.button("🔄 LÀM LẠI / CHẤM LẠI BÀI NÀY", type="secondary", use_container_width=True):
                        st.session_state['last_grade_result'] = None
                        st.toast("Đã xóa báo cáo cũ. Em hãy sửa lại code và bấm CHẤM BÀI nhé!", icon="✨")
                        st.rerun()

                m1, m2, m3 = st.columns(3)
                m1.metric("Trạng Thái Testcase", res['trang_thai'], delta="Thành công" if res['diem'] > 0 else "Sai thuật toán", delta_color="normal")
                m2.metric("Thời Gian Chạy Thực Tế", res['thoi_gian_chay'], delta="Tối ưu")
                m3.metric("Điểm Số Đạt Được", f"{res['diem']:.1f}/10")
                
                st.markdown("---")
                st.markdown(res['nhan_xet_ai'])

        with student_tab2:
            st.subheader(f"📊 Bảng Thống Kê Bài Làm Của Học Sinh: {student_id}")
            
            user_subs = st.session_state['submissions_db'].get(student_id, [])
            
            if len(user_subs) == 0:
                st.info("💡 Em chưa nộp bài tập nào. Hãy sang Tab '📝 Làm Bài Tập' để thử sức nhé!")
            else:
                st.markdown("### 🏆 Điểm Số Cao Nhất Đạt Được (Best Score):")
                
                best_scores = {}
                for sub in user_subs:
                    title = sub['ten_bai']
                    score = sub['diem']
                    if title not in best_scores or score > best_scores[title]:
                        best_scores[title] = score
                
                best_data = [{"Tên Bài Tập": t, "Điểm Số Cao Nhất": f"{s:.1f}/10", "Trạng Thái": "🟢 Đạt điểm tối đa" if s==10 else "🟡 Cần tối ưu thêm"} 
                             for t, s in best_scores.items()]
                st.dataframe(best_data, use_container_width=True)
                
                st.markdown("---")
                st.markdown("### 📜 Lịch Sử Chi Tiết Các Lần Nộp Bài:")
                
                for idx, sub in enumerate(reversed(user_subs)):
                    with st.expander(f"⏱️ Lần {len(user_subs)-idx}: {sub['ten_bai']} — Điểm: {sub['diem']:.1f}/10 ({sub['thoi_gian_nop']})"):
                        st.write(f"**Trạng thái:** `{sub['trang_thai']}` | **Thời gian chạy:** `{sub['thoi_gian_chay']}`")
                        st.markdown("**Đánh giá chi tiết từ AI:**")
                        st.markdown(sub['nhan_xet_ai'])

# ==========================================
# 6. GIAO DIỆN GIÁO VIÊN (ĐỒNG BỘ ĐÁM MÂY FIREBASE)
# ==========================================
else:
    if st.session_state['user_role'] != 'teacher':
        st.warning("🔒 **KHU VỰC BẢO MẬT:** Bàn làm việc Giáo viên yêu cầu quyền Quản trị. Vui lòng đăng nhập mật khẩu ở Menu bên trái!")
    else:
        st.subheader("👨‍🏫 Bàn Làm Việc Giáo Viên — Quản Lý Đề Thi & Học Sinh")
        
        selected_tab = st.radio(
            "Chọn chức năng làm việc:",
            ["📋 Danh Sách Bài Đã Đăng", "➕ Thêm Mới / Chỉnh Sửa Đề Bài", "👥 Quản Lý Tài Khoản Học Sinh"],
            index=st.session_state['active_teacher_tab'],
            horizontal=True
        )

        st.markdown("---")

        if selected_tab == "📋 Danh Sách Bài Đã Đăng":
            st.markdown("### 📚 Danh Sách Ngân Hàng Đề Thi Hiện Có:")
            
            col_add_btn, _ = st.columns([1, 3])
            with col_add_btn:
                if st.button("➕ SOẠN BÀI TẬP MỚI", type="primary"):
                    st.session_state['selected_problem_id'] = -1
                    st.session_state['active_teacher_tab'] = 1
                    st.rerun()

            if len(st.session_state['problems_db']) == 0:
                st.info("Chưa có bài tập nào. Hãy bấm nút '➕ SOẠN BÀI TẬP MỚI' để thêm bài đầu tiên!")

            for idx, p in enumerate(st.session_state['problems_db']):
                with st.expander(f"📌 Bài {idx+1}: {p['ten_bai']} ({p['io_mode']})", expanded=True):
                    c_info, c_act1, c_act2 = st.columns([3, 1, 1])
                    with c_info:
                        st.markdown(f"**Giới hạn/Đề bài:** {p['de_bai'][:120]}...")
                        st.caption(f"File INP: `{p['file_inp']}` | File OUT: `{p['file_out']}`")
                    
                    with c_act1:
                        if st.button(f"✏️ SỬA ĐỀ", key=f"edit_btn_{idx}"):
                            st.session_state['selected_problem_id'] = idx
                            st.session_state['active_teacher_tab'] = 1
                            st.toast(f"Đã chọn bài: {p['ten_bai']} để chỉnh sửa!")
                            st.rerun()

                    with c_act2:
                        if st.button(f"🗑️ XOÁ BÀI", key=f"del_btn_{idx}", type="secondary"):
                            removed_title = st.session_state['problems_db'][idx]['ten_bai']
                            st.session_state['problems_db'].pop(idx)
                            db_save("problems", st.session_state['problems_db'])
                            st.session_state['selected_problem_id'] = -1
                            st.toast(f"🗑️ Đã xóa bài tập: {removed_title}!", icon="🎉")
                            st.rerun()

        elif selected_tab == "➕ Thêm Mới / Chỉnh Sửa Đề Bài":
            edit_id = st.session_state['selected_problem_id']
            is_new = (edit_id == -1 or edit_id >= len(st.session_state['problems_db']))
            
            if is_new:
                st.markdown("### ➕ Soạn Thảo Bài Tập Mới")
                curr_p = {
                    "ten_bai": "", "io_mode": "Đọc/Ghi Tệp (.INP / .OUT)",
                    "file_inp": "BAILAM.INP", "file_out": "BAILAM.OUT",
                    "de_bai": "", "sample_in_1": "", "sample_out_1": "",
                    "sample_in_2": "", "sample_out_2": "", "sample_in_3": "", "sample_out_3": "",
                    "code_mau": ""
                }
            else:
                st.markdown(f"### ✏️ Chỉnh Sửa Bài Tập: **{st.session_state['problems_db'][edit_id]['ten_bai']}**")
                curr_p = st.session_state['problems_db'][edit_id]

            col_t1, col_t2 = st.columns([2, 1])
            with col_t1:
                ten_bai_val = st.text_input("📌 Tên Bài Tập:", value=curr_p['ten_bai'])
            with col_t2:
                io_mode_val = st.selectbox(
                    "⚙️ Hình Thức Nhập / Xuất Dữ Liệu:",
                    ["Đọc/Ghi Tệp (.INP / .OUT)", "Nhập/Xuất Chuẩn (cin / cout)"],
                    index=0 if curr_p['io_mode'] == "Đọc/Ghi Tệp (.INP / .OUT)" else 1
                )
            
            if io_mode_val == "Đọc/Ghi Tệp (.INP / .OUT)":
                c_file1, c_file2 = st.columns(2)
                with c_file1:
                    file_inp_val = st.text_input("📥 Tên Tệp Dữ Liệu Vào (Input File):", value=curr_p['file_inp'])
                with c_file2:
                    file_out_val = st.text_input("📤 Tên Tệp Kết Quả Ra (Output File):", value=curr_p['file_out'])
            else:
                file_inp_val, file_out_val = "cin", "cout"

            st.markdown("---")
            OPT_DIRECT = "✍️ Nhập / Copy dán văn bản trực tiếp"
            OPT_FILE = "📄 Tải tệp Đề bài (.pdf, .docx, .txt)"
            
            method = st.radio("Phương thức nạp văn bản đề bài:", [OPT_DIRECT, OPT_FILE], horizontal=True)
            extracted_text = curr_p['de_bai']
            
            if method == OPT_FILE:
                uploaded_file = st.file_uploader("Chọn tệp đề bài:", type=["pdf", "docx", "txt"])
                if uploaded_file is not None:
                    if uploaded_file.name.endswith(".pdf"):
                        extracted_text = extract_text_from_pdf(uploaded_file)
                    elif uploaded_file.name.endswith(".docx"):
                        extracted_text = extract_text_from_docx(uploaded_file)
                    elif uploaded_file.name.endswith(".txt"):
                        extracted_text = sanitize_text(uploaded_file.read().decode("utf-8", errors="ignore"))
                    st.success("✅ Đã trích xuất xong đề từ file!")

            de_bai_val = st.text_area("📝 Nội dung Đề bài & Giới hạn:", value=extracted_text, height=240)
            
            st.markdown("### 🧪 Cấu Hình 3 Bộ Test Mẫu (Sample Tests):")
            st_t1, st_t2, st_t3 = st.tabs(["Bộ Test Mẫu 1", "Bộ Test Mẫu 2", "Bộ Test Mẫu 3"])
            
            with st_t1:
                c1, c2 = st.columns(2)
                in_1 = c1.text_area("📥 Sample Input 1:", value=curr_p['sample_in_1'], height=90)
                out_1 = c2.text_area("📤 Sample Output 1:", value=curr_p['sample_out_1'], height=90)

            with st_t2:
                c1, c2 = st.columns(2)
                in_2 = c1.text_area("📥 Sample Input 2:", value=curr_p['sample_in_2'], height=90)
                out_2 = c2.text_area("📤 Sample Output 2:", value=curr_p['sample_out_2'], height=90)

            with st_t3:
                c1, c2 = st.columns(2)
                in_3 = c1.text_area("📥 Sample Input 3:", value=curr_p['sample_in_3'], height=90)
                out_3 = c2.text_area("📤 Sample Output 3:", value=curr_p['sample_out_3'], height=90)

            st.markdown("---")
            
            st.markdown("### 💻 Code C++ Mẫu Của Thầy:")
            col_cpp_file, col_cpp_text = st.columns([1, 2])
            
            uploaded_cpp_code = ""
            with col_cpp_file:
                st.caption("Cách 1: Tải file `.cpp` mẫu từ máy:")
                cpp_sample_file = st.file_uploader("Nạp file C++ mẫu:", type=["cpp", "c", "txt"], key="teacher_cpp_up")
                if cpp_sample_file is not None:
                    uploaded_cpp_code = sanitize_text(cpp_sample_file.read().decode("utf-8", errors="ignore"))
                    st.success("✅ Đã nạp code từ file!")

            with col_cpp_text:
                st.caption("Cách 2: Chỉnh sửa trực tiếp:")
                code_mau_val = st.text_area(
                    "Khung code mẫu C++:", 
                    value=uploaded_cpp_code if uploaded_cpp_code else curr_p['code_mau'], 
                    height=220
                )

            st.markdown("---")
            
            col_check_ai, col_save = st.columns(2)
            
            with col_check_ai:
                if st.button("🔍 DÙNG AI THẨM ĐỊNH CODE MẪU & TESTCASE", use_container_width=True):
                    if not GEMINI_API_KEY:
                        st.error("Chưa cấu hình GEMINI_API_KEY!")
                    else:
                        with st.spinner("🤖 AI đang thẩm định Code mẫu và khớp với các bộ Testcase..."):
                            client = genai.Client(api_key=GEMINI_API_KEY)
                            verify_prompt = f"""
                            Bạn là Chuyên gia Đề thi Học sinh giỏi Tin học.
                            Hãy thẩm định xem Đề bài, Code mẫu C++ và 3 bộ Sample Testcase dưới đây có KHỚP NHAU VÀ CHUẨN XÁC KỸ THUẬT không.

                            [ĐỀ BÀI]: {de_bai_val}
                            [CODE MẪU C++]: {code_mau_val}
                            [TEST 1]: IN={in_1} | OUT={out_1}
                            [TEST 2]: IN={in_2} | OUT={out_2}
                            [TEST 3]: IN={in_3} | OUT={out_3}

                            Trả về kết quả ngắn gọn:
                            1. Code mẫu có giải đúng yêu cầu đề bài không? (Chuẩn AC 100% hay có lỗi logic?)
                            2. Kết quả các bộ Sample Testcase có chính xác với kết quả Code mẫu sinh ra không?
                            3. Kết luận: [CHUẨN ĐỂ ĐĂNG BÀI] hoặc [CẦN ĐIỀU CHỈNH].
                            """
                            clean_v_prompt = sanitize_text(verify_prompt)
                            check_res = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=clean_v_prompt
                            )
                            st.info("📋 **BÁO CÁO THẨM ĐỊNH TỪ AI:**")
                            st.markdown(check_res.text)

            with col_save:
                if st.button("💾 LƯU BÀI TẬP VÀO FIREBASE (VĨNH VIỄN 100%)", type="primary", use_container_width=True):
                    if not ten_bai_val.strip():
                        st.error("⚠️ Vui lòng nhập Tên Bài Tập trước khi lưu!")
                    else:
                        new_data = {
                            "id": len(st.session_state['problems_db']) if is_new else edit_id,
                            "ten_bai": sanitize_text(ten_bai_val),
                            "io_mode": io_mode_val,
                            "file_inp": sanitize_text(file_inp_val),
                            "file_out": sanitize_text(file_out_val),
                            "de_bai": sanitize_text(de_bai_val),
                            "sample_in_1": sanitize_text(in_1), "sample_out_1": sanitize_text(out_1),
                            "sample_in_2": sanitize_text(in_2), "sample_out_2": sanitize_text(out_2),
                            "sample_in_3": sanitize_text(in_3), "sample_out_3": sanitize_text(out_3),
                            "code_mau": sanitize_text(code_mau_val)
                        }
                        
                        if is_new:
                            st.session_state['problems_db'].append(new_data)
                            st.toast(f"🎉 ĐÃ THÊM THÀNH CÔNG BÀI TẬP: {ten_bai_val}!", icon="✅")
                        else:
                            st.session_state['problems_db'][edit_id] = new_data
                            st.toast(f"🎉 ĐÃ CẬP NHẬT THÀNH CÔNG BÀI TẬP: {ten_bai_val}!", icon="✅")
                        
                        db_save("problems", st.session_state['problems_db'])
                        
                        st.session_state['active_teacher_tab'] = 0
                        st.session_state['selected_problem_id'] = -1
                        st.rerun()

        # TAB 3: QUẢN LÝ TÀI KHOẢN HỌC SINH ĐỒNG BỘ ĐÁM MÂY
        else:
            st.markdown("### 👤 Quản Lý Tài Khoản Học Sinh Nội Bộ (Đồng Bộ Đám Mây)")
            
            col_add_acc, col_edit_acc = st.columns([1, 1])
            
            with col_add_acc:
                st.caption("➕ **Tạo Tài Khoản Học Sinh Mới:**")
                new_u = st.text_input("Tên đăng nhập mới:", key="add_user")
                new_p = st.text_input("Mật khẩu mới:", type="password", key="add_pass")
                if st.button("🔑 CẤP TÀI KHOẢN MỚI", type="primary", use_container_width=True):
                    if new_u and new_p:
                        clean_u = sanitize_text(new_u)
                        clean_p = sanitize_text(new_p)
                        if clean_u in st.session_state['student_accounts']:
                            st.error("Tên đăng nhập này đã tồn tại!")
                        else:
                            st.session_state['student_accounts'][clean_u] = clean_p
                            db_save("accounts", st.session_state['student_accounts'])
                            st.toast(f"✅ Đã cấp tài khoản cho: {clean_u}!", icon="🎉")
                            st.rerun()
                    else:
                        st.error("Vui lòng điền đủ Username và Password!")

            with col_edit_acc:
                st.caption("🛠️ **Chỉnh Sửa / Cấp Lại Mật Khẩu:**")
                acc_list = list(st.session_state['student_accounts'].keys())
                if len(acc_list) > 0:
                    selected_acc = st.selectbox("Chọn tài khoản cần sửa:", acc_list)
                    current_pass = st.session_state['student_accounts'][selected_acc]
                    
                    mod_pass = st.text_input(f"Mật khẩu mới cho ({selected_acc}):", value=current_pass)
                    
                    c_btn1, c_btn2 = st.columns(2)
                    with c_btn1:
                        if st.button("💾 ĐỔI MẬT KHẨU", use_container_width=True):
                            st.session_state['student_accounts'][selected_acc] = sanitize_text(mod_pass)
                            db_save("accounts", st.session_state['student_accounts'])
                            st.toast(f"✅ Đã đổi mật khẩu cho {selected_acc}!", icon="🔑")
                            st.rerun()
                    
                    with c_btn2:
                        if st.button(f"🗑️ XÓA {selected_acc}", type="secondary", use_container_width=True):
                            del st.session_state['student_accounts'][selected_acc]
                            db_save("accounts", st.session_state['student_accounts'])
                            st.toast(f"🗑️ Đã xóa tài khoản {selected_acc}!", icon="🎉")
                            st.rerun()

            st.markdown("---")
            st.caption("📋 **Danh sách tất cả tài khoản học sinh đã cấp:**")
            acc_data = [{"STT": idx+1, "Tên Đăng Nhập": u, "Mật Khẩu": p} 
                        for idx, (u, p) in enumerate(st.session_state['student_accounts'].items())]
            st.dataframe(acc_data, use_container_width=True)