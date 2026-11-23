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
    if not text:
        return ""
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join([l for l in lines if l != ""]).strip()

def call_gemini_with_fallback(prompt_content):
    """Tự động gọi Gemini với cơ chế thử lại và chuyển model dự phòng khi gặp lỗi 503"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    models_to_try = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
    last_err = ""
    
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt_content
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                last_err = str(e)
                if "503" in last_err or "UNAVAILABLE" in last_err or "429" in last_err:
                    time.sleep(1.5)
                    continue
                raise e
    raise Exception(f"Các máy chủ AI đều đang bận, thầy vui lòng thử lại sau vài giây. ({last_err})")

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
        "is_visible": True,
        "de_bai": "Cho mảng $A$ gồm $N$ số nguyên. Hãy tìm dãy con liên tục có tổng lớn nhất.\n\n**Giới hạn:**\n* $N \\le 10^5$\n* $\\vert{}A_i\\vert{} \\le 10^9$",
        "sample_in_1": "5\n2 -3 4 -1 2",
        "sample_out_1": "5",
        "gen_code": """# Mã Python sinh bộ 5 test: Test 1 (mẫu), Test 2 (biên N=1), Test 3 (toàn âm), Test 4 (N=10^4), Test 5 (N=10^5)
import random

def generate_test(test_id):
    if test_id == 1:
        return "5\\n2 -3 4 -1 2"
    elif test_id == 2:
        return "1\\n-1000000000"
    elif test_id == 3:
        n = 1000
        arr = [random.randint(-10**9, -1) for _ in range(n)]
        return f"{n}\\n" + " ".join(map(str, arr))
    elif test_id == 4:
        n = 10000
        arr = [random.randint(-10**9, 10**9) for _ in range(n)]
        return f"{n}\\n" + " ".join(map(str, arr))
    else:
        n = 100000
        arr = [random.randint(-10**9, 10**9) for _ in range(n)]
        return f"{n}\\n" + " ".join(map(str, arr))
