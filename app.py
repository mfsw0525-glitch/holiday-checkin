import streamlit as st
import requests
import datetime
import time
import re
import threading

# 1. 页面配置
st.set_page_config(
    page_title="寒假打卡大冒险", 
    page_icon="🍄", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# ================= 🔐 门卫系统 =================

def check_password():
    correct_password = None
    try:
        if "feishu" in st.secrets and "APP_PASSWORD" in st.secrets["feishu"]:
            correct_password = str(st.secrets["feishu"]["APP_PASSWORD"])
        elif "APP_PASSWORD" in st.secrets:
            correct_password = str(st.secrets["APP_PASSWORD"])
    except:
        st.error("⚠️ 未配置 APP_PASSWORD")
        return False

    params = st.query_params
    if params.get("code") == correct_password:
        return True
    
    st.markdown("""
<style>
    [data-testid="stForm"] .stFormSubmitButton {
        display: flex; justify-content: center; margin-top: 30px;
    }
    [data-testid="stForm"] .stFormSubmitButton button {
        width: 80% !important; height: 60px !important;
        font-size: 24px !important; font-weight: 900 !important;
        border-radius: 35px !important; background-color: #4CAF50 !important;
        color: white !important; border: none !important;
        box-shadow: 0 5px 15px rgba(76, 175, 80, 0.4) !important;
        transition: all 0.3s ease !important;
    }
    [data-testid="stForm"] .stFormSubmitButton button:hover {
        background-color: #45a049 !important; transform: scale(1.03) !important;
    }
    /* 隐藏多余UI */
    header, footer {visibility: hidden !important; display: none !important; height: 0px !important;}
    .stApp > footer {display: none !important; opacity: 0 !important;}
    #MainMenu {visibility: hidden !important; display: none !important;}
    div[class*="viewerBadge"] {display: none !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important; display: none !important;}
    [data-testid="stToolbar"] {visibility: hidden !important; display: none !important;}
    [data-testid="stDecoration"] {visibility: hidden !important; display: none !important;}
</style>
""", unsafe_allow_html=True)

    st.markdown("## 🔒 请输入家庭暗号")
    st.markdown("---")
    
    with st.form("login_form"):
        password_input = st.text_input("密码", type="password")
        submit = st.form_submit_button("🛡️ 点击登录") 
        
    if submit:
        if str(password_input) == correct_password:
            st.query_params["code"] = correct_password
            st.success("✅ 登录成功！")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("❌ 暗号不对哦")
            return False
            
    return False

if not check_password():
    st.stop()

# ================= 🚀 核心配置区 =================

try:
    def get_secret(key):
        if "feishu" in st.secrets and key in st.secrets["feishu"]:
            return st.secrets["feishu"][key]
        elif key in st.secrets:
            return st.secrets[key]
        return None

    APP_ID = get_secret("APP_ID")
    APP_SECRET = get_secret("APP_SECRET")
    APP_TOKEN = get_secret("APP_TOKEN")
    TABLE_ID = get_secret("TABLE_ID")
    WEBHOOK_URL = get_secret("WEBHOOK_URL")
    
    if not APP_ID: raise Exception("Missing Config")

except Exception as e:
    st.error(f"❌ 配置读取失败: {e}")
    st.stop()

# ================= 工具函数 =================

def get_beijing_today():
    utc_now = datetime.datetime.utcnow()
    return (utc_now + datetime.timedelta(hours=8)).date()

def get_chinese_weekday(date_obj):
    return ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][date_obj.weekday()]

def get_tenant_access_token():
    try:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        r = requests.post(url, headers={"Content-Type": "application/json"}, json={"app_id": APP_ID, "app_secret": APP_SECRET})
        return r.json().get("tenant_access_token")
    except: return None

def parse_single_time_str(s):
    s = s.replace("：", ":").replace("点", ":").replace("分", "")
    parts = re.findall(r"\d+", s)
    if not parts: return 0
    h = int(parts[0])
    m = 0
    if len(parts) >= 2: m = int(parts[1])
    elif "半" in s: m = 30
    return h * 60 + m

def parse_duration_minutes(time_str):
    try:
        parts = str(time_str).split('-')
        if len(parts) != 2: return 60
        start_min = parse_single_time_str(parts[0])
        end_min = parse_single_time_str(parts[1])
        duration = end_min - start_min
        return duration if duration > 0 else 60
    except: return 60

