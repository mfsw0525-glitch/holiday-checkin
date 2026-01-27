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
    if st.session_state.get("password_correct", False):
        return True
    
    st.markdown("## 🔒 请输入家庭暗号")
    password_input = st.text_input("密码", type="password")
    
    if password_input:
        correct_password = None
        # 智能查找密码位置
        if "feishu" in st.secrets and "APP_PASSWORD" in st.secrets["feishu"]:
            correct_password = st.secrets["feishu"]["APP_PASSWORD"]
        elif "APP_PASSWORD" in st.secrets:
            correct_password = st.secrets["APP_PASSWORD"]
            
        if correct_password is None:
            st.error("⚠️ 配置错误：在 Secrets 中找不到 APP_PASSWORD。")
            return False

        if str(password_input) == str(correct_password):
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("❌ 暗号不对哦")
            
    return False

if not check_password():
    st.stop()

# ================= 🚀 核心功能区 =================

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
                    "id": record_id, "time": fields.get("时间段", "全天"),
                    "title": task_title, "tag": fields.get("标签", "其他"),
                    "coins": coins_val, "status": task_status
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

def background_sync(token, record_id, new_status, title, coins, send_msg):
    try:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
        requests.put(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"fields": {"状态": new_status}})
    except: pass
    if send_msg and WEBHOOK_URL and "hook" in WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, headers={"Content-Type": "application/json"}, json={
                "msg_type": "text", "content": {"text": f"🎉 打卡播报：宝贝完成了【{title}】！\n💰 金币：{coins}"}
            })
        except: pass

# ================= 界面构建 =================

st.markdown("""
<style>
    /* 全局背景 */
    .stApp {background-color: #FFF0F5;}
    
    /* 🔥🔥🔥 隐藏官方 UI 元素 🔥🔥🔥 */
    /* 隐藏右上角菜单 */
    #MainMenu {visibility: hidden;}
    /* 隐藏底部 "Hosted with Streamlit" */
    footer {visibility: hidden;}
    /* 隐藏顶部红条 (如果有) */
    header {visibility: hidden;}
    /* 隐藏右下角 "Manage app" 按钮 */
    .stDeployButton {display: none;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}

    /* 卡片和按钮样式 */
    .task-card {background-color: white; border-radius: 12px; padding: 15px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); transition: transform 0.2s;}
    .task-card:hover {transform: scale(1.01);}
    
    .stat-box {border-radius: 15px; padding: 10px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.08); margin-bottom: 12px; width: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center;}
    .stat-num {font-size: 28px; font-weight: 900; margin-bottom: 2px; line-height: 1;}
    .stat-label {font-size: 13px; font-weight: bold; opacity: 0.9;}
    
    .big-date {font-size: 28px; font-weight: bold; color: #333; margin-bottom: 5px;}
    .big-week {font-size: 20px; font-weight: bold; color: #666; margin-bottom: 20px;}
    
    .total-coins-box {
        background: linear-gradient(135deg, #FFD700 0%, #FF8C00 100%);
        border-radius: 20px; padding: 20px; text-align: center; color: white;
        box-shadow: 0 6px 15px rgba(255, 140, 0, 0.4); margin-bottom: 25px;
    }
    .total-coins-num {font-size: 48px; font-weight: 900; text-shadow: 2px 2px 4px rgba(0,0,0,0.2);}
    .total-coins-label {font-size: 16px; font-weight: bold;}

    /* 按钮样式 */
    div.stButton > button[kind="secondary"] {background-color: #FFD700; color: #333; border: none; font-weight: 900;}
    div.stButton > button[kind="secondary"]:hover {background-color: #FFC107; color: black;}
    div.stButton > button[kind="primary"] {background-color: #4CAF50; color: white; border: none; font-weight: 900;}
    div.stButton > button[kind="primary"]:disabled {background-color: #4CAF50; color: white; opacity: 0.6;}
    .stButton>button {border-radius: 50px; height: 45px; box-shadow: 0 3px 6px rgba(0,0,0,0.1);}
</style>
""", unsafe_allow_html=True)

if 'token' not in st.session_state: st.session_state.token = get_tenant_access_token()
if 'tasks_data' not in st.session_state: st.session_state.tasks_data = fetch_todays_tasks(st.session_state.token)
if 'total_coins_history' not in st.session_state: st.session_state.total_coins_history = fetch_total_coins(st.session_state.token)

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

    def on_click(idx, rid, status, title, coins):
        new = "进行中" if status == "待开始" else ("已完成" if status == "进行中" else "")
        if new:
            st.session_state.tasks_data[idx]['status'] = new
            if new == "已完成":
                st.session_state.total_coins_history += coins
                st.balloons()
            threading.Thread(target=background_sync, args=(st.session_state.token, rid, new, title, coins, new=="已完成")).start()
            # 🔥 这里的 st.rerun() 已经被移除，解决了黄色报错问题
            # Streamlit 会在回调结束后自动刷新，所以无需手动调用

    for i, t in enumerate(tasks):
        s = t['status']
        color = "#4CAF50" if s == '已完成' else ("#FFC107" if s == '进行中' else "#E0E0E0")
        bg = "#E8F5E9" if s == '已完成' else ("#FFFDE7" if s == '进行中' else "white")
        with st.container():
            c_card, c_btn = st.columns([3, 1])
            with c_card:
                st.markdown(f"""<div class="task-card" style="border-left:6px solid {color}; background:{bg};"><div style="display:flex; justify-content:space-between; align-items:center;"><div><span style="font-size:12px; color:#666; background:rgba(255,255,255,0.8); padding:2px 8px; border-radius:10px;">⏰ {t['time']}</span><span style="font-size:12px; color:#555; margin-left:5px; font-weight:bold;">{t['tag']}</span><h4 style="margin:8px 0 0 0; color:#333; font-size:18px;">{t['title']}</h4></div><div style="text-align:right;"><div style="background:{color}; color:white; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:bold;">+{t['coins']} 💰</div></div></div></div>""", unsafe_allow_html=True)
            with c_btn:
                st.write(""); st.write("")
                if s == "待开始": 
                    st.button("🚀 开始", key=t['id'], on_click=on_click, args=(i,t['id'],s,t['title'],t['coins']), type="secondary", use_container_width=True)
                elif s == "进行中": 
                    st.button("🏁 完成", key=t['id'], on_click=on_click, args=(i,t['id'],s,t['title'],t['coins']), type="primary", use_container_width=True)
                elif s == "已完成": 
                    st.button("✅ 已完", key=t['id'], disabled=True, use_container_width=True, type="primary")