""",
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
        url = f"{FIREBASE_URL}/{endpoint}.json"
        res = requests.get(url, timeout=5)
        if res.status_code == 200 and res.json() is not None:
            return res.json()
    except Exception:
        pass
    return default_value

def db_save(endpoint, data):
    if not FIREBASE_URL:
        return
    try:
        url = f"{FIREBASE_URL}/{endpoint}.json"
        requests.put(url, json=data, timeout=5)
    except Exception as e:
        st.error(f"Lỗi đồng bộ Firebase: {e}")

if 'problems_db' not in st.session_state:
    st.session_state['problems_db'] = db_get("problems", DEFAULT_PROBLEMS)

if 'student_accounts' not in st.session_state:
    st.session_state['student_accounts'] = db_get("accounts", DEFAULT_ACCOUNTS)

if 'submissions_db' not in st.session_state:
    st.session_state['submissions_db'] = db_get("submissions", {})

if 'top_display_count' not in st.session_state:
    st.session_state['top_display_count'] = db_get("top_count", 3)

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
if 'batch_parsed_problems' not in st.session_state:
    st.session_state['batch_parsed_problems'] = []

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
    full_text = []
    # Trích xuất cả đoạn văn và bảng biểu (để giữ nguyên khung Ví dụ Input/Output)
    for block in doc.element.body:
        if block.tag.endswith('p'):
            p_text = "".join(block.itertext()).strip()
            if p_text:
                full_text.append(p_text)
        elif block.tag.endswith('tbl'):
            full_text.append("\n[BẢNG VÍ DỤ]:")
            for row in block.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr'):
                cells = ["".join(c.itertext()).strip() for c in row.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc')]
                full_text.append(" | ".join(cells))
            full_text.append("[HẾT BẢNG]\n")
    return sanitize_text("\n".join(full_text))

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

def execute_generator_script(gen_code, test_id):
    """Thực thi mã Python sinh dữ liệu Input cho Test ID tương ứng"""
    local_scope = {}
    try:
        exec(gen_code, {}, local_scope)
        if "generate_test" in local_scope:
            return str(local_scope["generate_test"](test_id)).strip()
    except Exception:
        pass
    return ""

def get_top_students(top_n=3):
    all_subs = db_get("submissions", st.session_state['submissions_db'])
    all_st_accounts = list(st.session_state.get('student_accounts', {}).keys())
    
    leaderboard = []
    for st_id in all_st_accounts:
        st_subs = all_subs.get(st_id, [])
        best_by_prob = {}
        
        for s in st_subs:
            t = s.get('ten_bai', '').strip().upper()
            sc = float(s.get('diem', 0.0))
            if t not in best_by_prob or sc > best_by_prob[t]:
                best_by_prob[t] = sc
                
        total_score = sum(best_by_prob.values())
        ac_count = sum(1 for sc in best_by_prob.values() if sc == 10.0)
        num_problems_done = len(best_by_prob)
        avg_score = (total_score / num_problems_done) if num_problems_done > 0 else 0.0
        
        if len(st_subs) > 0:
            leaderboard.append({
                "st_id": st_id,
                "ac_count": ac_count,
                "total_score": total_score,
                "avg_score": avg_score
            })
            
    leaderboard.sort(key=lambda x: (x["ac_count"], x["total_score"], x["avg_score"]), reverse=True)
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
    visible_problems = [p for p in st.session_state['problems_db'] if p.get('is_visible', True) == True]
    
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
    visible_problems = [p for p in st.session_state['problems_db'] if p.get('is_visible', True) == True]
    
    if st.session_state['user_role'] != 'student':
        st.warning("🔒 **YÊU CẦU ĐĂNG NHẬP:** Vui lòng đăng nhập tài khoản Học sinh ở thanh Menu bên trái để nộp bài & chấm điểm!")
        
        top_limit = st.session_state.get('top_display_count', 3)
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
                        <p>⭐ Điểm trung bình: <b>{st_info['avg_score']:.1f} / 10 điểm</b></p>
                    </div>
                    """, unsafe_allow_html=True)
            st.markdown("---")

        st.markdown("## 🆕 Danh Sách Bài Tập Mới Đăng Nổi Bật")
        if len(visible_problems) == 0:
            st.info("Hiện tại chưa có bài tập nào được công khai.")
        else:
            recent_probs = list(reversed(visible_problems))[:5]
            for idx, p in enumerate(recent_probs):
                with st.expander(f"📌 **{p['ten_bai']}** — *(Hình thức: {p['io_mode']})*", expanded=(idx == 0)):
                    st.markdown(f"**Nội dung xem trước đề bài:**")
                    short_de_bai = p['de_bai'][:220] + "..." if len(p['de_bai']) > 220 else p['de_bai']
                    st.markdown(short_de_bai)
                    st.caption("🔒 *Hãy đăng nhập tài khoản Học sinh để xem ví dụ mẫu và gửi bài nộp C++!*")
                    
    elif len(visible_problems) == 0:
        st.info("📚 Hiện tại chưa có bài tập nào được công khai để làm bài.")
    else:
        student_id = st.session_state['logged_student']
        student_tab1, student_tab2 = st.tabs(["📝 Làm Bài Tập", "📊 Thống Kê Điểm Số & Lịch Sử Bài Làm"])
        
        with student_tab1:
            st.subheader("📚 Chọn Bài Tập")
            col_select, col_confirm = st.columns([3, 1])
            prob_titles = [p['ten_bai'] for p in visible_problems]
            
            curr_idx = st.session_state['current_student_problem_id']
            if curr_idx >= len(visible_problems):
                curr_idx = 0
                st.session_state['current_student_problem_id'] = 0

            with col_select:
                selected_title_temp = st.selectbox("Danh sách bài tập hiện có:", prob_titles, index=curr_idx)

            with col_confirm:
                st.write("")
                st.write("") 
                if st.button("OK - XÁC NHẬN CHỌN BÀI", type="primary", use_container_width=True):
                    new_idx = next(i for i, p in enumerate(visible_problems) if p['ten_bai'] == selected_title_temp)
                    st.session_state['current_student_problem_id'] = new_idx
                    st.session_state['last_grade_result'] = None
                    st.toast(f"Đã chuyển sang bài tập: {selected_title_temp}!", icon="🎯")
                    st.rerun()

            prob = visible_problems[st.session_state['current_student_problem_id']]
            
            st.markdown("---")
            st.subheader(f"📝 {prob['ten_bai']}")
            
            if prob['io_mode'] == "Đọc/Ghi Tệp (.INP / .OUT)":
                st.markdown(f'<div class="file-badge">📁 Hình thức nạp dữ liệu: Đọc từ tệp <code>{prob["file_inp"]}</code> — Ghi ra tệp <code>{prob["file_out"]}</code></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="file-badge">⌨️ Hình thức nạp dữ liệu: Nhập từ bàn phím (cin) — In ra màn hình (cout)</div>', unsafe_allow_html=True)

            with st.container():
                st.markdown(prob["de_bai"])
                st.markdown("### 🧪 Ví dụ Minh Họa Đề Bài:")
                col1, col2 = st.columns(2)
                col1.caption("📥 **Input Mẫu:**"); col1.markdown(f'<div class="sample-box">{prob.get("sample_in_1", "")}</div>', unsafe_allow_html=True)
                col2.caption("📤 **Output Mẫu:**"); col2.markdown(f'<div class="sample-box">{prob.get("sample_out_1", "")}</div>', unsafe_allow_html=True)

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
                cpp_file = st.file_uploader("Chọn file .cpp từ máy tính:", type=["cpp", "c", "txt"], key=f"uploader_prob_{prob['id']}")
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
                pasted_code = st.text_area("Khung chỉnh sửa mã nguồn:", height=260, placeholder="// Nhập hoặc dán mã nguồn C++ của em vào đây...", key=editor_widget_key)
                
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
                    with st.spinner("⏳ Đang biên dịch code mẫu và sinh bộ 5 testcase tự động..."):
                        with open("teacher.cpp", "w", encoding="utf-8") as f:
                            f.write(prob.get("code_mau", ""))
                        t_compile_ok, t_err = compile_cpp("teacher.cpp", "teacher.exec")

                        with open("student.cpp", "w", encoding="utf-8") as f:
                            f.write(final_code_to_grade)
                        s_compile_ok, s_compile_err = compile_cpp("student.cpp", "student.exec")
                        
                        if not t_compile_ok:
                            st.error("❌ **LỖI HỆ THỐNG:** Code mẫu của Giáo viên chưa biên dịch được!")
                            st.code(t_err, language="bash")
                        elif not s_compile_ok:
                            st.error("❌ **LỖI BIÊN DỊCH (Compile Error):**")
                            st.code(s_compile_err, language="bash")
                        else:
                            passed_tests = 0
                            total_exec_time = 0.0
                            test_results_detail = []
                            
                            io_m = prob.get("io_mode", "cin/cout")
                            f_in = prob.get("file_inp", "BAILAM.INP")
                            f_out = prob.get("file_out", "BAILAM.OUT")
                            gen_script = prob.get("gen_code", "")

                            for t_idx in range(1, 6):
                                test_inp = execute_generator_script(gen_script, t_idx)
                                if not test_inp:
                                    test_inp = prob.get("sample_in_1", "")

                                _, correct_out, _ = run_testcase("teacher.exec", test_inp, io_m, f_in, f_out, time_limit=2.0)
                                status, student_out, exec_t = run_testcase("student.exec", test_inp, io_m, f_in, f_out, time_limit=1.0)
                                total_exec_time += exec_t
                                
                                is_correct = (status == "OK" and normalize_output(student_out) == normalize_output(correct_out))
                                if is_correct:
                                    passed_tests += 1
                                    test_results_detail.append({"test": f"Test {t_idx}", "status": "🟢 Đúng (AC)", "time": f"{exec_t:.1f} ms"})
                                else:
                                    fail_type = "🔴 Sai kết quả (WA)" if status == "OK" else f"🔴 Lỗi chạy ({status})"
                                    test_results_detail.append({"test": f"Test {t_idx}", "status": fail_type, "time": f"{exec_t:.1f} ms"})

                            calculated_score = float(passed_tests * 2.0)
                            status_display = f"AC ({passed_tests}/5 Test)" if passed_tests == 5 else f"WA ({passed_tests}/5 Test)"

                            prompt_text = f"""
                            Bạn là Giáo viên Tin học bồi dưỡng HSG. Nhận xét cực kỳ ngắn gọn bài C++ dưới đây:
                            [ĐỀ BÀI]: {prob['de_bai'][:150]}
                            [KẾT QUẢ CHẤM]: {passed_tests}/5 test đúng ({calculated_score}/10đ).
                            [CODE HỌC SINH]:
                            {final_code_to_grade}

                            YÊU CẦU TRẢ VỀ DẠNG MARKDOWN CẮT GỌT TỐI ĐA (TỔNG KHÔNG QUÁ 3 DÒNG):
                            * **🔍 Đánh giá thuật toán:** <Nhận xét 1 câu ngắn gọn>
                            * **💡 Hướng tối ưu:** <Chỉ ra 1 ý tưởng thuật toán/độ phức tạp O() để đạt điểm tối đa>
                            """
                            
                            clean_prompt = sanitize_text(prompt_text)
                            feedback_text = ""
                            try:
                                feedback_text = call_gemini_with_fallback(clean_prompt)
                            except Exception:
                                feedback_text = "* **🔍 Đánh giá thuật toán:** Cần kiểm tra kỹ các test dữ liệu lớn.\n* **💡 Hướng tối ưu:** Tối ưu cấu trúc dữ liệu và kiểu số nguyên lớn."

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
                                "test_details": test_results_detail,
                                "code_cpp": final_code_to_grade
                            }
                            
                            st_subs = st.session_state['submissions_db'][student_id]
                            target_title = prob['ten_bai'].strip().upper()
                            existing_idx = next((i for i, s in enumerate(st_subs) if s.get('ten_bai', '').strip().upper() == target_title), -1)
                            
                            if existing_idx == -1:
                                st_subs.append(sub_record)
                                st.toast("🎉 Đã lưu bài nộp thành công!", icon="✅")
                            else:
                                old_rec = st_subs[existing_idx]
                                old_score = float(old_rec.get('diem', 0.0))
                                old_ms = float(old_rec.get('exec_ms', 999999.0))
                                
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
                    st.subheader("📊 BÁO CÁO KẾT QUẢ CHẤM MÁY & PHÂN TÍCH THUẬT TOÁN")
                with col_reset_btn:
                    if st.button("🔄 LÀM LẠI / CHẤM LẠI BÀI NÀY", type="secondary", use_container_width=True):
                        st.session_state['last_grade_result'] = None
                        st.toast("Đã xóa báo cáo cũ. Em hãy sửa lại code và bấm CHẤM BÀI nhé!", icon="✨")
                        st.rerun()

                m1, m2, m3 = st.columns(3)
                is_perfect = (res['diem'] == 10.0)
                m1.metric("Trạng Thái Bài Làm", res['trang_thai'], delta="🟢 Đạt điểm tối đa (AC)" if is_perfect else "🔴 Chưa đạt (WA)", delta_color="normal" if is_perfect else "inverse")
                m2.metric("Thời Gian Chạy Tổng 5 Test", res['thoi_gian_chay'], delta="Tối ưu")
                m3.metric("Điểm Số Đạt Được", f"{res['diem']:.1f}/10")
                
                if "test_details" in res:
                    st.markdown("### 📋 Kết Quả Chi Tiết 5 Bộ Test Sinh Động:")
                    st.dataframe(res["test_details"], use_container_width=True)

                st.markdown("### 💡 Gợi Ý Tối Ưu Từ Thầy AI:")
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
                        st.markdown("**📋 Gợi Ý Tối Ưu Từ AI:**")
                        st.markdown(sub['nhan_xet_ai'])