def fetch_total_coins(token):
    if not token: return 0
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"page_size": 500} 
    try:
        r = requests.get(url, headers=headers, params=params)
        items = r.json().get("data", {}).get("items", [])
        total = 0
        for item in items:
            fields = item['fields']
            if fields.get("状态", "") == "已完成":
                try: total += int(fields.get("金币值", 0))
                except: pass
        return total
    except: return 0

def fetch_todays_tasks(token):
    if not token: return []
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    target_date = get_beijing_today()
    target_str_dash = target_date.strftime("%Y-%m-%d") 
    target_str_slash = target_date.strftime("%Y/%m/%d")

    try:
        r = requests.get(url, headers=headers, params={"page_size": 100})
        raw_items = r.json().get("data", {}).get("items", [])
        clean_tasks = []
        for item in raw_items:
            fields = item['fields']
            record_id = item['record_id']
            task_title = fields.get("任务名称", "未知")
            task_status = fields.get("状态", "待开始")
            task_date_val = fields.get("日期", 0)
            start_ts = fields.get("实际开始时间", 0) 
            
            is_match = False
            if isinstance(task_date_val, int):
                utc_dt = datetime.datetime.utcfromtimestamp(task_date_val / 1000)
                if (utc_dt + datetime.timedelta(hours=8)).date() == target_date: is_match = True
            elif isinstance(task_date_val, str):
                if target_str_dash in task_date_val or target_str_slash in task_date_val: is_match = True
            
            if is_match:
                try: coins_val = int(fields.get("金币值", 0))
                except: coins_val = 0
                clean_tasks.append({
                    "id": record_id, 
                    "time": fields.get("时间段", "全天"),
                    "title": task_title, 
                    "tag": fields.get("标签", "其他"),
                    "coins": coins_val, 
                    "status": task_status,
                    "start_ts": start_ts
                })
        def parse_time(t):
            try:
                nums = re.findall(r"\d+", str(t).split('-')[0])
                if not nums: return 9999
                h = int(nums[0])
                m = 30 if '半' in str(t) else (int(nums[1]) if len(nums)>1 else 0)
                return h * 60 + m
            except: return 9999
        clean_tasks.sort(key=lambda x: parse_time(x['time']))
        return clean_tasks
    except: return []

def sync_to_feishu_direct(token, record_id, new_status, title, coins, send_msg, actual_minutes=0, limit_minutes=0, is_timeout=False, start_ts=None):
    try:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
        payload = {"fields": {"状态": new_status}}
        if new_status == "进行中" and start_ts:
             payload["fields"]["实际开始时间"] = start_ts
        if is_timeout: 
            payload["fields"]["金币值"] = coins
        
        requests.put(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload)
        
        if send_msg and WEBHOOK_URL and "hook" in WEBHOOK_URL:
            msg = f"🎉 打卡播报：宝贝完成了【{title}】！\n💰 获得金币：{coins}"
            if is_timeout: msg += f"\n⚠️ 注意：用时 {actual_minutes}分钟 (限时{limit_minutes}分钟)，超时扣除一半金币。"
            requests.post(WEBHOOK_URL, headers={"Content-Type": "application/json"}, json={"msg_type": "text", "content": {"text": msg}})
    except:
        pass

# 🔥🔥🔥 修复版：使用占位符 (placeholder) 实现自动消失 🔥🔥🔥
def show_big_popup(msg, is_bad=False):
    color = "#FF9800" if is_bad else "#4CAF50" # 橙色坏消息，绿色好消息
    icon = "📉" if is_bad else "🎉"
    
    # 1. 创建一个空盒子
    popup_box = st.empty()
    
    # 2. 把弹窗画在盒子里
    popup_box.markdown(f"""
<style>
    .popup-overlay {{
        position: fixed;
        top: 0; left: 0; width: 100%; height: 100%;
        background: rgba(0,0,0,0.5);
        z-index: 99999;
        display: flex; justify-content: center; align-items: center;
    }}
    .popup-box {{
        background: {color};
        padding: 40px;
        border-radius: 20px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        text-align: center;
        width: 80%;
        max-width: 600px;
        animation: popIn 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }}
    .popup-icon {{ font-size: 80px; display: block; margin-bottom: 20px; }}
    .popup-text {{ color: white; font-size: 28px; font-weight: bold; line-height: 1.5; white-space: pre-wrap; }}
    
    @keyframes popIn {{
        0% {{ transform: scale(0.5); opacity: 0; }}
        100% {{ transform: scale(1); opacity: 1; }}
    }}
</style>

<div class="popup-overlay">
    <div class="popup-box">
        <div class="popup-icon">{icon}</div>
        <div class="popup-text">{msg}</div>
    </div>
</div>
""", unsafe_allow_html=True)
    
    # 3. 停留3秒
    time.sleep(3)
    
    # 4. 🔥 关键一步：把盒子清空！弹窗就会消失了
    popup_box.empty()

