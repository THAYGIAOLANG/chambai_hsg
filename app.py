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
    
    .sample-box {
        background-color: #0f172a;
        color: #38bdf8;
        font-family: 'Courier New', Courier, monospace;
        padding: 12px;
        border-radius: 6px;
        font-size: 1rem;
        white-space: pre-wrap !important;
        word-break: break-word;
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
    .top-card {
        background: linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%);
        border: 2px solid #cbd5e1;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
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

def normalize_output(text):
    """Chuẩn hóa dữ liệu ra để so sánh chính xác tuyệt đối"""
    if not text:
        return ""
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join([l for l in lines if l != ""]).strip()

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
        "sample_in_4": "4\n-2 1 -3 4", "sample_out_4": "4",
        "sample_in_5": "5\n5 4 -1 7 8", "sample_out_5": "23",
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

if 'submissions_db' not in st.session_state:
    st.session_state['submissions_db'] = db_get("submissions", {})

if 'top_display_count' not in st.session_state:
    st.session_state['top_display_count'] = db_get("top_count", 2)

if 'user_role' not in st.session_state:
    st.session_state['user_role'] = None
if 'logged_student' not in st.session_state:
    st.session_state['logged_student'] = None
if 'active_teacher_tab' not in st.session_state:
    st.session_state['active_teacher_tab'] = 0
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

def run_testcase(exec_file, input_data, io_mode="cin/cout", file_inp="BAILAM.INP", file_out="BAILAM.OUT", time_limit=1.0):
    if os.name == 'nt' and not exec_file.endswith('.exe'):
        exec_file += '.exe'
    
    cmd_run = f'"{os.path.abspath(exec_file)}"' if os.name == 'nt' else f'./{exec_file}'
    
    # Nếu bài yêu cầu đọc tệp .INP -> Ghi tệp tạm trước khi chạy
    if io_mode == "Đọc/Ghi Tệp (.INP / .OUT)" and file_inp:
        try:
            with open(file_inp, "w", encoding="utf-8") as f:
                f.write(input_data)
        except Exception:
            pass

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

        output_res = process.stdout.strip()
        
        # Nếu đọc từ tệp .OUT
        if io_mode == "Đọc/Ghi Tệp (.INP / .OUT)" and file_out and os.path.exists(file_out):
            try:
                with open(file_out, "r", encoding="utf-8") as f:
                    output_res = f.read().strip()
            except Exception:
                pass

        return "OK", output_res, exec_time

    except subprocess.TimeoutExpired:
        return "TLE", "", time_limit * 1000
    except Exception as e:
        return "RTE", str(e), 0.0

def get_top_students(top_n=2):
    all_subs = db_get("submissions", st.session_state['submissions_db'])
    all_st_accounts = list(st.session_state.get('student_accounts', {}).keys())
    
    leaderboard = []
    for st_id in all_st_accounts:
        st_subs = all_subs.get(st_id, [])
        best_by_prob = {}
        for s in st_subs:
            t = s.get('ten_bai')
            sc = s.get('diem', 0.0)
            if t not in best_by_prob or sc > best_by_prob[t]:
                best_by_prob[t] = sc
                
        total_score = sum(best_by_prob.values())
        ac_count = sum(1 for sc in best_by_prob.values() if sc == 10.0)
        
        if len(st_subs) > 0:
            leaderboard.append({
                "st_id": st_id,
                "ac_count": ac_count,
                "total_score": total_score,
                "total_subs": len(st_subs)
            })
            
    leaderboard.sort(key=lambda x: (x["ac_count"], x["total_score"], x["total_subs"]), reverse=True)
    return leaderboard[:top_n]

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
        st.warning("🔒 **YÊU CẦU ĐĂNG NHẬP:** Vui lòng đăng nhập tài khoản Học sinh ở thanh Menu bên trái để nộp bài & chấm điểm!")
        
        top_limit = st.session_state.get('top_display_count', 2)
        top_students = get_top_students(top_limit)
        
        if len(top_students) > 0:
            st.markdown(f"## 🏆 Bảng Vinh Danh Top {len(top_students)} Học Sinh Tích Cực Nhất")
            cols = st.columns(len(top_students))
            medals = ["🥇 QUÁN QUÂN", "🥈 Á QUÂN", "🥉 HẠNG 3", "🏅 TOP HỌC SINH"]
            
            for i, st_info in enumerate(top_students):
                with cols[i]:
                    st.markdown(f"""
                    <div class="top-card">
                        <h4>{medals[min(i, 3)]}: <span style="color:#0284c7;">{st_info['st_id']}</span></h4>
                        <p>✅ Bài đạt 10/10 (AC): <b>{st_info['ac_count']} Bài</b></p>
                        <p>🎯 Tổng điểm tích lũy: <b>{st_info['total_score']:.1f} điểm</b></p>
                        <p>🔥 Số lần nộp bài: <b>{st_info['total_subs']} lần</b></p>
                    </div>
                    """, unsafe_allow_html=True)
            st.markdown("---")

        st.markdown("## 🆕 Danh Sách Bài Tập Mới Đăng Nổi Bật")
        problems_list = st.session_state['problems_db']
        if len(problems_list) == 0:
            st.info("Chưa có bài tập nào được đăng.")
        else:
            recent_probs = list(reversed(problems_list))[:5]
            for idx, p in enumerate(recent_probs):
                with st.expander(f"📌 **{p['ten_bai']}** — *(Hình thức: {p['io_mode']})*", expanded=(idx == 0)):
                    st.markdown(f"**Nội dung xem trước đề bài:**")
                    short_de_bai = p['de_bai'][:220] + "..." if len(p['de_bai']) > 220 else p['de_bai']
                    st.markdown(short_de_bai)
                    st.caption("🔒 *Hãy đăng nhập tài khoản Học sinh để mở toàn bộ 5 Testcase và gửi bài nộp C++!*")
                    
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
                st.markdown(prob["de_bai"])
                
                st.markdown("### 🧪 Ví dụ Mẫu (5 Bộ Test):")
                tab1, tab2, tab3, tab4, tab5 = st.tabs(["📌 Test 1", "📌 Test 2", "📌 Test 3", "📌 Test 4", "📌 Test 5"])
                
                with tab1:
                    col1, col2 = st.columns(2)
                    col1.caption("📥 **Input 1:**"); col1.markdown(f'<div class="sample-box">{prob.get("sample_in_1", "")}</div>', unsafe_allow_html=True)
                    col2.caption("📤 **Output 1:**"); col2.markdown(f'<div class="sample-box">{prob.get("sample_out_1", "")}</div>', unsafe_allow_html=True)

                with tab2:
                    col1, col2 = st.columns(2)
                    col1.caption("📥 **Input 2:**"); col1.markdown(f'<div class="sample-box">{prob.get("sample_in_2", "")}</div>', unsafe_allow_html=True)
                    col2.caption("📤 **Output 2:**"); col2.markdown(f'<div class="sample-box">{prob.get("sample_out_2", "")}</div>', unsafe_allow_html=True)

                with tab3:
                    col1, col2 = st.columns(2)
                    col1.caption("📥 **Input 3:**"); col1.markdown(f'<div class="sample-box">{prob.get("sample_in_3", "")}</div>', unsafe_allow_html=True)
                    col2.caption("📤 **Output 3:**"); col2.markdown(f'<div class="sample-box">{prob.get("sample_out_3", "")}</div>', unsafe_allow_html=True)

                with tab4:
                    col1, col2 = st.columns(2)
                    col1.caption("📥 **Input 4:**"); col1.markdown(f'<div class="sample-box">{prob.get("sample_in_4", "")}</div>', unsafe_allow_html=True)
                    col2.caption("📤 **Output 4:**"); col2.markdown(f'<div class="sample-box">{prob.get("sample_out_4", "")}</div>', unsafe_allow_html=True)

                with tab5:
                    col1, col2 = st.columns(2)
                    col1.caption("📥 **Input 5:**"); col1.markdown(f'<div class="sample-box">{prob.get("sample_in_5", "")}</div>', unsafe_allow_html=True)
                    col2.caption("📤 **Output 5:**"); col2.markdown(f'<div class="sample-box">{prob.get("sample_out_5", "")}</div>', unsafe_allow_html=True)

            st.markdown("---")
            st.subheader("💻 Nộp Mã Nguồn Bài Giải (C++)")
            
            editor_widget_key = f"txt_area_widget_{prob['id']}"
            if editor_widget_key not in st.session_state:
                st.session_state[editor_widget_key] = ""

            file_tracker_key = f"last_uploaded_file_{prob['id']}"
            if file_tracker_key not in st.session_state:
                st.session_state[file_tracker_key] = None

            col_up, col_edit = st.columns([1, 2])
            
            uploaded_code_direct = ""
            with col_up:
                st.markdown("**Cách 1: Tải tệp mã nguồn (.cpp):**")
                cpp_file = st.file_uploader(
                    "Chọn file .cpp từ máy tính:", 
                    type=["cpp", "c", "txt"], 
                    key=f"uploader_prob_{prob['id']}"
                )
                
                if cpp_file is not None:
                    raw_bytes = cpp_file.getvalue()
                    try:
                        file_code_str = raw_bytes.decode('utf-8-sig')
                    except UnicodeDecodeError:
                        file_code_str = raw_bytes.decode('latin-1', errors='ignore')
                    
                    uploaded_code_direct = sanitize_text(file_code_str)
                    
                    if st.session_state[file_tracker_key] != cpp_file.name:
                        st.session_state[file_tracker_key] = cpp_file.name
                        st.session_state[editor_widget_key] = uploaded_code_direct
                        st.rerun()

            with col_edit:
                st.markdown("**Cách 2: Gõ/Dán code C++ trực tiếp:**")
                
                pasted_code = st.text_area(
                    "Khung chỉnh sửa mã nguồn:", 
                    height=260, 
                    placeholder="// Nhập hoặc dán mã nguồn C++ của em vào đây...",
                    key=editor_widget_key
                )
                
                if st.button("🗑️ XOÁ SẠCH KHUNG CODE", type="secondary"):
                    st.session_state[editor_widget_key] = ""
                    st.session_state[file_tracker_key] = None
                    st.toast("Đã xóa sạch khung mã nguồn!", icon="🧹")
                    st.rerun()

            final_code_to_grade = pasted_code.strip() if pasted_code.strip() else uploaded_code_direct.strip()

            btn_submit = st.button("🚀 CHẤM BÀI & PHÂN TÍCH THUẬT TOÁN", type="primary", use_container_width=True)

            if btn_submit:
                if not final_code_to_grade:
                    st.error("⚠️ Khung mã nguồn đang trống! Em hãy dán code C++ hoặc tải file lên trước khi bấm Chấm bài.")
                elif not GEMINI_API_KEY:
                    st.error("⚠️ Hệ thống chưa cấu hình `GEMINI_API_KEY`!")
                else:
                    with st.spinner("⏳ Đang biên dịch C++ và chấm qua 5 bộ Testcase..."):
                        with open("student.cpp", "w", encoding="utf-8") as f:
                            f.write(final_code_to_grade)
                        
                        compile_success, compile_err = compile_cpp("student.cpp", "student.exec")
                        
                        if not compile_success:
                            st.error("❌ **LỖI BIÊN DỊCH (Compile Error):**")
                            st.code(compile_err, language="bash")
                        else:
                            passed_tests = 0
                            total_exec_time = 0.0
                            
                            io_m = prob.get("io_mode", "cin/cout")
                            f_in = prob.get("file_inp", "BAILAM.INP")
                            f_out = prob.get("file_out", "BAILAM.OUT")

                            for t_idx in range(1, 6):
                                inp_k = prob.get(f"sample_in_{t_idx}", "").strip()
                                out_k = prob.get(f"sample_out_{t_idx}", "").strip()
                                
                                status, run_out, exec_t = run_testcase("student.exec", inp_k, io_m, f_in, f_out)
                                total_exec_time += exec_t
                                
                                # So sánh đáp án sau khi chuẩn hóa khoảng trắng & dòng trống
                                is_correct = (status == "OK" and normalize_output(run_out) == normalize_output(out_k))
                                if is_correct:
                                    passed_tests += 1

                            calculated_score = float(passed_tests * 2.0)
                            status_display = f"AC ({passed_tests}/5 Test)" if passed_tests == 5 else f"WA ({passed_tests}/5 Test)"

                            prompt_text = f"""
                            Bạn là một Giáo viên dạy Bồi dưỡng Học sinh giỏi Tin học THCS/THPT chuyên nghiệp.
                            Bài làm C++ của học sinh đã được hệ thống chấm điểm tự động qua 5 bộ Testcase:
                            - Số test đúng: {passed_tests}/5
                            - Điểm số: {calculated_score}/10.0

                            [ĐỀ BÀI]: {prob['de_bai']}
                            [MÃ NGUỒN HỌC SINH]: {final_code_to_grade}

                            Hãy đưa ra nhận xét sư phạm chi tiết bằng Markdown theo 4 mục chuẩn sau:
                            ### 📌 1. ĐÁNH GIÁ CHUNG
                            * **Kết quả chấm máy:** Đạt {calculated_score}/10.0 điểm ({passed_tests}/5 bộ Testcase).
                            * **Nhận xét nhanh:** Lời động viên hoặc nhận xét tổng quan 1-2 câu.

                            ### 🔍 2. PHÂN TÍCH ĐỘ PHỨC TẠP THUẬT TOÁN
                            * **Thời gian (Time Complexity):** O(...)
                            * **Bộ nhớ (Space Complexity):** O(...)
                            * **Đánh giá giới hạn:** Nhận xét độ phù hợp với giới hạn N của bài.

                            ### 🛠️ 3. NHẬN XÉT CHI TIẾT BÀI LÀM
                            * **Ưu điểm:** Nêu ưu điểm cách đặt tên biến, cấu trúc code...
                            * **Hạn chế / Lỗi cần sửa:** Chỉ ra cụ thể các dòng code chưa tối ưu hoặc thiếu edge case.

                            ### 💡 4. HƯỚNG TỐI ƯU CỐT LÕI (GỢI Ý SƯ PHẠM)
                            * **Ý tưởng cải tiến:** Giải thích thuật toán tối ưu hơn nếu bài chưa đạt điểm tối đa.
                            * **Kỹ thuật khuyến nghị:** Nêu tên Thuật toán/Cấu trúc dữ liệu nên dùng.
                            """
                            
                            clean_prompt = sanitize_text(prompt_text)

                            feedback_text = ""
                            try:
                                client = genai.Client(api_key=GEMINI_API_KEY)
                                try:
                                    response = client.models.generate_content(
                                        model="gemini-2.5-flash",
                                        contents=clean_prompt
                                    )
                                    feedback_text = response.text
                                except Exception:
                                    response = client.models.generate_content(
                                        model="gemini-1.5-flash",
                                        contents=clean_prompt
                                    )
                                    feedback_text = response.text
                            except Exception as ai_err:
                                feedback_text = f"### 📌 1. ĐÁNH GIÁ CHUNG\n* **Kết quả chấm máy:** Đạt {calculated_score}/10.0 điểm ({passed_tests}/5 bộ Testcase).\n* **Ghi chú:** Báo cáo phân tích thuật toán từ Thầy AI đang khởi tạo."

                            if student_id not in st.session_state['submissions_db']:
                                st.session_state['submissions_db'][student_id] = []
                                
                            sub_record = {
                                "ten_bai": prob['ten_bai'],
                                "diem": calculated_score,
                                "trang_thai": status_display,
                                "thoi_gian_chay": f"{total_exec_time:.2f} ms",
                                "exec_ms": total_exec_time,
                                "thoi_gian_nop": time.strftime("%H:%M:%S %d/%m/%Y"),
                                "nhan_xet_ai": feedback_text,
                                "code_cpp": final_code_to_grade
                            }
                            
                            st_subs = st.session_state['submissions_db'][student_id]
                            existing_idx = next((i for i, s in enumerate(st_subs) if s['ten_bai'] == prob['ten_bai']), -1)
                            
                            if existing_idx == -1:
                                st_subs.append(sub_record)
                            else:
                                old_rec = st_subs[existing_idx]
                                old_score = old_rec.get('diem', 0.0)
                                old_ms = old_rec.get('exec_ms', 999999.0)
                                
                                if (calculated_score > old_score) or (calculated_score == old_score and total_exec_time < old_ms):
                                    st_subs[existing_idx] = sub_record
                                    st.toast("🎉 Đã cập nhật kỷ lục bài làm tốt nhất của em!", icon="🏆")
                                else:
                                    st.toast("ℹ️ Lần nộp này chưa vượt qua điểm/thời gian bài làm tốt nhất trước đó.", icon="📌")

                            st.session_state['last_grade_result'] = sub_record
                            db_save("submissions", st.session_state['submissions_db'])

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
                is_perfect = (res['diem'] == 10.0)
                m1.metric(
                    "Kết Quả Testcase", 
                    res['trang_thai'], 
                    delta="🟢 Đạt điểm tối đa (AC)" if is_perfect else "🔴 Chưa đạt (WA)", 
                    delta_color="normal" if is_perfect else "inverse"
                )
                m2.metric("Thời Gian Chạy Tổng 5 Test", res['thoi_gian_chay'], delta="Tối ưu")
                m3.metric("Điểm Số Đạt Được", f"{res['diem']:.1f}/10")
                
                st.markdown("---")
                st.markdown(res['nhan_xet_ai'])

        with student_tab2:
            st.subheader(f"📊 Bảng Thống Kê Bài Làm Của Học Sinh: {student_id}")
            
            user_subs = st.session_state['submissions_db'].get(student_id, [])
            
            if len(user_subs) == 0:
                st.info("💡 Em chưa nộp bài tập nào. Hãy sang Tab '📝 Làm Bài Tập' để thử sức nhé!")
            else:
                st.markdown("### 🏆 Mã Nguồn & Kết Quả Tốt Nhất Trên Từng Bài:")
                
                best_data = [{
                    "Tên Bài Tập": sub['ten_bai'], 
                    "Điểm Số Cao Nhất": f"{sub['diem']:.1f}/10", 
                    "Thời Gian Chạy": sub['thoi_gian_chay'],
                    "Thời Gian Nộp Kỷ Lục": sub['thoi_gian_nop'],
                    "Trạng Thái": "🟢 Đạt điểm tối đa" if sub['diem']==10 else "🟡 Cần tối ưu thêm"
                } for sub in user_subs]
                st.dataframe(best_data, use_container_width=True)
                
                st.markdown("---")
                st.markdown("### 📜 Chi Tiết Báo Cáo Kỷ Lục Lời Giải Tốt Nhất:")
                
                for idx, sub in enumerate(user_subs):
                    with st.expander(f"📌 Bài {idx+1}: {sub['ten_bai']} — Điểm Kỷ Lục: {sub['diem']:.1f}/10 ({sub['thoi_gian_nop']})"):
                        st.write(f"**Trạng thái:** `{sub['trang_thai']}` | **Thời gian chạy:** `{sub['thoi_gian_chay']}`")
                        st.markdown("**💻 Code C++ Tốt Nhất Của Em:**")
                        st.code(sub.get('code_cpp', '// Không có mã nguồn'), language='cpp')
                        st.markdown("**📋 Đánh Giá Từ AI:**")
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
            ["📋 Danh Sách Bài Đã Đăng", "➕ Thêm Mới / Chỉnh Sửa Đề Bài", "👥 Quản Lý Tài Khoản Học Sinh", "⚙️ Cấu Hình Vinh Danh & Thống Kê"],
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
                    "de_bai": "", 
                    "sample_in_1": "", "sample_out_1": "",
                    "sample_in_2": "", "sample_out_2": "", 
                    "sample_in_3": "", "sample_out_3": "",
                    "sample_in_4": "", "sample_out_4": "",
                    "sample_in_5": "", "sample_out_5": "",
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
            
            st.markdown("### 🧪 Cấu Hình 5 Bộ Testcase Chấm Điểm (Mỗi Test 2.0 Điểm):")
            st_t1, st_t2, st_t3, st_t4, st_t5 = st.tabs(["Test 1", "Test 2", "Test 3", "Test 4", "Test 5"])
            
            with st_t1:
                c1, c2 = st.columns(2)
                in_1 = c1.text_area("📥 Input 1:", value=curr_p.get('sample_in_1', ''), height=90)
                out_1 = c2.text_area("📤 Output 1:", value=curr_p.get('sample_out_1', ''), height=90)

            with st_t2:
                c1, c2 = st.columns(2)
                in_2 = c1.text_area("📥 Input 2:", value=curr_p.get('sample_in_2', ''), height=90)
                out_2 = c2.text_area("📤 Output 2:", value=curr_p.get('sample_out_2', ''), height=90)

            with st_t3:
                c1, c2 = st.columns(2)
                in_3 = c1.text_area("📥 Input 3:", value=curr_p.get('sample_in_3', ''), height=90)
                out_3 = c2.text_area("📤 Output 3:", value=curr_p.get('sample_out_3', ''), height=90)

            with st_t4:
                c1, c2 = st.columns(2)
                in_4 = c1.text_area("📥 Input 4:", value=curr_p.get('sample_in_4', ''), height=90)
                out_4 = c2.text_area("📤 Output 4:", value=curr_p.get('sample_out_4', ''), height=90)

            with st_t5:
                c1, c2 = st.columns(2)
                in_5 = c1.text_area("📥 Input 5:", value=curr_p.get('sample_in_5', ''), height=90)
                out_5 = c2.text_area("📤 Output 5:", value=curr_p.get('sample_out_5', ''), height=90)

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
                            try:
                                client = genai.Client(api_key=GEMINI_API_KEY)
                                verify_prompt = f"""
                                Bạn là Chuyên gia Đề thi Học sinh giỏi Tin học.
                                Hãy thẩm định xem Đề bài, Code mẫu C++ và 5 bộ Testcase dưới đây có KHỚP NHAU VÀ CHUẨN XÁC KỸ THUẬT không.

                                [ĐỀ BÀI]: {de_bai_val}
                                [CODE MẪU C++]: {code_mau_val}
                                [TEST 1]: IN={in_1} | OUT={out_1}
                                [TEST 2]: IN={in_2} | OUT={out_2}
                                [TEST 3]: IN={in_3} | OUT={out_3}
                                [TEST 4]: IN={in_4} | OUT={out_4}
                                [TEST 5]: IN={in_5} | OUT={out_5}

                                Trả về kết quả ngắn gọn:
                                1. Code mẫu có giải đúng yêu cầu đề bài không?
                                2. Kết quả 5 bộ Testcase có chính xác với kết quả Code mẫu sinh ra không?
                                3. Kết luận: [CHUẨN ĐỂ ĐĂNG BÀI] hoặc [CẦN ĐIỀU CHỈNH].
                                """
                                clean_v_prompt = sanitize_text(verify_prompt)
                                check_res = client.models.generate_content(
                                    model="gemini-2.5-flash",
                                    contents=clean_v_prompt
                                )
                                st.info("📋 **BÁO CÁO THẨM ĐỊNH TỪ AI:**")
                                st.markdown(check_res.text)
                            except Exception as ex:
                                st.error(f"Lỗi thẩm định AI: {ex}")

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
                            "sample_in_4": sanitize_text(in_4), "sample_out_4": sanitize_text(out_4),
                            "sample_in_5": sanitize_text(in_5), "sample_out_5": sanitize_text(out_5),
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

        elif selected_tab == "👥 Quản Lý Tài Khoản Học Sinh":
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

        else:
            st.markdown("### ⚙️ Cấu Hình Vinh Danh Trang Chủ & Báo Cáo Thống Kê")
            
            all_subs = db_get("submissions", st.session_state['submissions_db'])
            st.session_state['submissions_db'] = all_subs
            
            col_cfg1, col_cfg2 = st.columns([2, 1])
            with col_cfg1:
                st.caption("🏆 **Cấu hình Bảng Vinh Danh Học Sinh Tích Cực ở Trang Chủ:**")
                current_top = st.session_state.get('top_display_count', 2)
                new_top_count = st.number_input("Số lượng Top học sinh hiển thị ở Trang chủ (Ví dụ: 2, 3, 4, 5...):", min_value=1, max_value=10, value=current_top)
            
            with col_cfg2:
                st.write("")
                st.write("")
                if st.button("💾 LƯU CẤU HÌNH VINH DANH", type="primary", use_container_width=True):
                    st.session_state['top_display_count'] = int(new_top_count)
                    db_save("top_count", int(new_top_count))
                    st.toast(f"✅ Đã lưu cấu hình vinh danh Top {new_top_count} Học sinh!", icon="🏆")
                    st.rerun()

            st.markdown("---")
            
            stat_mode = st.selectbox(
                "🎯 Chọn góc nhìn thống kê nâng cao:",
                [
                    "1. 🏆 Bảng Xếp Hạng Tổng Sắp Cả Lớp (Leaderboard)",
                    "2. 👤 Thống kê chi tiết theo TÊN HỌC SINH", 
                    "3. 📝 Thống kê chi tiết theo ĐỀ BÀI TẬP"
                ]
            )
            
            st.markdown("---")
            
            if "1. 🏆 Bảng Xếp Hạng" in stat_mode:
                st.markdown("### 🏆 Bảng Xếp Hạng Đội Tuyển Tích Cực (Kỷ Lục Điểm Tối Ưu)")
                
                all_st_accounts = list(st.session_state['student_accounts'].keys())
                if len(all_st_accounts) == 0:
                    st.info("Chưa có học sinh nào trong hệ thống.")
                else:
                    leaderboard = []
                    for st_id in all_st_accounts:
                        st_subs = all_subs.get(st_id, [])
                        best_by_prob = {}
                        for s in st_subs:
                            t = s.get('ten_bai')
                            sc = s.get('diem', 0.0)
                            if t not in best_by_prob or sc > best_by_prob[t]:
                                best_by_prob[t] = sc
                                
                        total_score = sum(best_by_prob.values())
                        ac_count = sum(1 for sc in best_by_prob.values() if sc == 10.0)
                        
                        leaderboard.append({
                            "Học Sinh": st_id,
                            "Số Bài AC (10/10)": ac_count,
                            "Số Bài Đã Giải": len(best_by_prob),
                            "Tổng Điểm Tích Lũy": total_score,
                            "Tổng Số Lần Nộp": len(st_subs)
                        })
                    
                    leaderboard.sort(key=lambda x: (x["Số Bài AC (10/10)"], x["Tổng Điểm Tích Lũy"], x["Tổng Số Lần Nộp"]), reverse=True)
                    
                    lb_display = [{
                        "Hạng": "🥇 1" if i==0 else ("🥈 2" if i==1 else ("🥉 3" if i==2 else f"{i+1}")),
                        "Tên Học Sinh": item["Học Sinh"],
                        "Số Bài 10/10 (AC)": item["Số Bài AC (10/10)"],
                        "Tổng Điểm": f"{item['Tổng Điểm Tích Lũy']:.1f}",
                        "Số Bài Đã Làm": item["Số Bài Đã Giải"],
                        "Tổng Lần Nộp": item["Tổng Số Lần Nộp"]
                    } for i, item in enumerate(leaderboard)]
                    
                    st.dataframe(lb_display, use_container_width=True)

            elif "2. 👤 Thống kê" in stat_mode:
                st.markdown("### 👤 Báo Cáo Kỷ Lục Lời Giải Của Học Sinh")
                
                all_student_list = list(st.session_state['student_accounts'].keys())
                if len(all_student_list) == 0:
                    st.info("Chưa có tài khoản học sinh nào được cấp.")
                else:
                    selected_st = st.selectbox("🎯 Chọn Học Sinh Cần Kiểm Tra:", all_student_list)
                    
                    st_subs = all_subs.get(selected_st, [])
                    total_probs_db = len(st.session_state['problems_db'])
                    
                    perfect_count = sum(1 for s in st_subs if s.get('diem') == 10.0)
                    avg_score = (sum(s.get('diem', 0.0) for s in st_subs) / len(st_subs)) if len(st_subs) > 0 else 0.0
                    
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Số Bài Đã Giải", f"{len(st_subs)}/{total_probs_db} Bài")
                    c2.metric("Số Bài Đạt 10/10", f"{perfect_count} Bài")
                    c3.metric("Điểm Trung Bình", f"{avg_score:.1f}/10")
                    c4.metric("Lần Nộp Kỷ Lục", f"{len(st_subs)} Bài")
                    
                    st.markdown("---")
                    
                    if len(st_subs) == 0:
                        st.warning(f"⚠️ Học sinh **{selected_st}** chưa nộp bài tập nào.")
                    else:
                        st.markdown(f"#### 🏆 Kỷ Lục Lời Giải Tốt Nhất Của ({selected_st}):")
                        summary_table = [{
                            "Tên Bài Tập": info['ten_bai'],
                            "Điểm Cao Nhất": f"{info['diem']:.1f}/10",
                            "Thời Gian Chạy": info.get('thoi_gian_chay', 'N/A'),
                            "Thời Gian Nộp": info.get('thoi_gian_nop', 'N/A')
                        } for info in st_subs]
                        st.dataframe(summary_table, use_container_width=True)
                        
                        st.markdown("---")
                        st.markdown(f"#### 🔍 Soi Mã Nguồn C++ Tối Ưu Của ({selected_st}):")
                        
                        prob_titles_st = [s['ten_bai'] for s in st_subs]
                        selected_prob_to_view = st.selectbox("Chọn bài tập muốn xem code:", prob_titles_st)
                        
                        chosen_sub = next(s for s in st_subs if s['ten_bai'] == selected_prob_to_view)
                        
                        col_c1, col_c2 = st.columns([1, 1])
                        with col_c1:
                            st.markdown(f"**💻 Mã Nguồn C++ Kỷ Lục ({chosen_sub.get('diem', 0.0):.1f}/10):**")
                            st.code(chosen_sub.get('code_cpp', '// Không có mã nguồn'), language='cpp')
                        with col_c2:
                            st.markdown("**📋 Phân Tích Thuật Toán Từ AI:**")
                            st.markdown(chosen_sub.get('nhan_xet_ai', ''))

            else:
                if len(st.session_state['problems_db']) == 0:
                    st.info("Chưa có bài tập nào để thống kê.")
                else:
                    prob_titles = [p['ten_bai'] for p in st.session_state['problems_db']]
                    selected_prob_title = st.selectbox("🎯 Chọn Bài Tập Cần Theo Dõi Kết Quả:", prob_titles)
                    
                    st.markdown("---")
                    
                    student_summary = []
                    for st_id, sub_list in all_subs.items():
                        prob_subs = [s for s in sub_list if s.get('ten_bai') == selected_prob_title]
                        if len(prob_subs) > 0:
                            best_sub = prob_subs[0]
                            student_summary.append({
                                "Học Sinh": st_id,
                                "Điểm Cao Nhất": best_sub.get('diem', 0.0),
                                "Thời Gian Chạy": best_sub.get('thoi_gian_chay', 'N/A'),
                                "Thời Gian Nộp Kỷ Lục": best_sub.get('thoi_gian_nop', 'N/A'),
                                "best_code": best_sub.get('code_cpp', '// Không có mã nguồn'),
                                "best_feedback": best_sub.get('nhan_xet_ai', '')
                            })
                    
                    if len(student_summary) == 0:
                        st.warning(f"⚠️ Chưa có học sinh nào nộp bài **{selected_prob_title}**.")
                    else:
                        st.success(f"📈 **Có {len(student_summary)} học sinh đã giải thành công bài này:**")
                        table_display = [{
                            "STT": i+1,
                            "Tên Học Sinh": s["Học Sinh"],
                            "Điểm Kỷ Lục": f"{s['Điểm Cao Nhất']:.1f}/10.0",
                            "Thời Gian Chạy": s["Thời Gian Chạy"],
                            "Thời Gian Nộp": s["Thời Gian Nộp Kỷ Lục"]
                        } for i, s in enumerate(student_summary)]
                        st.dataframe(table_display, use_container_width=True)
                        
                        st.markdown("---")
                        st.markdown("### 🔍 Xem Chi Tiết Mã Nguồn C++ Kỷ Lục Của Từng Học Sinh")
                        
                        st_names = [s["Học Sinh"] for s in student_summary]
                        chosen_st = st.selectbox("👤 Chọn Học Sinh Cần Kiểm Tra Code:", st_names)
                        
                        st_info = next(s for s in student_summary if s["Học Sinh"] == chosen_st)
                        
                        col_code_view, col_detail_view = st.columns([1, 1])
                        with col_code_view:
                            st.markdown(f"#### 💻 Code C++ Kỷ Lục ({st_info['Điểm Cao Nhất']:.1f}/10):")
                            st.code(st_info['best_code'], language='cpp')
                        with col_detail_view:
                            st.markdown("#### 📋 Báo Cáo Phân Tích Từ AI:")
                            st.markdown(st_info['best_feedback'])