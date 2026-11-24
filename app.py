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
    .topic-card {
        background: linear-gradient(135deg, #f8fafc 0%, #eff6ff 100%);
        border: 1.5px solid #93c5fd;
        border-left: 6px solid #1d4ed8;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04);
    }
    .topic-card h4 { margin: 0 0 6px 0; color: #1e3a8a; font-size: 1.15rem; }
    .topic-card p { margin: 0; color: #334155; font-size: 0.95rem; }
</style>
""", unsafe_allow_html=True)

raw_api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
GEMINI_API_KEY = "".join(c for c in raw_api_key if ord(c) < 128).strip()

TEACHER_PASSWORD = st.secrets.get("TEACHER_PASSWORD", "hoang123")
FIREBASE_URL = st.secrets.get("FIREBASE_URL", "").rstrip("/")

DEFAULT_TOPIC_NAME = "📚 Bài tập Luyện tập Chung"

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

def get_prob_topic(prob):
    if not isinstance(prob, dict):
        return DEFAULT_TOPIC_NAME
    t = prob.get("chu_de", "").strip()
    return t if t else DEFAULT_TOPIC_NAME

def get_prob_type(prob):
    if not isinstance(prob, dict):
        return "📚 Chuyên đề"
    return prob.get("loai_goi", "📚 Chuyên đề")

def clear_code_callback(ed_key, trk_key):
    """Callback xóa sạch khung code trước khi widget khởi tạo lại"""
    st.session_state[ed_key] = ""
    st.session_state[trk_key] = None

def cleanup_temp_files(file_list):
    """Dọn dẹp toàn bộ file biên dịch và test tạm để chống tràn RAM/Disk"""
    for f_path in file_list:
        if f_path and f_path not in ["cin", "cout"] and os.path.exists(f_path):
            try:
                os.remove(f_path)
            except Exception:
                pass

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

def parse_batch_problems_by_tags(raw_text, is_vis_flag, topic_name, pkg_type):
    """Bóc tách danh sách bài tập theo thẻ phân tách để tránh tuyệt đối lỗi ký tự \ trong LaTeX và C++"""
    blocks = raw_text.split("===BAI_MOI===")
    parsed_items = []
    for blk in blocks:
        blk = blk.strip()
        if not blk or "[TEN_BAI]" not in blk:
            continue
            
        def extract_tag(tag_name, text):
            pattern = rf"\[{tag_name}\](.*?)\[/{tag_name}\]"
            m = re.search(pattern, text, re.DOTALL)
            return m.group(1).strip() if m else ""

        ten_bai = extract_tag("TEN_BAI", blk)
        io_raw = extract_tag("IO_MODE", blk)
        io_mode = "Đọc/Ghi Tệp (.INP / .OUT)" if "Tệp" in io_raw or "INP" in io_raw else "Nhập/Xuất Chuẩn (cin / cout)"
        file_inp = extract_tag("FILE_INP", blk) or ("BAILAM.INP" if io_mode == "Đọc/Ghi Tệp (.INP / .OUT)" else "cin")
        file_out = extract_tag("FILE_OUT", blk) or ("BAILAM.OUT" if io_mode == "Đọc/Ghi Tệp (.INP / .OUT)" else "cout")
        de_bai = extract_tag("DE_BAI", blk)
        sample_in = extract_tag("SAMPLE_IN", blk)
        sample_out = extract_tag("SAMPLE_OUT", blk)
        
        gen_code = extract_tag("GEN_CODE", blk).replace("```python", "").replace("```", "").strip()
        code_mau = extract_tag("CODE_MAU", blk).replace("```cpp", "").replace("```c++", "").replace("```", "").strip()

        if ten_bai:
            parsed_items.append({
                "ten_bai": sanitize_text(ten_bai),
                "chu_de": sanitize_text(topic_name),
                "loai_goi": pkg_type,
                "io_mode": io_mode,
                "file_inp": sanitize_text(file_inp),
                "file_out": sanitize_text(file_out),
                "is_visible": is_vis_flag,
                "de_bai": sanitize_text(de_bai),
                "sample_in_1": sanitize_text(sample_in),
                "sample_out_1": sanitize_text(sample_out),
                "gen_code": sanitize_text(gen_code),
                "code_mau": sanitize_text(code_mau)
            })
    return parsed_items

# ==========================================
# 2. XỬ LÝ LƯU TRỮ ĐÁM MÂY VĨNH VIỄN QUA FIREBASE
# ==========================================
DEFAULT_PROBLEMS = [
    {
        "id": 0,
        "ten_bai": "TỔNG DÃY CON CỰC ĐẠI (MAXSUB)",
        "chu_de": "📚 Chuyên đề 1: Quy hoạch động & Mảng cộng dồn",
        "loai_goi": "📚 Chuyên đề",
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

def normalize_firebase_list(raw_data, default_val):
    """Chuẩn hóa dữ liệu từ Firebase tránh lỗi lệch kiểu dict/None"""
    if raw_data is None:
        return default_val
    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]
    if isinstance(raw_data, dict):
        return [v for _, v in sorted(raw_data.items(), key=lambda x: str(x[0])) if isinstance(v, dict)]
    return default_val

def db_get(endpoint, default_value):
    if not FIREBASE_URL:
        return default_value
    try:
        url = f"{FIREBASE_URL}/{endpoint}.json"
        res = requests.get(url, timeout=6)
        if res.status_code == 200 and res.json() is not None:
            data = res.json()
            if endpoint == "problems":
                return normalize_firebase_list(data, default_value)
            return data
    except Exception:
        pass
    return default_value

def db_save(endpoint, data):
    if not FIREBASE_URL:
        return
    try:
        url = f"{FIREBASE_URL}/{endpoint}.json"
        requests.put(url, json=data, timeout=6)
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
if 'selected_student_topic' not in st.session_state:
    st.session_state['selected_student_topic'] = None
if 'current_student_problem_idx' not in st.session_state:
    st.session_state['current_student_problem_idx'] = 0
if 'last_grade_result' not in st.session_state:
    st.session_state['last_grade_result'] = None
if 'selected_problem_id' not in st.session_state:
    st.session_state['selected_problem_id'] = -1
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
    # Sử dụng -O2 thay vì -O3 để tiết kiệm tối đa RAM khi biên dịch trên Cloud
    cmd = f'g++ -O2 "{cpp_file}" -o "{exec_file}"'
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return False, result.stderr
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Quá thời gian biên dịch (Compile Timeout)."
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
    if not isinstance(all_subs, dict):
        all_subs = {}
    all_st_accounts = list(st.session_state.get('student_accounts', {}).keys())
    
    leaderboard = []
    for st_id in all_st_accounts:
        st_subs = all_subs.get(st_id, [])
        if not isinstance(st_subs, list):
            continue
        best_by_prob = {}
        
        for s in st_subs:
            if not isinstance(s, dict):
                continue
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

def group_problems_by_topic(prob_list):
    """Gom nhóm danh sách bài tập theo Chủ đề / Đề thi"""
    grouped = {}
    for idx, p in enumerate(prob_list):
        if not isinstance(p, dict):
            continue
        topic = get_prob_topic(p)
        if topic not in grouped:
            grouped[topic] = {
                "loai_goi": get_prob_type(p),
                "items": []
            }
        grouped[topic]["items"].append((idx, p))
    return grouped

# ==========================================
# 4. HEADER & SIDEBAR NAVIGATION
# ==========================================
st.markdown("""
<div class="main-header">
    <h1>⚡ AlgorEvaluator - Chẩn Đoán & Chấm Điểm Thuật Toán</h1>
    <p>Hệ thống Luyện Đề Thi & Chuyên Đề Chuyên Sâu Dành Cho Đội Tuyển HSG Tin Học — Thầy Hoàng</p>
</div>
""", unsafe_allow_html=True)

st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2103/2103633.png", width=70)
st.sidebar.title("📌 Hệ Thống Xác Thực")

role_option = st.sidebar.radio("Bạn muốn truy cập vào:", ["👨‍🎓 Góc Học Sinh Luyện Đề", "👨‍🏫 Bàn Làm Việc Giáo Viên"])

st.sidebar.markdown("---")

if role_option == "👨‍🎓 Góc Học Sinh Luyện Đề":
    if st.session_state['user_role'] != 'student':
        st.sidebar.subheader("🔑 Đăng Nhập Học Sinh")
        st_user = st.sidebar.text_input("Tên đăng nhập:")
        st_pass = st.sidebar.text_input("Mật khẩu:", type="password")
        if st.sidebar.button("🔓 Đăng Nhập Học Sinh", type="primary"):
            accounts = st.session_state['student_accounts']
            if st_user in accounts and accounts[st_user] == st_pass:
                st.session_state['user_role'] = 'student'
                st.session_state['logged_student'] = st_user
                st.session_state['selected_student_topic'] = None
                st.sidebar.success(f"Xin chào {st_user}!")
                st.rerun()
            else:
                st.sidebar.error("❌ Mật khẩu hoặc tài khoản không chính xác!")
    else:
        st.sidebar.success(f"🟢 Tài khoản: **{st.session_state['logged_student']}**")
        if st.sidebar.button("🚪 Đăng Xuất"):
            st.session_state['user_role'] = None
            st.session_state['logged_student'] = None
            st.session_state['selected_student_topic'] = None
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
# 5. GIAO DIỆN HỌC SINH LUYỆN ĐỀ & CHỦ ĐỀ
# ==========================================
if role_option == "👨‍🎓 Góc Học Sinh Luyện Đề":
    visible_problems = [p for p in st.session_state['problems_db'] if isinstance(p, dict) and p.get('is_visible', True) == True]
    grouped_visible = group_problems_by_topic(visible_problems)
    
    if st.session_state['user_role'] != 'student':
        st.warning("🔒 **YÊU CẦU ĐĂNG NHẬP:** Vui lòng đăng nhập tài khoản Học sinh ở thanh Menu bên trái để vào phòng luyện Đề thi & Chuyên đề!")
        
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

        st.markdown("## 📂 Danh Sách Đề Thi & Chuyên Đề Đang Mở")
        if len(grouped_visible) == 0:
            st.info("Hiện tại chưa có Đề thi hoặc Chuyên đề nào được công khai.")
        else:
            for topic_name, info in grouped_visible.items():
                prob_count = len(info["items"])
                badge_type = info["loai_goi"]
                prob_names_preview = ", ".join([p['ten_bai'] for _, p in info["items"]])
                st.markdown(f"""
                <div class="topic-card">
                    <h4>{topic_name} <span style="font-size:0.85rem; background:#dbeafe; color:#1e40af; padding:3px 10px; border-radius:12px; margin-left:8px;">{badge_type} • {prob_count} bài</span></h4>
                    <p><b>Danh sách bài:</b> {prob_names_preview}</p>
                </div>
                """, unsafe_allow_html=True)
            st.caption("🔒 *Hãy đăng nhập tài khoản Học sinh ở cột bên trái để chọn Chủ đề / Đề thi và gửi mã nguồn C++!*")
                    
    elif len(grouped_visible) == 0:
        st.info("📚 Hiện tại chưa có Đề thi hoặc Chuyên đề nào được công khai.")
    else:
        student_id = st.session_state['logged_student']
        user_subs = st.session_state['submissions_db'].get(student_id, [])
        if not isinstance(user_subs, list):
            user_subs = []
        
        best_scores_map = {}
        for s in user_subs:
            if not isinstance(s, dict):
                continue
            t_key = s.get('ten_bai', '').strip().upper()
            sc_val = float(s.get('diem', 0.0))
            if t_key not in best_scores_map or sc_val > best_scores_map[t_key]:
                best_scores_map[t_key] = sc_val

        student_tab1, student_tab2 = st.tabs(["📂 Luyện Theo Đề Thi / Chủ Đề", "📊 Thống Kê Điểm Số & Lịch Sử Bài Làm"])
        
        with student_tab1:
            curr_topic = st.session_state.get('selected_student_topic')
            
            if not curr_topic or curr_topic not in grouped_visible:
                st.subheader("📂 Chọn Đề Thi Hoặc Chuyên Đề Luyện Tập")
                st.caption("Bấm vào một **Đề thi** hoặc **Chuyên đề** bên dưới để mở danh sách các bài tập bên trong:")
                
                topic_keys = list(grouped_visible.keys())
                for t_idx, t_name in enumerate(topic_keys):
                    t_info = grouped_visible[t_name]
                    t_probs = [p for _, p in t_info["items"]]
                    total_p = len(t_probs)
                    
                    ac_p = 0
                    sum_sc = 0.0
                    for p in t_probs:
                        sc = best_scores_map.get(p['ten_bai'].strip().upper(), -1.0)
                        if sc >= 0:
                            sum_sc += sc
                            if sc == 10.0:
                                ac_p += 1
                    
                    c_card, c_btn = st.columns([4, 1.2])
                    with c_card:
                        st.markdown(f"""
                        <div class="topic-card">
                            <h4>{t_name} <span style="font-size:0.82rem; background:#dbeafe; color:#1e40af; padding:2px 9px; border-radius:10px; margin-left:6px;">{t_info['loai_goi']}</span></h4>
                            <p>📌 Số lượng: <b>{total_p} bài</b> &nbsp;|&nbsp; ✅ Hoàn thành tối đa (10đ): <b>{ac_p}/{total_p} bài</b> &nbsp;|&nbsp; 🎯 Điểm gói này: <b>{sum_sc:.1f}/{total_p*10:.0f}</b></p>
                        </div>
                        """, unsafe_allow_html=True)
                    with c_btn:
                        st.write("")
                        st.write("")
                        if st.button("🚀 VÀO LÀM BÀI", key=f"enter_topic_{t_idx}", type="primary", width="stretch"):
                            st.session_state['selected_student_topic'] = t_name
                            st.session_state['current_student_problem_idx'] = 0
                            st.session_state['last_grade_result'] = None
                            st.rerun()

            else:
                col_back, col_topic_title = st.columns([1.3, 3.7])
                with col_back:
                    if st.button("⬅️ CHỌN CHỦ ĐỀ KHÁC", type="secondary", width="stretch"):
                        st.session_state['selected_student_topic'] = None
                        st.session_state['last_grade_result'] = None
                        st.rerun()
                with col_topic_title:
                    st.markdown(f"### 📂 {curr_topic}")

                topic_probs = [p for _, p in grouped_visible[curr_topic]["items"]]
                
                prob_labels = []
                for idx_p, p in enumerate(topic_probs):
                    sc = best_scores_map.get(p['ten_bai'].strip().upper(), -1.0)
                    if sc == 10.0:
                        status_tag = f"✅ [10.0đ - AC]"
                    elif sc >= 0:
                        status_tag = f"🟡 [{sc:.1f}đ]"
                    else:
                        status_tag = "⚪ [Chưa làm]"
                    prob_labels.append(f"Bài {idx_p+1}: {p['ten_bai']}  —  {status_tag}")

                curr_p_idx = st.session_state.get('current_student_problem_idx', 0)
                if curr_p_idx >= len(topic_probs):
                    curr_p_idx = 0
                    st.session_state['current_student_problem_idx'] = 0

                chosen_label = st.radio(
                    "🎯 Chọn bài tập trong chủ đề này để xem đề và nộp code:",
                    prob_labels,
                    index=curr_p_idx,
                    key=f"radio_prob_in_{curr_topic}"
                )
                new_p_idx = prob_labels.index(chosen_label)
                if new_p_idx != curr_p_idx:
                    st.session_state['current_student_problem_idx'] = new_p_idx
                    st.session_state['last_grade_result'] = None
                    st.rerun()

                prob = topic_probs[st.session_state['current_student_problem_idx']]
                
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
                
                prob_unique_key = f"{curr_topic}_{prob['ten_bai']}"
                editor_widget_key = f"txt_area_widget_{prob_unique_key}"
                if editor_widget_key not in st.session_state:
                    st.session_state[editor_widget_key] = ""

                file_tracker_key = f"last_uploaded_file_{prob_unique_key}"
                if file_tracker_key not in st.session_state:
                    st.session_state[file_tracker_key] = None

                col_up, col_edit = st.columns([1, 2])
                
                uploaded_code_direct = ""
                with col_up:
                    st.markdown("**Cách 1: Tải tệp mã nguồn (.cpp):**")
                    cpp_file = st.file_uploader("Chọn file .cpp từ máy tính:", type=["cpp", "c", "txt"], key=f"uploader_{prob_unique_key}")
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
                    
                    st.button(
                        "🗑️ XOÁ SẠCH KHUNG CODE",
                        type="secondary",
                        on_click=clear_code_callback,
                        args=(editor_widget_key, file_tracker_key),
                        key=f"clear_btn_{prob_unique_key}"
                    )

                final_code_to_grade = pasted_code.strip() if pasted_code.strip() else uploaded_code_direct.strip()

                btn_submit = st.button("🚀 CHẤM BÀI & PHÂN TÍCH THUẬT TOÁN", type="primary", width="stretch")

                if btn_submit:
                    if not final_code_to_grade:
                        st.error("⚠️ Khung mã nguồn đang trống! Em hãy dán code C++ hoặc tải file lên trước khi bấm Chấm bài.")
                    elif not GEMINI_API_KEY:
                        st.error("⚠️ Hệ thống chưa cấu hình `GEMINI_API_KEY`!")
                    else:
                        io_m = prob.get("io_mode", "cin/cout")
                        f_in = prob.get("file_inp", "BAILAM.INP")
                        f_out = prob.get("file_out", "BAILAM.OUT")
                        gen_script = prob.get("gen_code", "")
                        temp_files_to_clean = [
                            "teacher.cpp", "student.cpp",
                            "teacher.exec", "student.exec",
                            "teacher.exec.exe", "student.exec.exe",
                            f_in, f_out
                        ]

                        with st.spinner("⏳ Đang biên dịch code mẫu và sinh bộ 5 testcase tự động..."):
                            try:
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
                                        "chu_de": curr_topic,
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
                            finally:
                                cleanup_temp_files(temp_files_to_clean)

                if st.session_state['last_grade_result'] is not None:
                    res = st.session_state['last_grade_result']
                    st.markdown("---")
                    col_res_title, col_reset_btn = st.columns([3, 1])
                    
                    with col_res_title:
                        st.subheader("📊 BÁO CÁO KẾT QUẢ CHẤM MÁY & PHÂN TÍCH THUẬT TOÁN")
                    with col_reset_btn:
                        if st.button("🔄 LÀM LẠI / CHẤM LẠI BÀI NÀY", type="secondary", width="stretch"):
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
                        st.dataframe(res["test_details"], width="stretch")

                    st.markdown("### 💡 Gợi Ý Tối Ưu Từ Thầy AI:")
                    st.markdown(res['nhan_xet_ai'])

        with student_tab2:
            st.subheader(f"📊 Bảng Thống Kê Bài Làm Của Học Sinh: {student_id}")
            if len(user_subs) == 0:
                st.info("💡 Em chưa nộp bài tập nào. Hãy sang Tab '📂 Luyện Theo Đề Thi / Chủ Đề' để thử sức nhé!")
            else:
                st.markdown("### 🏆 Mã Nguồn & Kết Quả Tốt Nhất Trên Từng Bài:")
                best_data = [{
                    "Chủ Đề / Đề Thi": sub.get('chu_de', DEFAULT_TOPIC_NAME),
                    "Tên Bài Tập": sub['ten_bai'], 
                    "Điểm Số Cao Nhất": f"{sub['diem']:.1f}/10", 
                    "Thời Gian Chạy": sub['thoi_gian_chay'],
                    "Thời Gian Nộp Kỷ Lục": sub['thoi_gian_nop'],
                    "Trạng Thái": "🟢 Đạt điểm tối đa" if sub['diem']==10 else "🟡 Cần tối ưu thêm"
                } for sub in user_subs]
                st.dataframe(best_data, width="stretch")
                
                st.markdown("---")
                st.markdown("### 📜 Chi Tiết Báo Cáo Kỷ Lục Lời Giải Tốt Nhất:")
                for idx, sub in enumerate(user_subs):
                    with st.expander(f"📌 Bài {idx+1}: {sub['ten_bai']} — Điểm Kỷ Lục: {sub['diem']:.1f}/10 ({sub['thoi_gian_nop']})"):
                        st.write(f"**Chủ đề:** `{sub.get('chu_de', DEFAULT_TOPIC_NAME)}` | **Trạng thái:** `{sub['trang_thai']}` | **Thời gian chạy:** `{sub['thoi_gian_chay']}`")
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
        st.subheader("👨‍🏫 Bàn Làm Việc Giáo Viên — Quản Lý Đề Thi & Chuyên Đề")
        teacher_tabs = [
            "📂 Quản Lý Đề Thi & Chủ Đề", 
            "📚 Nhập File Đề Thi / Chuyên Đề", 
            "🗂️ Tạo Chủ Đề & Gom Bài Cũ",
            "✏️ Chỉnh Sửa Chi Tiết Bài", 
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

        # TAB 0: QUẢN LÝ ĐỀ THI & CHỦ ĐỀ (GOM NHÓM)
        if selected_tab == "📂 Quản Lý Đề Thi & Chủ Đề":
            st.markdown("### 📂 Ngân Hàng Đề Thi & Chuyên Đề Hiện Có")
            col_b1, col_b2, _ = st.columns([1.6, 1.6, 1.8])
            with col_b1:
                if st.button("📚 NHẬP FILE ĐỀ / CHUYÊN ĐỀ MỚI", type="primary", width="stretch"):
                    st.session_state['active_teacher_tab'] = 1
                    st.rerun()
            with col_b2:
                if st.button("🗂️ TẠO CHỦ ĐỀ TỪ BÀI CŨ", type="secondary", width="stretch"):
                    st.session_state['active_teacher_tab'] = 2
                    st.rerun()

            grouped_all = group_problems_by_topic(st.session_state['problems_db'])
            if len(grouped_all) == 0:
                st.info("Chưa có Đề thi hoặc Chuyên đề nào. Hãy bấm nút '📚 NHẬP FILE ĐỀ / CHUYÊN ĐỀ MỚI'!")

            for t_idx, (t_name, t_info) in enumerate(grouped_all.items()):
                items_in_topic = t_info["items"]
                visible_cnt = sum(1 for _, p in items_in_topic if p.get('is_visible', True))
                total_cnt = len(items_in_topic)
                
                if visible_cnt == total_cnt:
                    topic_status = f"🟢 ĐANG MỞ ({visible_cnt}/{total_cnt} bài)"
                elif visible_cnt == 0:
                    topic_status = f"🔒 ĐANG ẨN TOÀN BỘ ({total_cnt} bài)"
                else:
                    topic_status = f"🟡 MỞ MỘT PHẦN ({visible_cnt}/{total_cnt} bài)"

                with st.expander(f"📁 **{t_name}** [{t_info['loai_goi']}] — {topic_status}", expanded=True):
                    c_act_t1, c_act_t2, c_act_t3, c_act_t4 = st.columns([1.2, 1.2, 1.6, 1.2])
                    with c_act_t1:
                        if st.button("👁️ MỞ CẢ ĐỀ", key=f"show_all_topic_{t_idx}", width="stretch"):
                            for orig_idx, _ in items_in_topic:
                                st.session_state['problems_db'][orig_idx]['is_visible'] = True
                            db_save("problems", st.session_state['problems_db'])
                            st.toast(f"Đã mở công khai toàn bộ: {t_name}!", icon="👁️")
                            st.rerun()
                    with c_act_t2:
                        if st.button("🔒 ẨN CẢ ĐỀ", key=f"hide_all_topic_{t_idx}", width="stretch"):
                            for orig_idx, _ in items_in_topic:
                                st.session_state['problems_db'][orig_idx]['is_visible'] = False
                            db_save("problems", st.session_state['problems_db'])
                            st.toast(f"Đã ẩn toàn bộ: {t_name}!", icon="🔒")
                            st.rerun()
                    with c_act_t3:
                        new_t_rename = st.text_input("Đổi tên chủ đề:", value=t_name, key=f"rename_input_{t_idx}", label_visibility="collapsed")
                    with c_act_t4:
                        if st.button("💾 ĐỔI TÊN", key=f"rename_btn_{t_idx}", width="stretch"):
                            if new_t_rename.strip() and new_t_rename.strip() != t_name:
                                for orig_idx, _ in items_in_topic:
                                    st.session_state['problems_db'][orig_idx]['chu_de'] = sanitize_text(new_t_rename.strip())
                                db_save("problems", st.session_state['problems_db'])
                                st.toast("Đã đổi tên chủ đề thành công!", icon="✅")
                                st.rerun()

                    st.markdown("---")
                    for sub_i, (orig_idx, p) in enumerate(items_in_topic):
                        p_icon = "🟢" if p.get('is_visible', True) else "🔒"
                        col_p1, col_p2, col_p3 = st.columns([3.5, 0.8, 0.8])
                        with col_p1:
                            st.markdown(f"{p_icon} **Bài {sub_i+1}: {p['ten_bai']}** *(Input: `{p['file_inp']}` | Output: `{p['file_out']}`)*")
                        with col_p2:
                            if st.button("✏️ Sửa", key=f"edit_p_{orig_idx}", width="stretch"):
                                st.session_state['selected_problem_id'] = orig_idx
                                st.session_state['active_teacher_tab'] = 3
                                st.rerun()
                        with col_p3:
                            if st.button("🗑️ Xóa", key=f"del_p_{orig_idx}", width="stretch"):
                                removed_name = st.session_state['problems_db'][orig_idx]['ten_bai']
                                st.session_state['problems_db'].pop(orig_idx)
                                db_save("problems", st.session_state['problems_db'])
                                st.toast(f"Đã xóa bài: {removed_name}", icon="🗑️")
                                st.rerun()

        # TAB 1: NHẬP FILE ĐỀ THI / CHUYÊN ĐỀ (TÁCH HÀNG LOẠT)
        elif selected_tab == "📚 Nhập File Đề Thi / Chuyên Đề":
            st.markdown("### 📚 Tải Lên File Đề Thi Hoặc Chuyên Đề (Tự Động Tách Bài & Sinh Test)")
            st.info("💡 Tải lên 1 tệp (`.docx`, `.pdf`, `.txt`) gồm 3–4 bài (Đề thi) hoặc nhiều bài (Chuyên đề). Hệ thống sẽ gom toàn bộ vào chung **1 Chủ đề / Đề thi** để học sinh chọn luyện theo gói.")

            col_meta1, col_meta2 = st.columns([2.2, 1])
            with col_meta1:
                batch_topic_name = st.text_input("📌 Đặt Tên Đề Thi hoặc Chuyên Đề:", placeholder="Ví dụ: Đề thi thử HSG Tỉnh số 01  hoặc  Chuyên đề 2: Số học nguyên tố")
            with col_meta2:
                batch_pkg_type = st.selectbox("🏷️ Phân loại gói bài:", ["🏆 Đề thi / Đề luyện", "📚 Chuyên đề"])

            col_up_doc, col_opt_doc = st.columns([2, 1])
            with col_up_doc:
                topic_file = st.file_uploader("📂 Chọn tệp tài liệu (.docx, .pdf, .txt):", type=["docx", "pdf", "txt"], key="topic_file_uploader")
            with col_opt_doc:
                default_vis_batch = st.selectbox("👁️ Trạng thái sau khi lưu:", ["🔒 ẨN (Để thầy soát lại)", "👁️ HIỆN (Mở cho học sinh ngay)"], index=0)
                auto_gen_cpp = st.checkbox("🤖 Tự viết luôn Code C++ mẫu chuẩn", value=True)

            if topic_file is not None:
                if st.button("⚡ PHÂN TÍCH & TÁCH THÀNH CÁC BÀI TRONG GÓI", type="primary", width="stretch"):
                    if not GEMINI_API_KEY:
                        st.error("Chưa cấu hình GEMINI_API_KEY!")
                    else:
                        final_topic_label = batch_topic_name.strip()
                        if not final_topic_label:
                            base_name = os.path.splitext(topic_file.name)[0].replace("_", " ")
                            final_topic_label = f"{batch_pkg_type}: {base_name}"

                        with st.spinner("⏳ Đang đọc tệp và nhờ AI bóc tách từng bài, viết code C++ mẫu và bộ sinh test Python..."):
                            try:
                                if topic_file.name.endswith(".pdf"):
                                    raw_doc_text = extract_text_from_pdf(topic_file)
                                elif topic_file.name.endswith(".docx"):
                                    raw_doc_text = extract_text_from_docx(topic_file)
                                else:
                                    raw_doc_text = sanitize_text(topic_file.read().decode("utf-8", errors="ignore"))

                                cpp_instruction = """
                                [CODE_MAU]
                                Viết mã nguồn C++ hoàn chỉnh, tối ưu (dùng freopen nếu đọc/ghi tệp, dùng long long tránh tràn số) giải đúng 100% bài toán.
                                [/CODE_MAU]
                                """ if auto_gen_cpp else "[CODE_MAU][/CODE_MAU]"

                                batch_prompt = f"""
                                Bạn là chuyên gia ra đề thi Học sinh giỏi Tin học. Dưới đây là nội dung một đề thi hoặc tài liệu chuyên đề chứa NHIỀU BÀI TẬP.
                                Hãy đọc toàn bộ tài liệu, phân tách chính xác thành TỪNG BÀI TẬP ĐƠN LẺ.
                                Với MỖI BÀI TẬP, hãy xuất theo đúng khuôn mẫu thẻ phân tách sau (không dùng định dạng JSON):

                                ===BAI_MOI===
                                [TEN_BAI]Tên bài tập (VD: BÀI 1. TỔNG NGUYÊN TỐ)[/TEN_BAI]
                                [IO_MODE]Đọc/Ghi Tệp (.INP / .OUT) hoặc Nhập/Xuất Chuẩn (cin / cout)[/IO_MODE]
                                [FILE_INP]Tên file INP viết hoa (hoặc cin)[/FILE_INP]
                                [FILE_OUT]Tên file OUT viết hoa (hoặc cout)[/FILE_OUT]
                                [DE_BAI]
                                Toàn bộ nội dung mô tả đề bài, dữ liệu vào/ra, giới hạn (định dạng Markdown sạch sẽ, công thức toán học bọc trong dấu $...$). Không bao gồm phần ví dụ.
                                [/DE_BAI]
                                [SAMPLE_IN]Dữ liệu Input của ví dụ 1 (chỉ lấy dữ liệu thô)[/SAMPLE_IN]
                                [SAMPLE_OUT]Dữ liệu Output của ví dụ 1 (chỉ lấy dữ liệu thô)[/SAMPLE_OUT]
                                [GEN_CODE]
                                Viết mã nguồn Python thuần túy chứa hàm generate_test(test_id) trả về chuỗi String Input tương ứng giới hạn đề bài:
                                - test_id = 1: Giống hệt SAMPLE_IN
                                - test_id = 2: Test biên cực tiểu / trường hợp đặc biệt
                                - test_id = 3: Test ngẫu nhiên trung bình
                                - test_id = 4: Test bẫy thuật toán / số lớn
                                - test_id = 5: Test tối đa giới hạn N của đề bài
                                [/GEN_CODE]
                                {cpp_instruction}

                                [NỘI DUNG TÀI LIỆU]:
                                {raw_doc_text}
                                """

                                raw_ai_text = call_gemini_with_fallback(batch_prompt)
                                is_vis_flag = (default_vis_batch == "👁️ HIỆN (Mở cho học sinh ngay)")
                                cleaned_batch = parse_batch_problems_by_tags(raw_ai_text, is_vis_flag, final_topic_label, batch_pkg_type)

                                if len(cleaned_batch) == 0:
                                    st.error("⚠️ AI không tìm thấy bài tập rõ ràng nào trong tệp này. Thầy kiểm tra lại định dạng tệp nhé!")
                                else:
                                    st.session_state['batch_parsed_problems'] = cleaned_batch
                                    st.success(f"🎉 Đã bóc tách thành công **{len(cleaned_batch)} bài tập** vào gói **{final_topic_label}**!")
                            except Exception as e:
                                st.error(f"❌ Lỗi trong quá trình phân tích tệp: {e}")

            if len(st.session_state['batch_parsed_problems']) > 0:
                st.markdown("---")
                target_grp_name = st.session_state['batch_parsed_problems'][0]['chu_de']
                st.subheader(f"📋 Xem Trước {len(st.session_state['batch_parsed_problems'])} Bài Thuộc Gói: {target_grp_name}")
                
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
                            if st.button("🗑️ Bỏ", key=f"b_del_{idx}", help="Loại bỏ bài này khỏi gói"):
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
                    if st.button(f"💾 LƯU GÓI ({len(st.session_state['batch_parsed_problems'])} BÀI) VÀO FIREBASE", type="primary", width="stretch"):
                        start_id = len(st.session_state['problems_db'])
                        for offset, item in enumerate(st.session_state['batch_parsed_problems']):
                            item["id"] = start_id + offset
                            st.session_state['problems_db'].append(item)
                        
                        db_save("problems", st.session_state['problems_db'])
                        count_saved = len(st.session_state['batch_parsed_problems'])
                        st.session_state['batch_parsed_problems'] = []
                        st.session_state['active_teacher_tab'] = 0
                        st.toast(f"🎉 Đã lưu thành công gói {count_saved} bài tập vào Firebase!", icon="✅")
                        st.rerun()
                with col_clear_all:
                    if st.button("🧹 HỦY DANH SÁCH", type="secondary", width="stretch"):
                        st.session_state['batch_parsed_problems'] = []
                        st.rerun()

        # TAB 2: TẠO CHỦ ĐỀ & GOM BÀI CŨ
        elif selected_tab == "🗂️ Tạo Chủ Đề & Gom Bài Cũ":
            st.markdown("### 🗂️ Tạo Chủ Đề / Đề Thi Mới & Gom Các Bài Cũ Đã Lưu")
            st.info("💡 Chức năng này giúp thầy gom các bài tập đơn lẻ đã đăng trước đó vào chung một **Chủ đề** hoặc **Đề thi**. Sau khi gom, học sinh sẽ chỉ nhìn thấy Chủ đề / Đề thi mà không còn thấy bài đơn lẻ rời rạc.")

            all_probs = st.session_state['problems_db']
            if len(all_probs) == 0:
                st.warning("Hiện chưa có bài tập nào trong hệ thống.")
            else:
                existing_topics = sorted(list(set(get_prob_topic(p) for p in all_probs)))
                
                col_c_mode, col_c_type = st.columns([2, 1])
                with col_c_mode:
                    topic_action = st.radio("Chọn thao tác:", ["➕ Tạo tên Chủ đề / Đề thi mới", "📂 Thêm bài vào Chủ đề / Đề thi đã có"], horizontal=True)
                with col_c_type:
                    new_pkg_type = st.selectbox("Phân loại:", ["📚 Chuyên đề", "🏆 Đề thi / Đề luyện"], key="organize_pkg_type")

                if topic_action == "➕ Tạo tên Chủ đề / Đề thi mới":
                    target_topic_name = st.text_input("📌 Nhập tên Chủ đề / Đề thi mới:", placeholder="Ví dụ: Chuyên đề 1: Số học cơ bản  hoặc  Đề luyện tập số 01")
                else:
                    target_topic_name = st.selectbox("📂 Chọn Chủ đề / Đề thi đích:", existing_topics)

                st.markdown("#### ✅ Tích chọn các bài muốn đưa vào Chủ đề / Đề thi trên:")
                filter_unassigned = st.checkbox("Chỉ lọc hiển thị các bài chưa phân loại (nằm ở 'Bài tập Luyện tập Chung')", value=False)
                
                selected_indices = []
                for idx, p in enumerate(all_probs):
                    curr_t = get_prob_topic(p)
                    if filter_unassigned and curr_t != DEFAULT_TOPIC_NAME:
                        continue
                    
                    vis_lbl = "🟢 Đang mở" if p.get('is_visible', True) else "🔒 Đang ẩn"
                    chk = st.checkbox(
                        f"**{p['ten_bai']}** — *(Đang thuộc: `{curr_t}` | {vis_lbl})*",
                        key=f"chk_assign_prob_{idx}"
                    )
                    if chk:
                        selected_indices.append(idx)

                st.markdown("---")
                if st.button(f"💾 GOM {len(selected_indices)} BÀI ĐÃ CHỌN VÀO CHỦ ĐỀ / ĐỀ THI", type="primary", width="stretch"):
                    if not target_topic_name or not target_topic_name.strip():
                        st.error("⚠️ Thầy vui lòng nhập tên Chủ đề / Đề thi trước khi lưu!")
                    elif len(selected_indices) == 0:
                        st.error("⚠️ Thầy chưa tích chọn bài tập nào!")
                    else:
                        clean_topic = sanitize_text(target_topic_name.strip())
                        for idx in selected_indices:
                            st.session_state['problems_db'][idx]['chu_de'] = clean_topic
                            st.session_state['problems_db'][idx]['loai_goi'] = new_pkg_type
                        
                        db_save("problems", st.session_state['problems_db'])
                        st.toast(f"🎉 Đã gom {len(selected_indices)} bài vào '{clean_topic}'!", icon="✅")
                        st.session_state['active_teacher_tab'] = 0
                        st.rerun()

        # TAB 3: CHỈNH SỬA CHI TIẾT BÀI TRONG GÓI
        elif selected_tab == "✏️ Chỉnh Sửa Chi Tiết Bài":
            all_probs = st.session_state['problems_db']
            if len(all_probs) == 0:
                st.info("Chưa có bài tập nào trong hệ thống.")
            else:
                prob_select_labels = [f"[{get_prob_topic(p)}] — {p['ten_bai']}" for p in all_probs]
                default_edit_idx = st.session_state.get('selected_problem_id', 0)
                if default_edit_idx < 0 or default_edit_idx >= len(all_probs):
                    default_edit_idx = 0

                chosen_edit_lbl = st.selectbox("🎯 Chọn bài cần chỉnh sửa nội dung / code mẫu / sinh test:", prob_select_labels, index=default_edit_idx)
                edit_id = prob_select_labels.index(chosen_edit_lbl)
                curr_p = all_probs[edit_id]

                st.markdown("---")
                col_e1, col_e2, col_e3 = st.columns([2, 1.5, 1])
                with col_e1:
                    ten_bai_val = st.text_input("📌 Tên Bài Tập:", value=curr_p['ten_bai'])
                with col_e2:
                    chu_de_val = st.text_input("📂 Thuộc Chủ Đề / Đề Thi:", value=get_prob_topic(curr_p))
                with col_e3:
                    loai_goi_val = st.selectbox("🏷️ Loại Gói:", ["📚 Chuyên đề", "🏆 Đề thi / Đề luyện"], index=0 if get_prob_type(curr_p) == "📚 Chuyên đề" else 1)

                col_t2, col_t3, col_f1, col_f2 = st.columns([1.3, 1.2, 1, 1])
                with col_t2:
                    io_mode_val = st.selectbox("⚙️ Nhập / Xuất:", ["Đọc/Ghi Tệp (.INP / .OUT)", "Nhập/Xuất Chuẩn (cin / cout)"], index=0 if curr_p['io_mode'] == "Đọc/Ghi Tệp (.INP / .OUT)" else 1)
                with col_t3:
                    vis_option = st.selectbox("👁️ Hiển Thị:", ["👁️ HIỆN", "🔒 ẨN"], index=0 if curr_p.get('is_visible', True) else 1)
                    is_visible_val = (vis_option == "👁️ HIỆN")
                with col_f1:
                    file_inp_val = st.text_input("📥 Tệp Vào:", value=curr_p['file_inp']) if io_mode_val == "Đọc/Ghi Tệp (.INP / .OUT)" else "cin"
                with col_f2:
                    file_out_val = st.text_input("📤 Tệp Ra:", value=curr_p['file_out']) if io_mode_val == "Đọc/Ghi Tệp (.INP / .OUT)" else "cout"

                de_bai_val = st.text_area("📝 Nội dung Đề bài & Giới hạn:", value=curr_p['de_bai'], height=180)
                
                c1, c2 = st.columns(2)
                in_sample = c1.text_area("📥 Input Mẫu:", value=curr_p.get('sample_in_1', ''), height=85)
                out_sample = c2.text_area("📤 Output Mẫu:", value=curr_p.get('sample_out_1', ''), height=85)

                code_mau_val = st.text_area("💻 Code C++ Mẫu Chuẩn:", value=curr_p.get('code_mau', ''), height=180)

                gen_widget_key = f"gen_code_editor_{edit_id}"
                if gen_widget_key not in st.session_state:
                    st.session_state[gen_widget_key] = curr_p.get('gen_code', '')

                if st.button("🤖 NHỜ AI VIẾT LẠI MÃ PYTHON SINH TEST CHO BÀI NÀY", width="stretch"):
                    if not GEMINI_API_KEY:
                        st.error("Chưa cấu hình GEMINI_API_KEY!")
                    else:
                        with st.spinner("🤖 AI đang viết lại mã sinh test..."):
                            try:
                                ai_gen_prompt = f"""
                                Viết MÃ NGUỒN PYTHON chứa hàm `generate_test(test_id)` trả về chuỗi String Input tương ứng:
                                - test_id = 1: Test ví dụ mẫu nhỏ
                                - test_id = 2: Test biên cực tiểu
                                - test_id = 3: Test ngẫu nhiên trung bình
                                - test_id = 4: Test đặc biệt / bẫy thuật toán
                                - test_id = 5: Test tối đa giới hạn N của đề bài

                                [ĐỀ BÀI]: {de_bai_val}
                                [INPUT MẪU]: {in_sample}

                                CHỈ TRẢ VỀ DUY NHẤT ĐOẠN CODE PYTHON:
                                """
                                raw_text = call_gemini_with_fallback(ai_gen_prompt)
                                code_cleaned = raw_text.replace("```python", "").replace("```", "").strip()
                                st.session_state[gen_widget_key] = code_cleaned
                                st.toast("✅ Đã cập nhật mã sinh test!", icon="🤖")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Lỗi gọi AI: {e}")

                gen_code_val = st.text_area("⚙️ Mã nguồn Python sinh Test:", key=gen_widget_key, height=200)

                if st.button("💾 LƯU THAY ĐỔI BÀI TẬP VÀO FIREBASE", type="primary", width="stretch"):
                    st.session_state['problems_db'][edit_id] = {
                        "id": edit_id,
                        "ten_bai": sanitize_text(ten_bai_val),
                        "chu_de": sanitize_text(chu_de_val.strip() or DEFAULT_TOPIC_NAME),
                        "loai_goi": loai_goi_val,
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
                    db_save("problems", st.session_state['problems_db'])
                    if gen_widget_key in st.session_state:
                        del st.session_state[gen_widget_key]
                    st.toast("🎉 Đã lưu thay đổi bài tập thành công!", icon="✅")
                    st.session_state['active_teacher_tab'] = 0
                    st.rerun()

        # TAB 4: QUẢN LÝ TÀI KHOẢN HỌC SINH
        elif selected_tab == "👥 Quản Lý Tài Khoản Học Sinh":
            st.markdown("### 👤 Quản Lý Tài Khoản Học Sinh Nội Bộ (Đồng Bộ Đám Mây)")
            col_add_acc, col_edit_acc = st.columns([1, 1])
            with col_add_acc:
                st.caption("➕ **Tạo Tài Khoản Học Sinh Mới:**")
                new_u = st.text_input("Tên đăng nhập mới:", key="add_user")
                new_p = st.text_input("Mật khẩu mới:", type="password", key="add_pass")
                if st.button("🔑 CẤP TÀI KHOẢN MỚI", type="primary", width="stretch"):
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
                        if st.button("💾 ĐỔI MẬT KHẨU", width="stretch"):
                            st.session_state['student_accounts'][selected_acc] = sanitize_text(mod_pass)
                            db_save("accounts", st.session_state['student_accounts'])
                            st.toast(f"✅ Đã đổi mật khẩu cho {selected_acc}!", icon="🔑")
                            st.rerun()
                    with c_btn2:
                        if st.button(f"🗑️ XÓA {selected_acc}", type="secondary", width="stretch"):
                            del st.session_state['student_accounts'][selected_acc]
                            db_save("accounts", st.session_state['student_accounts'])
                            st.toast(f"🗑️ Đã xóa tài khoản {selected_acc}!", icon="🎉")
                            st.rerun()

            st.markdown("---")
            st.caption("📋 **Danh sách tất cả tài khoản học sinh đã cấp:**")
            acc_data = [{"STT": idx+1, "Tên Đăng Nhập": u, "Mật Khẩu": p} for idx, (u, p) in enumerate(st.session_state['student_accounts'].items())]
            st.dataframe(acc_data, width="stretch")

        # TAB 5: CẤU HÌNH VINH DANH & THỐNG KÊ
        else:
            st.markdown("### ⚙️ Cấu Hình Vinh Danh Trang Chủ & Báo Cáo Thống Kê")
            all_subs = db_get("submissions", st.session_state['submissions_db'])
            if not isinstance(all_subs, dict):
                all_subs = {}
            st.session_state['submissions_db'] = all_subs
            
            col_cfg1, col_cfg2 = st.columns([2, 1])
            with col_cfg1:
                st.caption("🏆 **Cấu hình Bảng Vinh Danh Học Sinh Tích Cực ở Trang Chủ:**")
                current_top = st.session_state.get('top_display_count', 3)
                new_top_count = st.number_input("Số lượng Top học sinh hiển thị ở Trang chủ (Ví dụ: 2, 3, 4, 5...):", min_value=1, max_value=10, value=current_top)
            with col_cfg2:
                st.write(""); st.write("")
                if st.button("💾 LƯU CẤU HÌNH VINH DANH", type="primary", width="stretch"):
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
                        if not isinstance(st_subs, list):
                            continue
                        best_by_prob = {}
                        for s in st_subs:
                            if not isinstance(s, dict):
                                continue
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
                    st.dataframe(lb_display, width="stretch")

            elif "2. 👤 Thống kê" in stat_mode:
                st.markdown("### 👤 Báo Cáo Kỷ Lục Lời Giải Của Học Sinh")
                all_student_list = list(st.session_state['student_accounts'].keys())
                if len(all_student_list) == 0:
                    st.info("Chưa có tài khoản học sinh nào được cấp.")
                else:
                    selected_st = st.selectbox("🎯 Chọn Học Sinh Cần Kiểm Tra:", all_student_list)
                    st_subs = all_subs.get(selected_st, [])
                    if not isinstance(st_subs, list):
                        st_subs = []
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
                        summary_table = [{"Chủ Đề": info.get('chu_de', DEFAULT_TOPIC_NAME), "Tên Bài Tập": info['ten_bai'], "Điểm Cao Nhất": f"{info['diem']:.1f}/10", "Thời Gian Chạy": info.get('thoi_gian_chay', 'N/A'), "Thời Gian Nộp": info.get('thoi_gian_nop', 'N/A')} for info in st_subs]
                        st.dataframe(summary_table, width="stretch")
                        
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
                        if not isinstance(sub_list, list):
                            continue
                        prob_subs = [s for s in sub_list if isinstance(s, dict) and s.get('ten_bai') == selected_prob_title]
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
                        st.dataframe(table_display, width="stretch")
                        
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