# ================= 界面构建 =================

st.markdown("""
<style>
    .stApp {background-color: #FFF0F5;}
    .task-card {background-color: white; border-radius: 12px; padding: 15px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); transition: transform 0.2s;}
    .task-card:hover {transform: scale(1.01);}
    .stat-box {border-radius: 15px; padding: 10px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.08); margin-bottom: 12px; width: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center;}
    .stat-num {font-size: 28px; font-weight: 900; margin-bottom: 2px; line-height: 1;}
    .stat-label {font-size: 13px; font-weight: bold; opacity: 0.9;}
    .big-date {font-size: 28px; font-weight: bold; color: #333; margin-bottom: 5px;}
    .big-week {font-size: 20px; font-weight: bold; color: #666; margin-bottom: 20px;}
    .total-coins-box {background: linear-gradient(135deg, #FFD700 0%, #FF8C00 100%); border-radius: 20px; padding: 20px; text-align: center; color: white; box-shadow: 0 6px 15px rgba(255, 140, 0, 0.4); margin-bottom: 25px;}
    .total-coins-num {font-size: 48px; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.2);}
    .total-coins-label {font-size: 16px; font-weight: bold;}
    div.stButton > button[kind="secondary"] {background-color: #FFD700; color: #333; border: none; font-weight: 900;}
    div.stButton > button[kind="secondary"]:hover {background-color: #FFC107; color: black;}
    div.stButton > button[kind="primary"] {background-color: #4CAF50; color: white; border: none; font-weight: 900;}
    div.stButton > button[kind="primary"]:disabled {background-color: #4CAF50; color: white; opacity: 0.6;}
    .stButton>button {border-radius: 50px; height: 45px; box-shadow: 0 3px 6px rgba(0,0,0,0.1);}
</style>
""", unsafe_allow_html=True)

if 'token' not in st.session_state: st.session_state.token = get_tenant_access_token()

if 'tasks_data' not in st.session_state: 
    st.session_state.tasks_data = fetch_todays_tasks(st.session_state.token)
if 'total_coins_history' not in st.session_state: 
    st.session_state.total_coins_history = fetch_total_coins(st.session_state.token)

tasks = st.session_state.tasks_data
total_history = st.session_state.total_coins_history
done = len([t for t in tasks if t['status'] == '已完成'])
todo = len([t for t in tasks if t['status'] == '待开始'])
coins_today = sum([t['coins'] for t in tasks if t['status'] == '已完成'])

col_left, col_right = st.columns([1, 2], gap="large")

with col_left:
    today = get_beijing_today()
    st.markdown(f'<div class="big-date">{today.strftime("%Y年%m月%d日")}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big-week">{get_chinese_weekday(today)}</div>', unsafe_allow_html=True)
    st.markdown(f"""<div class="total-coins-box"><div class="total-coins-num">{total_history}</div><div class="total-coins-label">🏆 历史总金币</div></div>""", unsafe_allow_html=True)
    st.markdown("#### 📊 今日进度")
    st.write("") 
    c_s1, c_s2 = st.columns(2)
    with c_s1: st.markdown(f"""<div class="stat-box" style="background:#E8F5E9; border:2px solid #4CAF50;"><div class="stat-num" style="color:#2E7D32;">{done}</div><div class="stat-label" style="color:#2E7D32;">✅ 已完成</div></div>""", unsafe_allow_html=True)
    with c_s2: st.markdown(f"""<div class="stat-box" style="background:#FFF3E0; border:2px solid #FF9800;"><div class="stat-num" style="color:#E65100;">{coins_today}</div><div class="stat-label" style="color:#E65100;">💰 今日获取</div></div>""", unsafe_allow_html=True)
    st.markdown(f"""<div class="stat-box" style="background:#F5F5F5; border:2px solid #9E9E9E;"><div class="stat-num" style="color:#757575;">{todo}</div><div class="stat-label" style="color:#757575;">⏳ 待开始</div></div>""", unsafe_allow_html=True)