# ==========================================
# 6. GIAO DIỆN GIÁO VIÊN (ĐỒNG BỘ ĐÁM MÂY FIREBASE)
# ==========================================
else:
    if st.session_state['user_role'] != 'teacher':
        st.warning("🔒 **KHU VỰC BẢO MẬT:** Bàn làm việc Giáo viên yêu cầu quyền Quản trị. Vui lòng đăng nhập mật khẩu ở Menu bên trái!")
    else:
        st.subheader("👨‍🏫 Bàn Làm Việc Giáo Viên — Quản Lý Đề Thi & Học Sinh")
        teacher_tabs = [
            "📋 Danh Sách Bài Đã Đăng", 
            "➕ Thêm / Sửa Bài Lẻ", 
            "📚 Nhập File Chuyên Đề (Tách Hàng Loạt)", 
            "👥 Quản Lý Tài Khoản Học Sinh", 
            "⚙️ Cấu Hình Vinh Danh & Thống Kê"
        ]
        curr_tab_idx = st.session_state['active_teacher_tab']
        if curr_tab_idx >= len(teacher_tabs):
            curr_tab_idx = 0

        selected_tab = st.radio(
            "Chọn chức năng làm việc:",
            teacher_tabs,
            index=curr_tab_idx,
            horizontal=True
        )
        st.markdown("---")

        # TAB 0: DANH SÁCH BÀI ĐÃ ĐĂNG
        if selected_tab == "📋 Danh Sách Bài Đã Đăng":
            st.markdown("### 📚 Danh Sách Ngân Hàng Đề Thi Hiện Có:")
            col_add_btn1, col_add_btn2, _ = st.columns([1.2, 1.5, 2.3])
            with col_add_btn1:
                if st.button("➕ SOẠN BÀI LẺ MỚI", type="primary", use_container_width=True):
                    st.session_state['selected_problem_id'] = -1
                    st.session_state['active_teacher_tab'] = 1
                    st.rerun()
            with col_add_btn2:
                if st.button("📚 NHẬP TỪ FILE CHUYÊN ĐỀ", type="secondary", use_container_width=True):
                    st.session_state['active_teacher_tab'] = 2
                    st.rerun()

            if len(st.session_state['problems_db']) == 0:
                st.info("Chưa có bài tập nào. Hãy thêm bài lẻ hoặc tải lên tệp chuyên đề!")

            for idx, p in enumerate(st.session_state['problems_db']):
                status_icon = "🟢 [ĐANG MỞ]" if p.get('is_visible', True) else "🔒 [ĐANG ẨN / SOÁT ĐỀ]"
                with st.expander(f"📌 Bài {idx+1}: {p['ten_bai']} — {status_icon}", expanded=False):
                    c_info, c_act1, c_act2 = st.columns([3, 1, 1])
                    with c_info:
                        st.markdown(f"**Giới hạn/Đề bài:** {p['de_bai'][:140]}...")
                        st.caption(f"Hình thức: `{p['io_mode']}` | File INP: `{p['file_inp']}` | File OUT: `{p['file_out']}`")
                    with c_act1:
                        if st.button(f"✏️ SỬA ĐỀ", key=f"edit_btn_{idx}", use_container_width=True):
                            st.session_state['selected_problem_id'] = idx
                            st.session_state['active_teacher_tab'] = 1
                            st.toast(f"Đã chọn bài: {p['ten_bai']} để chỉnh sửa!")
                            st.rerun()
                    with c_act2:
                        if st.button(f"🗑️ XOÁ BÀI", key=f"del_btn_{idx}", type="secondary", use_container_width=True):
                            removed_title = st.session_state['problems_db'][idx]['ten_bai']
                            st.session_state['problems_db'].pop(idx)
                            db_save("problems", st.session_state['problems_db'])
                            st.session_state['selected_problem_id'] = -1
                            st.toast(f"🗑️ Đã xóa bài tập: {removed_title}!", icon="🎉")
                            st.rerun()

        # TAB 1: THÊM / SỬA BÀI LẺ
        elif selected_tab == "➕ Thêm / Sửa Bài Lẻ":
            edit_id = st.session_state['selected_problem_id']
            is_new = (edit_id == -1 or edit_id >= len(st.session_state['problems_db']))
            
            if is_new:
                st.markdown("### ➕ Soạn Thảo Bài Tập Mới (Mô Hình Sinh Test Cục Bộ)")
                curr_p = {
                    "ten_bai": "", "io_mode": "Đọc/Ghi Tệp (.INP / .OUT)",
                    "file_inp": "BAILAM.INP", "file_out": "BAILAM.OUT",
                    "is_visible": True, "de_bai": "", "sample_in_1": "", "sample_out_1": "",
                    "gen_code": """# Đoạn mã Python sinh 5 Testcase:
import random

def generate_test(test_id):
    if test_id == 1:
        return "5\\n1 2 3 4 5"  # Test ví dụ nhỏ
    elif test_id == 2:
        return "1\\n1000000000" # Test biên cực tiểu/cực đại
    elif test_id == 3:
        n = 1000
        return f"{n}\\n" + " ".join([str(random.randint(1, 10**9)) for _ in range(n)])
    elif test_id == 4:
        n = 10000
        return f"{n}\\n" + " ".join([str(random.randint(1, 10**9)) for _ in range(n)])
    else:
        n = 100000 # Test giới hạn lớn N=10^5
        return f"{n}\\n" + " ".join([str(random.randint(1, 10**9)) for _ in range(n)])
""",
                    "code_mau": ""
                }
            else:
                st.markdown(f"### ✏️ Chỉnh Sửa Bài Tập: **{st.session_state['problems_db'][edit_id]['ten_bai']}**")
                curr_p = st.session_state['problems_db'][edit_id]

            col_t1, col_t2, col_t3 = st.columns([2, 1, 1])
            with col_t1:
                ten_bai_val = st.text_input("📌 Tên Bài Tập:", value=curr_p['ten_bai'])
            with col_t2:
                io_mode_val = st.selectbox("⚙️ Hình Thức Nhập / Xuất:", ["Đọc/Ghi Tệp (.INP / .OUT)", "Nhập/Xuất Chuẩn (cin / cout)"], index=0 if curr_p['io_mode'] == "Đọc/Ghi Tệp (.INP / .OUT)" else 1)
            with col_t3:
                vis_option = st.selectbox("👁️ Trạng Thái Hiển Thị:", ["👁️ HIỆN (Học sinh thấy)", "🔒 ẨN (Kiểm thử / Soát đề)"], index=0 if curr_p.get('is_visible', True) else 1)
                is_visible_val = (vis_option == "👁️ HIỆN (Học sinh thấy)")
            
            if io_mode_val == "Đọc/Ghi Tệp (.INP / .OUT)":
                c_file1, c_file2 = st.columns(2)
                with c_file1: file_inp_val = st.text_input("📥 Tên Tệp Vào (Input File):", value=curr_p['file_inp'])
                with c_file2: file_out_val = st.text_input("📤 Tên Tệp Ra (Output File):", value=curr_p['file_out'])
            else:
                file_inp_val, file_out_val = "cin", "cout"

            st.markdown("---")
            method = st.radio("Phương thức nạp văn bản đề bài:", ["✍️ Nhập / Copy dán văn bản trực tiếp", "📄 Tải tệp Đề bài (.pdf, .docx, .txt)"], horizontal=True)
            extracted_text = curr_p['de_bai']
            if method == "📄 Tải tệp Đề bài (.pdf, .docx, .txt)":
                uploaded_file = st.file_uploader("Chọn tệp đề bài:", type=["pdf", "docx", "txt"])
                if uploaded_file is not None:
                    if uploaded_file.name.endswith(".pdf"): extracted_text = extract_text_from_pdf(uploaded_file)
                    elif uploaded_file.name.endswith(".docx"): extracted_text = extract_text_from_docx(uploaded_file)
                    elif uploaded_file.name.endswith(".txt"): extracted_text = sanitize_text(uploaded_file.read().decode("utf-8", errors="ignore"))
                    st.success("✅ Đã trích xuất xong đề từ file!")

            de_bai_val = st.text_area("📝 Nội dung Đề bài & Giới hạn:", value=extracted_text, height=200)
            
            st.markdown("### 🧪 Ví Dụ Mẫu Để Học Sinh Hiểu Đề:")
            c1, c2 = st.columns(2)
            in_sample = c1.text_area("📥 Input Mẫu:", value=curr_p.get('sample_in_1', ''), height=90)
            out_sample = c2.text_area("📤 Output Mẫu:", value=curr_p.get('sample_out_1', ''), height=90)

            st.markdown("---")
            st.markdown("### 💻 Code C++ Mẫu Chuẩn Của Thầy (Dùng để sinh đáp án chuẩn):")
            code_mau_val = st.text_area("Khung code mẫu C++:", value=curr_p.get('code_mau', ''), height=200)

            st.markdown("---")
            st.markdown("### ⚙️ Trình Sinh Bộ 5 Test Cục Bộ (Generator Script):")
            st.caption("Trình sinh test cục bộ bằng Python giúp sinh trực tiếp từ test nhỏ đến test $10^5$ phần tử trong bộ nhớ tạm mà không tốn dung lượng lưu trữ.")
            
            gen_widget_key = f"gen_code_editor_{edit_id}"
            if gen_widget_key not in st.session_state:
                st.session_state[gen_widget_key] = curr_p.get('gen_code', '')

            if st.button("🤖 NHỜ AI TỰ VIẾT MÃ PYTHON SINH TEST THEO GIỚI HẠN ĐỀ", use_container_width=True):
                if not GEMINI_API_KEY:
                    st.error("Chưa cấu hình GEMINI_API_KEY!")
                else:
                    with st.spinner("🤖 AI đang phân tích giới hạn đề bài để viết mã sinh test..."):
                        try:
                            ai_gen_prompt = f"""
                            Bạn là chuyên gia ra đề HSG Tin học. Hãy viết MÃ NGUỒN PYTHON chứa hàm `generate_test(test_id)` trả về chuỗi String Input tương ứng:
                            - test_id = 1: Test ví dụ mẫu nhỏ
                            - test_id = 2: Test biên cực tiểu (N nhỏ nhất, giá trị biên âm/dương)
                            - test_id = 3: Test ngẫu nhiên trung bình
                            - test_id = 4: Test đặc biệt / bẫy thuật toán
                            - test_id = 5: Test tối đa giới hạn N của đề bài (ví dụ N=10^5)

                            [ĐỀ BÀI]: {de_bai_val}
                            [INPUT MẪU]: {in_sample}

                            CHỈ TRẢ VỀ DUY NHẤT ĐOẠN CODE PYTHON (KHÔNG BỌC TRONG BẤT KỲ VĂN BẢN NÀO):
                            """
                            raw_text = call_gemini_with_fallback(ai_gen_prompt)
                            code_cleaned = raw_text.replace("```python", "").replace("```", "").strip()
                            st.session_state[gen_widget_key] = code_cleaned
                            st.toast("✅ AI đã viết xong mã sinh test!", icon="🤖")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Lỗi gọi AI: {e}")

            gen_code_val = st.text_area("Mã nguồn Python sinh Test:", key=gen_widget_key, height=240)

            st.markdown("---")
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
                        "is_visible": is_visible_val,
                        "de_bai": sanitize_text(de_bai_val),
                        "sample_in_1": sanitize_text(in_sample),
                        "sample_out_1": sanitize_text(out_sample),
                        "gen_code": sanitize_text(gen_code_val),
                        "code_mau": sanitize_text(code_mau_val)
                    }
                    
                    if is_new:
                        st.session_state['problems_db'].append(new_data)
                        st.toast(f"🎉 ĐÃ THÊM THÀNH CÔNG BÀI TẬP: {ten_bai_val}!", icon="✅")
                    else:
                        st.session_state['problems_db'][edit_id] = new_data
                        st.toast(f"🎉 ĐÃ CẬP NHẬT THÀNH CÔNG BÀI TẬP: {ten_bai_val}!", icon="✅")
                    
                    db_save("problems", st.session_state['problems_db'])
                    if gen_widget_key in st.session_state:
                        del st.session_state[gen_widget_key]
                    st.session_state['active_teacher_tab'] = 0
                    st.session_state['selected_problem_id'] = -1
                    st.rerun()

        # TAB 2: NHẬP FILE CHUYÊN ĐỀ (TÁCH BÀI HÀNG LOẠT)
        elif selected_tab == "📚 Nhập File Chuyên Đề (Tách Hàng Loạt)":
            st.markdown("### 📚 Nhập & Bóc Tách Hàng Loạt Từ File Chuyên Đề")
            st.info("💡 **Tính năng thông minh:** Tải lên 1 tệp chuyên đề (`.docx`, `.pdf`, `.txt`) chứa nhiều bài tập. AI sẽ tự động nhận diện từng bài, tách đề, ví dụ Input/Output, viết sẵn **code Python sinh test** theo giới hạn và viết luôn **code giải mẫu C++**.")

            col_up_doc, col_opt_doc = st.columns([2, 1])
            with col_up_doc:
                topic_file = st.file_uploader("📂 Chọn tệp chuyên đề nhiều bài tập (.docx, .pdf, .txt):", type=["docx", "pdf", "txt"], key="topic_file_uploader")
            with col_opt_doc:
                default_vis_batch = st.selectbox("👁️ Trạng thái sau khi lưu:", ["🔒 ẨN (Để thầy soát lại)", "👁️ HIỆN (Mở cho học sinh ngay)"], index=0)
                auto_gen_cpp = st.checkbox("🤖 Tự viết luôn Code C++ mẫu chuẩn", value=True)

            if topic_file is not None:
                if st.button("⚡ PHÂN TÍCH & TÁCH THÀNH CÁC BÀI TẬP ĐƠN", type="primary", use_container_width=True):
                    if not GEMINI_API_KEY:
                        st.error("Chưa cấu hình GEMINI_API_KEY!")
                    else:
                        with st.spinner("⏳ Đang đọc tệp chuyên đề và nhờ AI bóc tách cấu trúc từng bài (có thể mất 15–30 giây)..."):
                            try:
                                if topic_file.name.endswith(".pdf"):
                                    raw_doc_text = extract_text_from_pdf(topic_file)
                                elif topic_file.name.endswith(".docx"):
                                    raw_doc_text = extract_text_from_docx(topic_file)
                                else:
                                    raw_doc_text = sanitize_text(topic_file.read().decode("utf-8", errors="ignore"))

                                cpp_instruction = """
                                - "code_mau": Viết mã nguồn C++ hoàn chỉnh, tối ưu (sử dụng freopen nếu đọc/ghi tệp, dùng long long tránh tràn số) giải đúng 100% bài toán.
                                """ if auto_gen_cpp else """
                                - "code_mau": ""
                                """

                                batch_prompt = f"""
                                Bạn là chuyên gia ra đề thi Học sinh giỏi Tin học. Dưới đây là nội dung một tài liệu chuyên đề chứa NHIỀU BÀI TẬP.
                                Hãy đọc toàn bộ tài liệu, phân tách chính xác thành TỪNG BÀI TẬP ĐƠN LẺ và trả về một MẢNG JSON (JSON Array), mỗi phần tử là một đối tượng đại diện cho 1 bài tập với đúng các trường sau:

                                - "ten_bai": Tên bài tập (VD: "BÀI 1. TỔNG NGUYÊN TỐ (SUMPRIME)")
                                - "io_mode": Chỉ nhận 1 trong 2 giá trị chính xác: "Đọc/Ghi Tệp (.INP / .OUT)" hoặc "Nhập/Xuất Chuẩn (cin / cout)". (Nếu đề có nhắc tên file .INP/.OUT thì chọn "Đọc/Ghi Tệp (.INP / .OUT)").
                                - "file_inp": Tên tệp Input viết hoa (VD: "SUMPRIME.INP"), hoặc "cin" nếu nhập chuẩn.
                                - "file_out": Tên tệp Output viết hoa (VD: "SUMPRIME.OUT"), hoặc "cout" nếu xuất chuẩn.
                                - "de_bai": Toàn bộ nội dung mô tả đề bài, dữ liệu vào/ra, ràng buộc/giới hạn (định dạng Markdown sạch sẽ, các biểu thức toán học bọc trong dấu $...$). KHÔNG bao gồm phần ví dụ mẫu ở đây.
                                - "sample_in_1": Dữ liệu Input của ví dụ 1 (chỉ lấy dữ liệu thô, không kèm chữ Input).
                                - "sample_out_1": Dữ liệu Output của ví dụ 1 (chỉ lấy dữ liệu thô, không kèm chữ Output).
                                - "gen_code": Viết mã nguồn Python thuần túy chứa hàm `generate_test(test_id)` trả về chuỗi String Input tương ứng với giới hạn của bài:
                                    * test_id = 1: Giống hệt sample_in_1
                                    * test_id = 2: Test biên cực tiểu / trường hợp đặc biệt
                                    * test_id = 3: Test ngẫu nhiên kích thước trung bình
                                    * test_id = 4: Test bẫy thuật toán / số lớn
                                    * test_id = 5: Test tối đa giới hạn N của đề bài
                                {cpp_instruction}

                                [NỘI DUNG TÀI LIỆU CHUYÊN ĐỀ]:
                                {raw_doc_text}
                                """

                                raw_ai_text = call_gemini_with_fallback(batch_prompt)
                                clean_json_str = raw_ai_text.strip()
                                if "```json" in clean_json_str:
                                    clean_json_str = clean_json_str.split("```json")[1].split("```")[0].strip()
                                elif "```" in clean_json_str:
                                    clean_json_str = clean_json_str.split("```")[1].split("```")[0].strip()
                                
                                parsed_list = json.loads(clean_json_str)
                                parsed_list = json.loads(json_response)

                                if isinstance(parsed_list, dict) and "problems" in parsed_list:
                                    parsed_list = parsed_list["problems"]

                                if not isinstance(parsed_list, list) or len(parsed_list) == 0:
                                    st.error("⚠️ AI không tìm thấy bài tập rõ ràng nào trong tệp này. Thầy kiểm tra lại định dạng tệp nhé!")
                                else:
                                    is_vis_flag = (default_vis_batch == "👁️ HIỆN (Mở cho học sinh ngay)")
                                    cleaned_batch = []
                                    for item in parsed_list:
                                        cleaned_batch.append({
                                            "ten_bai": sanitize_text(item.get("ten_bai", "Bài tập chưa đặt tên")),
                                            "io_mode": item.get("io_mode", "Đọc/Ghi Tệp (.INP / .OUT)"),
                                            "file_inp": sanitize_text(item.get("file_inp", "BAILAM.INP")),
                                            "file_out": sanitize_text(item.get("file_out", "BAILAM.OUT")),
                                            "is_visible": is_vis_flag,
                                            "de_bai": sanitize_text(item.get("de_bai", "")),
                                            "sample_in_1": sanitize_text(item.get("sample_in_1", "")),
                                            "sample_out_1": sanitize_text(item.get("sample_out_1", "")),
                                            "gen_code": sanitize_text(item.get("gen_code", "")),
                                            "code_mau": sanitize_text(item.get("code_mau", ""))
                                        })
                                    st.session_state['batch_parsed_problems'] = cleaned_batch
                                    st.success(f"🎉 Đã bóc tách thành công **{len(cleaned_batch)} bài tập** từ tệp chuyên đề!")
                            except Exception as e:
                                st.error(f"❌ Lỗi trong quá trình phân tích tệp chuyên đề: {e}")

            # Hiển thị danh sách bài đã tách để giáo viên rà soát & lưu
            if len(st.session_state['batch_parsed_problems']) > 0:
                st.markdown("---")
                st.subheader(f"📋 Danh Sách {len(st.session_state['batch_parsed_problems'])} Bài Tập Đã Tách (Xem Trước & Tinh Chỉnh)")
                
                indices_to_remove = []
                for idx, bp in enumerate(st.session_state['batch_parsed_problems']):
                    with st.expander(f"📌 Bài {idx+1}: {bp['ten_bai']} ({bp['file_inp']} / {bp['file_out']})", expanded=(idx == 0)):
                        c_b1, c_b2, c_b3 = st.columns([2.5, 1, 0.5])
                        with c_b1:
                            bp['ten_bai'] = st.text_input("Tên bài:", value=bp['ten_bai'], key=f"b_title_{idx}")
                        with c_b2:
                            bp['file_inp'] = st.text_input("File INP:", value=bp['file_inp'], key=f"b_fin_{idx}")
                        with c_b3:
                            st.write(""); st.write("")
                            if st.button("🗑️ Bỏ", key=f"b_del_{idx}", help="Loại bỏ bài này khỏi danh sách nhập"):
                                indices_to_remove.append(idx)

                        bp['de_bai'] = st.text_area("Nội dung đề bài:", value=bp['de_bai'], height=130, key=f"b_debai_{idx}")
                        
                        cb_s1, cb_s2 = st.columns(2)
                        bp['sample_in_1'] = cb_s1.text_area("Input mẫu:", value=bp['sample_in_1'], height=75, key=f"b_sin_{idx}")
                        bp['sample_out_1'] = cb_s2.text_area("Output mẫu:", value=bp['sample_out_1'], height=75, key=f"b_sout_{idx}")

                        cb_c1, cb_c2 = st.columns(2)
                        bp['code_mau'] = cb_c1.text_area("💻 Code mẫu C++ (AI giải):", value=bp['code_mau'], height=180, key=f"b_cpp_{idx}")
                        bp['gen_code'] = cb_c2.text_area("⚙️ Code Python sinh test (AI viết):", value=bp['gen_code'], height=180, key=f"b_py_{idx}")

                if len(indices_to_remove) > 0:
                    for r_idx in sorted(indices_to_remove, reverse=True):
                        st.session_state['batch_parsed_problems'].pop(r_idx)
                    st.rerun()

                st.markdown("---")
                col_save_all, col_clear_all = st.columns([3, 1])
                with col_save_all:
                    if st.button(f"💾 LƯU TẤT CẢ {len(st.session_state['batch_parsed_problems'])} BÀI VÀO NGÂN HÀNG FIREBASE", type="primary", use_container_width=True):
                        start_id = len(st.session_state['problems_db'])
                        for offset, item in enumerate(st.session_state['batch_parsed_problems']):
                            item["id"] = start_id + offset
                            st.session_state['problems_db'].append(item)
                        
                        db_save("problems", st.session_state['problems_db'])
                        count_saved = len(st.session_state['batch_parsed_problems'])
                        st.session_state['batch_parsed_problems'] = []
                        st.session_state['active_teacher_tab'] = 0
                        st.toast(f"🎉 Đã lưu thành công {count_saved} bài tập vào Firebase!", icon="✅")
                        st.rerun()
                with col_clear_all:
                    if st.button("🧹 HỦY DANH SÁCH", type="secondary", use_container_width=True):
                        st.session_state['batch_parsed_problems'] = []
                        st.rerun()

        # TAB 3: QUẢN LÝ TÀI KHOẢN HỌC SINH
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
            acc_data = [{"STT": idx+1, "Tên Đăng Nhập": u, "Mật Khẩu": p} for idx, (u, p) in enumerate(st.session_state['student_accounts'].items())]
            st.dataframe(acc_data, use_container_width=True)

        # TAB 4: CẤU HÌNH VINH DANH & THỐNG KÊ
        else:
            st.markdown("### ⚙️ Cấu Hình Vinh Danh Trang Chủ & Báo Cáo Thống Kê")
            all_subs = db_get("submissions", st.session_state['submissions_db'])
            st.session_state['submissions_db'] = all_subs
            
            col_cfg1, col_cfg2 = st.columns([2, 1])
            with col_cfg1:
                st.caption("🏆 **Cấu hình Bảng Vinh Danh Học Sinh Tích Cực ở Trang Chủ:**")
                current_top = st.session_state.get('top_display_count', 3)
                new_top_count = st.number_input("Số lượng Top học sinh hiển thị ở Trang chủ (Ví dụ: 2, 3, 4, 5...):", min_value=1, max_value=10, value=current_top)
            with col_cfg2:
                st.write(""); st.write("")
                if st.button("💾 LƯU CẤU HÌNH VINH DANH", type="primary", use_container_width=True):
                    st.session_state['top_display_count'] = int(new_top_count)
                    db_save("top_count", int(new_top_count))
                    st.toast(f"✅ Đã lưu cấu hình vinh danh Top {new_top_count} Học sinh!", icon="🏆")
                    st.rerun()

            st.markdown("---")
            stat_mode = st.selectbox("🎯 Chọn góc nhìn thống kê nâng cao:", ["1. 🏆 Bảng Xếp Hạng Tổng Sắp Cả Lớp (Leaderboard)", "2. 👤 Thống kê chi tiết theo TÊN HỌC SINH", "3. 📝 Thống kê chi tiết theo ĐỀ BÀI TẬP"])
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
                            t = s.get('ten_bai', '').strip().upper()
                            sc = float(s.get('diem', 0.0))
                            if t not in best_by_prob or sc > best_by_prob[t]:
                                best_by_prob[t] = sc
                                
                        total_score = sum(best_by_prob.values())
                        ac_count = sum(1 for sc in best_by_prob.values() if sc == 10.0)
                        num_done = len(best_by_prob)
                        avg_sc = (total_score / num_done) if num_done > 0 else 0.0
                        
                        leaderboard.append({
                            "Học Sinh": st_id,
                            "Số Bài AC (10/10)": ac_count,
                            "Số Bài Đã Giải": num_done,
                            "Tổng Điểm Tích Lũy": total_score,
                            "Điểm Trung Bình": avg_sc
                        })
                    
                    leaderboard.sort(key=lambda x: (x["Số Bài AC (10/10)"], x["Tổng Điểm Tích Lũy"], x["Điểm Trung Bình"]), reverse=True)
                    lb_display = [{
                        "Hạng": "🥇 1" if i==0 else ("🥈 2" if i==1 else ("🥉 3" if i==2 else f"{i+1}")),
                        "Tên Học Sinh": item["Học Sinh"],
                        "Số Bài 10/10 (AC)": item["Số Bài AC (10/10)"],
                        "Tổng Điểm": f"{item['Tổng Điểm Tích Lũy']:.1f}",
                        "Điểm Trung Bình": f"{item['Điểm Trung Bình']:.1f} / 10",
                        "Số Bài Đã Làm": item["Số Bài Đã Giải"]
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
                        summary_table = [{"Tên Bài Tập": info['ten_bai'], "Điểm Cao Nhất": f"{info['diem']:.1f}/10", "Thời Gian Chạy": info.get('thoi_gian_chay', 'N/A'), "Thời Gian Nộp": info.get('thoi_gian_nop', 'N/A')} for info in st_subs]
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
                        table_display = [{"STT": i+1, "Tên Học Sinh": s["Học Sinh"], "Điểm Kỷ Lục": f"{s['Điểm Cao Nhất']:.1f}/10.0", "Thời Gian Chạy": s["Thời Gian Chạy"], "Thời Gian Nộp": s["Thời Gian Nộp Kỷ Lục"]} for i, s in enumerate(student_summary)]
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