with col_right:
    c_head, c_refresh = st.columns([5, 1])
    with c_head: st.markdown("## 📝 任务清单")
    with c_refresh: 
        if st.button("🔄"): 
            st.session_state.tasks_data = fetch_todays_tasks(st.session_state.token)
            st.session_state.total_coins_history = fetch_total_coins(st.session_state.token)
            st.rerun()
    
    if not tasks: st.info("👋 今天没有任务哦，快去飞书安排吧！")

    def on_click(idx, rid, status, title, coins, time_str, saved_start_ts):
        new = "进行中" if status == "待开始" else ("已完成" if status == "进行中" else "")
        if new:
            st.session_state.tasks_data[idx]['status'] = new
            
            if new == "进行中":
                current_ts = int(time.time() * 1000)
                st.session_state.tasks_data[idx]['start_ts'] = current_ts
                threading.Thread(target=sync_to_feishu_direct, args=(st.session_state.token, rid, new, title, coins, False, 0, 0, False, current_ts)).start()
                
            elif new == "已完成":
                start_ts_val = st.session_state.tasks_data[idx].get('start_ts') or saved_start_ts
                final_coins = coins
                is_timeout = False
                actual_minutes = 0
                limit_minutes = parse_duration_minutes(time_str)
                
                msg = ""
                
                if start_ts_val and start_ts_val > 0:
                    start_dt = datetime.datetime.fromtimestamp(start_ts_val / 1000)
                    end_dt = datetime.datetime.now()
                    duration = end_dt - start_dt
                    actual_minutes = int(duration.total_seconds() / 60)
                    if actual_minutes < 1: actual_minutes = 1
                    
                    if actual_minutes > limit_minutes:
                        is_timeout = True
                        final_coins = coins // 2
                        msg = f"📉 哎呀超时了！\n实际用时 {actual_minutes}分钟 > 限时 {limit_minutes}分钟\n获得金币减半 ({final_coins})"
                    else:
                        msg = f"恭喜你在规定时间内完成！\n实际用时 {actual_minutes}分钟 (限时 {limit_minutes}分钟)\n获得 {final_coins} 金币"
                else:
                    msg = f"恭喜完成任务！\n(无时间记录，按全额发放)\n获得 {final_coins} 金币"

                st.session_state.tasks_data[idx]['coins'] = final_coins
                st.session_state.total_coins_history += final_coins
                
                st.balloons()
                
                # 🔥 这里调用新的弹窗逻辑
                show_big_popup(msg, is_bad=is_timeout)
                
                threading.Thread(target=sync_to_feishu_direct, args=(st.session_state.token, rid, new, title, final_coins, True, actual_minutes, limit_minutes, is_timeout, None)).start()

    for i, t in enumerate(tasks):
        s = t['status']
        color = "#4CAF50" if s == '已完成' else ("#FFC107" if s == '进行中' else "#E0E0E0")
        bg = "#E8F5E9" if s == '已完成' else ("#FFFDE7" if s == '进行中' else "white")
        display_coins = t['coins']
        t_start_ts = t.get('start_ts', 0)
        
        with st.container():
            c_card, c_btn = st.columns([3, 1])
            with c_card:
                st.markdown(f"""<div class="task-card" style="border-left:6px solid {color}; background:{bg};"><div style="display:flex; justify-content:space-between; align-items:center;"><div><span style="font-size:12px; color:#666; background:rgba(255,255,255,0.8); padding:2px 8px; border-radius:10px;">⏰ {t['time']}</span><span style="font-size:12px; color:#555; margin-left:5px; font-weight:bold;">{t['tag']}</span><h4 style="margin:8px 0 0 0; color:#333; font-size:18px;">{t['title']}</h4></div><div style="text-align:right;"><div style="background:{color}; color:white; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:bold;">+{display_coins} 💰</div></div></div></div>""", unsafe_allow_html=True)
            with c_btn:
                st.write(""); st.write("")
                if s == "待开始": st.button("🚀 开始", key=t['id'], on_click=on_click, args=(i,t['id'],s,t['title'],t['coins'], t['time'], t_start_ts), type="secondary", use_container_width=True)
                elif s == "进行中": st.button("🏁 完成", key=t['id'], on_click=on_click, args=(i,t['id'],s,t['title'],t['coins'], t['time'], t_start_ts), type="primary", use_container_width=True)
                elif s == "已完成": st.button("✅ 已完", key=t['id'], disabled=True, use_container_width=True, type="primary")