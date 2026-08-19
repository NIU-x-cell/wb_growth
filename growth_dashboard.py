"""
WB运营人员成长分析看板
核心规则：运营业绩从入职日期起算
启动：streamlit run growth_dashboard.py
"""
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
from config import get_db_config
# ============================================================
# 页面配置
# ============================================================
st.set_page_config(
    page_title="WB运营人员成长分析看板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown("""
<style>
    .main-header { font-size: 28px; font-weight: bold; color: #1f3a5f; margin-bottom: 10px; }
    .section-title { font-size: 20px; font-weight: bold; color: #1f3a5f; margin: 20px 0 10px 0;
                     border-left: 4px solid #667eea; padding-left: 10px; }
    .sub-title { font-size: 16px; font-weight: 600; color: #2c3e50; margin: 12px 0 8px 0; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { height: 45px; border-radius: 8px 8px 0 0; font-weight: 600; }
</style>
""", unsafe_allow_html=True)
# ============================================================
# 数据库连接（缓存）
# ============================================================
@st.cache_resource
def get_engine():
    cfg = get_db_config()
    ssl_params = ""
    if cfg.get("ssl_verify_cert"):
        ssl_params = "&ssl_verify_cert=true&ssl_verify_identity=true"
    url = f"mysql+pymysql://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}?charset={cfg['charset']}{ssl_params}"
    return create_engine(url, pool_recycle=3600, pool_pre_ping=True)
@st.cache_data(ttl=300)
def run_query(sql):
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)
# ============================================================
# 数据加载
# ============================================================
def load_dimensions():
    sql = """
    SELECT DISTINCT department, manager, team_leader, operator, entry_date
    FROM wb_personnel
    WHERE department IS NOT NULL
    ORDER BY department, manager, team_leader
    """
    return run_query(sql)
def load_performance_data(start_date, end_date, dept=None, manager=None, team_leader=None):
    """加载业绩数据（按日汇总，仅入职后订单）
    口径说明：
    - total_sales / order_count = 全部订单（含退款、作废、cancel）
    - net_sales / net_order_count = 排除已退款 + 已作废 + 平台cancel
    """
    conditions = [
        "pay_time IS NOT NULL",
        "operator IS NOT NULL",
        f"DATE(pay_time) >= '{start_date}'",
        f"DATE(pay_time) <= '{end_date}'",
    ]
    if dept and dept != "全部":
        conditions.append(f"department = '{dept}'")
    if manager and manager != "全部":
        conditions.append(f"manager = '{manager}'")
    if team_leader and team_leader != "全部":
        conditions.append(f"team_leader = '{team_leader}'")
    where = " AND ".join(conditions)
    sql = f"""
    SELECT
        DATE(pay_time) AS stat_date,
        department, manager, team_leader, operator,
        MIN(entry_date) AS entry_date,
        MIN(days_since_entry) AS days_since_entry,
        COUNT(*) AS order_count,
        SUM(goods_amount) AS total_sales,
        SUM(CASE WHEN is_refund <> '是' AND order_status <> '已作废' AND platform_status <> 'cancel'
                 THEN goods_amount ELSE 0 END) AS net_sales,
        SUM(CASE WHEN is_refund <> '是' AND order_status <> '已作废' AND platform_status <> 'cancel'
                 THEN 1 ELSE 0 END) AS net_order_count,
        SUM(CASE WHEN is_refund = '是' THEN goods_amount ELSE 0 END) AS refund_amount,
        SUM(CASE WHEN is_refund = '是' THEN 1 ELSE 0 END) AS refund_count,
        SUM(CASE WHEN order_status = '已作废' THEN goods_amount ELSE 0 END) AS void_amount,
        SUM(CASE WHEN order_status = '已作废' THEN 1 ELSE 0 END) AS void_count,
        SUM(CASE WHEN platform_status = 'cancel' THEN goods_amount ELSE 0 END) AS cancel_amount,
        SUM(CASE WHEN platform_status = 'cancel' THEN 1 ELSE 0 END) AS cancel_count,
        SUM(goods_cost) AS total_cost,
        SUM(ad_fee) AS total_ad_fee,
        SUM(shipping_fee) AS total_shipping_fee,
        SUM(packaging_fee) AS total_packaging_fee
    FROM wb_orders
    WHERE {where}
    GROUP BY DATE(pay_time), department, manager, team_leader, operator
    ORDER BY stat_date
    """
    df = run_query(sql)
    if not df.empty:
        df['stat_date'] = pd.to_datetime(df['stat_date'])
        df['entry_date'] = pd.to_datetime(df['entry_date'])
    return df
def load_operator_entry_info():
    """加载运营接手店铺信息"""
    sql = """
    SELECT operator, department, manager, team_leader, entry_date, take_shop_date, position, shop_name
    FROM wb_personnel
    WHERE operator IS NOT NULL AND entry_date IS NOT NULL
    ORDER BY entry_date
    """
    df = run_query(sql)
    if not df.empty:
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        df['take_shop_date'] = pd.to_datetime(df['take_shop_date'])
        df['days_employed'] = (pd.Timestamp.now() - df['entry_date']).dt.days
    return df
# ============================================================
# 侧边栏筛选器
# ============================================================
def render_sidebar(dim_df):
    st.sidebar.markdown("### 🔍 筛选条件")
    departments = ["全部"] + sorted(dim_df['department'].dropna().unique().tolist())
    selected_dept = st.sidebar.selectbox("部门", departments, index=0)
    if selected_dept == "全部":
        managers = ["全部"] + sorted(dim_df['manager'].dropna().unique().tolist())
    else:
        managers = ["全部"] + sorted(dim_df[dim_df['department'] == selected_dept]['manager'].dropna().unique().tolist())
    selected_manager = st.sidebar.selectbox("主管", managers, index=0)
    tl_df = dim_df.copy()
    if selected_dept != "全部":
        tl_df = tl_df[tl_df['department'] == selected_dept]
    if selected_manager != "全部":
        tl_df = tl_df[tl_df['manager'] == selected_manager]
    team_leaders = ["全部"] + sorted(tl_df['team_leader'].dropna().unique().tolist())
    selected_tl = st.sidebar.selectbox("组长", team_leaders, index=0)
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📅 时间范围")
    date_range = run_query("SELECT MIN(DATE(pay_time)) as min_d, MAX(DATE(pay_time)) as max_d FROM wb_orders WHERE pay_time IS NOT NULL")
    min_date = pd.to_datetime(date_range.iloc[0]['min_d']).date()
    max_date = pd.to_datetime(date_range.iloc[0]['max_d']).date()
    default_start = max_date - timedelta(days=90)
    if default_start < min_date:
        default_start = min_date
    col1, col2 = st.sidebar.columns(2)
    with col1:
        start_date = st.date_input("开始日期", value=default_start, min_value=min_date, max_value=max_date)
    with col2:
        end_date = st.date_input("结束日期", value=max_date, min_value=min_date, max_value=max_date)
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📈 趋势粒度")
    granularity = st.sidebar.radio("聚合方式", ["按周", "按月", "按日"], index=0)
    return {
        'dept': selected_dept, 'manager': selected_manager,
        'team_leader': selected_tl, 'start_date': start_date,
        'end_date': end_date, 'granularity': granularity,
    }
def render_filter_bar(filters, dim_df):
    # 选了什么就显示什么；选了下级自动反查上级
    dept_display = filters['dept']
    mgr_display = filters['manager']
    tl_display = filters['team_leader']
    # 选了组长但部门/主管是全部，自动反查
    if filters['team_leader'] != "全部":
        tl_row = dim_df[dim_df['team_leader'] == filters['team_leader']]
        if not tl_row.empty:
            if filters['dept'] == "全部":
                dept_display = tl_row.iloc[0]['department']
            if filters['manager'] == "全部":
                mgr_display = tl_row.iloc[0]['manager']
    # 选了主管但部门是全部，自动反查
    if filters['manager'] != "全部" and filters['dept'] == "全部":
        mgr_row = dim_df[dim_df['manager'] == filters['manager']]
        if not mgr_row.empty:
            dept_display = mgr_row.iloc[0]['department']
    cols = st.columns(4)
    with cols[0]:
        st.metric("部门", dept_display)
    with cols[1]:
        st.metric("主管", mgr_display)
    with cols[2]:
        st.metric("组长", tl_display)
    with cols[3]:
        st.metric("时间范围", f"{filters['start_date']}\n~ {filters['end_date']}")
# ============================================================
# KPI卡片
# ============================================================
def render_kpi_cards(df):
    if df.empty:
        st.warning("当前筛选条件下无数据")
        return
    total_sales = df['total_sales'].sum()
    net_sales = df['net_sales'].sum()
    order_count = df['order_count'].sum()
    net_order_count = df['net_order_count'].sum()
    refund_count = df['refund_count'].sum()
    refund_rate = refund_count / order_count * 100 if order_count > 0 else 0
    avg_order_value = net_sales / net_order_count if net_order_count > 0 else 0
    operator_count = df['operator'].nunique()
    cols = st.columns(6)
    kpis = [
        ("总销售额", f"¥{total_sales:,.0f}", "#764ba2"),
        ("净销售额", f"¥{net_sales:,.0f}", "#667eea"),
        ("订单数", f"{order_count:,}", "#f093fb"),
        ("退款率", f"{refund_rate:.1f}%", "#f5576c"),
        ("客单价", f"¥{avg_order_value:,.1f}", "#4facfe"),
        ("活跃运营", f"{operator_count}人", "#43e97b"),
    ]
    for i, (label, value, color) in enumerate(kpis):
        with cols[i]:
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, {color} 0%, {color}cc 100%);
                        padding: 18px; border-radius: 12px; color: white; text-align: center;">
                <div style="font-size: 24px; font-weight: bold;">{value}</div>
                <div style="font-size: 13px; opacity: 0.9; margin-top: 4px;">{label}</div>
            </div>
            """, unsafe_allow_html=True)
# ============================================================
# 业绩成长波动图（核心）
# ============================================================
def aggregate_by_time(df, granularity):
    if df.empty:
        return df
    freq_map = {"按日": "D", "按周": "W", "按月": "ME"}
    freq = freq_map.get(granularity, "W")
    df_agg = df.set_index('stat_date').resample(freq).agg({
        'total_sales': 'sum', 'net_sales': 'sum', 'order_count': 'sum',
        'net_order_count': 'sum',
        'refund_count': 'sum', 'refund_amount': 'sum',
        'total_ad_fee': 'sum',
    }).reset_index()
    df_agg['refund_rate'] = df_agg['refund_count'] / df_agg['order_count'] * 100
    df_agg['avg_order_value'] = df_agg['net_sales'] / df_agg['net_order_count']
    return df_agg
def render_growth_trend(df, granularity):
    st.markdown('<div class="section-title">📈 业绩成长波动图</div>', unsafe_allow_html=True)
    df_agg = aggregate_by_time(df, granularity)
    if df_agg.empty:
        st.warning("无数据")
        return
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    # 蓝色柱状图：净销售额（核心指标）
    fig.add_trace(
        go.Bar(x=df_agg['stat_date'], y=df_agg['net_sales'], name='净销售额',
               marker_color='rgba(102, 126, 234, 0.75)',
               hovertemplate='日期: %{x}<br>净销售额: ¥%{y:,.0f}<extra></extra>'),
        secondary_y=False,
    )
    # 绿色折线：总销售额（参考，在上方可看到退款/作废损耗）
    fig.add_trace(
        go.Scatter(x=df_agg['stat_date'], y=df_agg['total_sales'], name='总销售额',
                   mode='lines+markers', line=dict(color='#00b894', width=3), marker=dict(size=8),
                   hovertemplate='日期: %{x}<br>总销售额: ¥%{y:,.0f}<extra></extra>'),
        secondary_y=False,
    )
    # 红色虚线：订单数（辅助参考，右轴）
    fig.add_trace(
        go.Scatter(x=df_agg['stat_date'], y=df_agg['order_count'], name='订单数',
                   mode='lines+markers', line=dict(color='#f5576c', width=2, dash='dot'), marker=dict(size=6),
                   hovertemplate='日期: %{x}<br>订单数: %{y:,.0f}<extra></extra>'),
        secondary_y=True,
    )
    if len(df_agg) > 1:
        df_agg['wow_growth'] = df_agg['net_sales'].pct_change() * 100
        for i, row in df_agg.iterrows():
            if i > 0 and pd.notna(row['wow_growth']):
                color = '#43e97b' if row['wow_growth'] >= 0 else '#f5576c'
                symbol = '+' if row['wow_growth'] >= 0 else ''
                fig.add_annotation(x=row['stat_date'], y=row['net_sales'],
                                   text=f"{symbol}{row['wow_growth']:.1f}%", showarrow=False,
                                   yshift=15, font=dict(size=10, color=color))
    fig.update_layout(title=f'业绩成长趋势（{granularity}，仅统计入职后订单）',
                      height=450, hovermode='x unified',
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                      margin=dict(l=10, r=10, t=60, b=10))
    fig.update_yaxes(title_text='金额（¥）', secondary_y=False, tickformat=',.0f')
    fig.update_yaxes(title_text='订单数', secondary_y=True)
    fig.update_xaxes(title_text='日期')
    st.plotly_chart(fig, use_container_width=True)
# ============================================================
# 入职成长曲线（新增核心功能）
# ============================================================
def render_entry_growth(df, entry_info_df):
    """以入职日为第0天，按入职天数聚合业绩，对比运营成长轨迹"""
    st.markdown('<div class="section-title">🚀 成长曲线（以接手店铺日为起点）</div>', unsafe_allow_html=True)
    if df.empty:
        st.warning("无数据")
        return
    operators = sorted(df['operator'].dropna().unique().tolist())
    if not operators:
        st.warning("无运营数据")
        return
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown('<div class="sub-title">选择运营对比成长轨迹</div>', unsafe_allow_html=True)
        op_sales = df.groupby('operator')['net_sales'].sum().sort_values(ascending=False)
        default_ops = op_sales.head(5).index.tolist()
        selected_ops = st.multiselect("运营（最多8人）", operators, default=default_ops,
                                      max_selections=8, key="entry_growth_ops")
        st.markdown('<div class="sub-title">成长曲线参数</div>', unsafe_allow_html=True)
        max_days = st.slider("展示入职后天数范围", 7, 120, 90, key="entry_max_days")
        curve_metric = st.radio("曲线指标", ["销售额", "累计销售额", "净销售额", "累计净销售额", "订单数"], index=0, key="entry_curve_metric")
    with col2:
        if selected_ops:
            df_entry = df[df['operator'].isin(selected_ops)].copy()
            df_entry['entry_week'] = (df_entry['days_since_entry'] // 7) * 7
            df_entry_agg = df_entry.groupby(['entry_week', 'operator']).agg(
                net_sales=('net_sales', 'sum'),
                total_sales=('total_sales', 'sum'),
                order_count=('order_count', 'sum'),
            ).reset_index()
            df_entry_agg = df_entry_agg[df_entry_agg['entry_week'] <= max_days]
            df_entry_agg = df_entry_agg.sort_values(['operator', 'entry_week'])
            df_entry_agg['cum_net_sales'] = df_entry_agg.groupby('operator')['net_sales'].cumsum()
            df_entry_agg['cum_total_sales'] = df_entry_agg.groupby('operator')['total_sales'].cumsum()
            y_col_map = {"净销售额": "net_sales", "累计净销售额": "cum_net_sales",
                         "销售额": "total_sales", "累计销售额": "cum_total_sales",
                         "订单数": "order_count"}
            y_col = y_col_map[curve_metric]
            fig = px.line(df_entry_agg, x='entry_week', y=y_col, color='operator',
                          markers=True, title=f'入职后{curve_metric}成长曲线',
                          labels={'entry_week': '入职后第N天', y_col: curve_metric, 'operator': '运营'})
            fig.update_layout(height=420, hovermode='x unified',
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                              margin=dict(l=10, r=10, t=50, b=10))
            fig.update_xaxes(dtick=7)
            if y_col in ['net_sales', 'cum_net_sales', 'total_sales', 'cum_total_sales']:
                fig.update_yaxes(tickformat=',.0f')
            st.plotly_chart(fig, use_container_width=True)
    # 入职阶段业绩分布
    if not df.empty:
        st.markdown('<div class="sub-title">📊 入职阶段业绩分布</div>', unsafe_allow_html=True)
        df_phase = df.copy()
        df_phase['entry_phase'] = pd.cut(
            df_phase['days_since_entry'],
            bins=[-1, 7, 14, 30, 60, 90, 999],
            labels=['0-7天(新人)', '8-14天', '15-30天', '31-60天', '61-90天', '90天以上']
        )
        phase_stats = df_phase.groupby('entry_phase', observed=True).agg(
            order_count=('order_count', 'sum'),
            total_sales=('total_sales', 'sum'),
            operators=('operator', 'nunique'),
        ).reset_index()
        phase_stats['avg_per_op'] = phase_stats['total_sales'] / phase_stats['operators']
        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(phase_stats, x='entry_phase', y='total_sales',
                         color='operators', text='total_sales',
                         title='各入职阶段销售额（颜色=活跃运营数）',
                         labels={'entry_phase': '入职阶段', 'total_sales': '销售额', 'operators': '运营数'})
            fig.update_traces(texttemplate='¥%{text:,.0f}', textposition='outside')
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=50, b=10), yaxis_tickformat=',.0f')
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            fig = px.bar(phase_stats, x='entry_phase', y='avg_per_op',
                         color='avg_per_op', color_continuous_scale='Blues',
                         title='各入职阶段人均销售额',
                         labels={'entry_phase': '入职阶段', 'avg_per_op': '人均销售额'})
            fig.update_layout(height=350, margin=dict(l=10, r=10, t=50, b=10),
                              yaxis_tickformat=',.0f', showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
# ============================================================
# 周度成长汇总（热力图 + 累计曲线 + 明细表）
# ============================================================
def render_weekly_growth_summary(df):
    """
    按入职周数汇总业绩：第1周、第2周、第3周...
    支持运营/组长/主管三个维度，组长和主管自动汇总名下所有运营
    可视化：热力图 + 累计成长曲线 + 周度明细表
    """
    st.markdown('<div class="section-title">📅 周度成长汇总（入职第N周业绩）</div>', unsafe_allow_html=True)
    if df.empty:
        st.warning("无数据")
        return
    # 控制栏
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 2])
    with col_ctrl1:
        dim = st.radio("汇总维度", ["运营", "组长", "主管"], horizontal=True, key="weekly_dim")
    dim_col = {"运营": "operator", "组长": "team_leader", "主管": "manager"}[dim]
    # 该维度下的总人数（用于slider最大值）
    total_dim_count = df[dim_col].nunique()
    with col_ctrl2:
        metric = st.radio("业绩指标", ["销售额", "净销售额", "订单数"], horizontal=True, key="weekly_metric")
    with col_ctrl3:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        show_top = st.slider("展示前N名（按入职时间排序）", 1, total_dim_count, min(20, total_dim_count), key="weekly_top")
    metric_col = {"销售额": "total_sales", "净销售额": "net_sales", "订单数": "order_count"}[metric]
    is_money = metric in ["销售额", "净销售额"]
    # 计算入职周数（第1周=入职0-6天，第2周=7-13天...）
    df_w = df.copy()
    df_w = df_w[df_w['days_since_entry'].notna()]
    df_w['entry_week'] = (df_w['days_since_entry'] // 7) + 1
    # 按维度+周数聚合
    weekly = df_w.groupby([dim_col, 'entry_week'])[metric_col].sum().reset_index()
    # 透视表：行=维度，列=周数
    pivot = weekly.pivot(index=dim_col, columns='entry_week', values=metric_col).fillna(0)
    if pivot.empty:
        st.warning("无周度数据")
        return
    max_week = int(pivot.columns.max())
    # 周数范围筛选
    week_range = st.slider("入职周数范围", 1, max_week, (1, min(12, max_week)), key="weekly_range")
    pivot = pivot.loc[:, week_range[0]:week_range[1]]
    # 按入职时间排序，取前N名
    pivot['合计'] = pivot.sum(axis=1)
    # 获取每个维度值对应的最早入职日期
    entry_date_map = df_w.groupby(dim_col)['entry_date'].min().to_dict()
    pivot['_entry_sort'] = pivot.index.map(entry_date_map)
    pivot = pivot.sort_values('_entry_sort', ascending=True).head(show_top)
    pivot = pivot.drop(columns='_entry_sort')
    # ===== 1. 热力图 =====
    st.markdown('<div class="sub-title">🔥 周度业绩热力图（颜色越深业绩越高）</div>', unsafe_allow_html=True)
    heat_data = pivot.drop(columns='合计')
    fig = go.Figure(data=go.Heatmap(
        z=heat_data.values,
        x=[f"第{int(c)}周" for c in heat_data.columns],
        y=heat_data.index,
        text=[[f"¥{v:,.0f}" if is_money else f"{int(v):,}" for v in row] for row in heat_data.values],
        texttemplate="%{text}",
        textfont={"size": 10},
        colorscale='Blues',
        hovertemplate='%{y}<br>%{x}<br>' + (f'{metric}: ¥%{{z:,.0f}}<extra></extra>' if is_money else f'{metric}: %{{z:,.0f}}<extra></extra>'),
        colorbar=dict(title=metric),
    ))
    fig.update_layout(
        height=max(350, len(heat_data) * 28),
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis=dict(side='top'),
    )
    st.plotly_chart(fig, use_container_width=True)
    # ===== 2. 周均业绩 & 成长率 =====
    st.markdown('<div class="sub-title">⚡ 周均业绩与环比成长率</div>', unsafe_allow_html=True)
    # 计算每个维度的周均业绩和最后一周/第一周增长率
    growth_stats = []
    for name in pivot.index:
        row_data = heat_data.loc[name]
        active_weeks = (row_data > 0).sum()
        total = row_data.sum()
        avg = total / active_weeks if active_weeks > 0 else 0
        first_week_val = row_data[row_data > 0].iloc[0] if (row_data > 0).any() else 0
        last_week_val = row_data[row_data > 0].iloc[-1] if (row_data > 0).any() else 0
        growth = ((last_week_val - first_week_val) / first_week_val * 100) if first_week_val > 0 else 0
        growth_stats.append({
            dim: name,
            '活跃周数': int(active_weeks),
            '周均业绩': avg,
            '首周业绩': first_week_val,
            '最近周业绩': last_week_val,
            '成长率(%)': growth,
        })
    growth_df = pd.DataFrame(growth_stats)
    # 排序选择器
    col_sort1, col_sort2 = st.columns([1, 1])
    with col_sort1:
        sort_col = st.selectbox("排序字段", ['周均业绩', '成长率(%)', '活跃周数', '首周业绩', '最近周业绩'], key="weekly_sort_col")
    with col_sort2:
        sort_order = st.radio("排序方式", ["降序", "升序"], horizontal=True, key="weekly_sort_order")
    growth_df = growth_df.sort_values(sort_col, ascending=(sort_order == "升序")).reset_index(drop=True)
    growth_df.index = growth_df.index + 1
    growth_df.index.name = '排名'
    display_growth = growth_df.copy()
    if is_money:
        display_growth['周均业绩'] = display_growth['周均业绩'].apply(lambda x: f"¥{x:,.0f}")
        display_growth['首周业绩'] = display_growth['首周业绩'].apply(lambda x: f"¥{x:,.0f}")
        display_growth['最近周业绩'] = display_growth['最近周业绩'].apply(lambda x: f"¥{x:,.0f}")
    display_growth['成长率(%)'] = display_growth['成长率(%)'].apply(lambda x: f"{'+' if x >= 0 else ''}{x:.1f}%")
    st.dataframe(display_growth, use_container_width=True)
# ============================================================
# 新人成长排名（新增）
# ============================================================
def render_newcomer_ranking(df, entry_info_df):
    """新人成长排名：入职30/60/90天累计业绩"""
    st.markdown('<div class="section-title">🏆 新人成长排名（按入职后固定天数）</div>', unsafe_allow_html=True)
    if df.empty:
        st.warning("无数据")
        return
    col1, col2 = st.columns([1, 3])
    with col1:
        rank_days = st.radio("排名口径（入职后N天累计）", [30, 60, 90], index=1, key="newcomer_days")
        rank_metric = st.radio("排名指标", ["销售额", "净销售额", "订单数"], index=0, key="newcomer_metric")
        total_ops = df['operator'].nunique()
        show_n = st.slider("展示前N名（按入职时间从早到晚）", 1, total_ops, min(20, total_ops), key="newcomer_show_n")
    df_new = df[df['days_since_entry'] <= rank_days].copy()
    if df_new.empty:
        st.warning(f"无入职{rank_days}天内的数据")
        return
    metric_col = {'销售额': 'total_sales', '净销售额': 'net_sales', '订单数': 'order_count'}[rank_metric]
    newcomer_rank = df_new.groupby('operator').agg(
        total_sales=('total_sales', 'sum'),
        net_sales=('net_sales', 'sum'),
        order_count=('order_count', 'sum'),
        entry_date=('entry_date', 'first'),
        department=('department', 'first'),
        manager=('manager', 'first'),
        team_leader=('team_leader', 'first'),
    ).reset_index()
    # 按入职时间从早到晚排序
    newcomer_rank = newcomer_rank.sort_values('entry_date', ascending=True).reset_index(drop=True)
    newcomer_rank = newcomer_rank.head(show_n)
    newcomer_rank.index = newcomer_rank.index + 1
    newcomer_rank.index.name = '序号'
    with col2:
        display = newcomer_rank[['operator', 'department', 'manager', 'team_leader', 'entry_date',
                                 'total_sales', 'net_sales', 'order_count']].copy()
        display.columns = ['运营', '部门', '主管', '组长', '入职日期', '销售额', '净销售额', '订单数']
        display['入职日期'] = display['入职日期'].dt.strftime('%Y-%m-%d')
        display['销售额'] = display['销售额'].apply(lambda x: f"¥{x:,.0f}")
        display['净销售额'] = display['净销售额'].apply(lambda x: f"¥{x:,.0f}")
        st.dataframe(display, use_container_width=True, height=420)
    fig = px.bar(newcomer_rank, x=metric_col, y='operator', orientation='h',
                 color=metric_col, color_continuous_scale='RdPu',
                 title=f'入职{rank_days}天{rank_metric}（按入职时间排序，前{show_n}名）',
                 labels={metric_col: rank_metric, 'operator': '运营'})
    fig.update_layout(height=max(400, show_n * 25), yaxis={'categoryorder': 'total ascending'},
                      margin=dict(l=10, r=10, t=50, b=10))
    if metric_col in ['total_sales', 'net_sales']:
        fig.update_xaxes(tickformat=',.0f')
    st.plotly_chart(fig, use_container_width=True)
# ============================================================
# 运营个人成长分析
# ============================================================
def render_operator_growth(df, entry_info_df, granularity):
    st.markdown('<div class="section-title">👤 运营个人成长分析</div>', unsafe_allow_html=True)
    if df.empty:
        st.warning("无数据")
        return
    op_summary = df.groupby('operator').agg(
        total_sales=('total_sales', 'sum'),
        net_sales=('net_sales', 'sum'),
        order_count=('order_count', 'sum'),
        refund_count=('refund_count', 'sum'),
        entry_date=('entry_date', 'first'),
    ).reset_index()
    op_summary['refund_rate'] = op_summary['refund_count'] / op_summary['order_count'] * 100
    op_summary = op_summary.sort_values('total_sales', ascending=False).reset_index(drop=True)
    op_summary.index = op_summary.index + 1
    op_summary.index.name = '排名'
    col1, col2 = st.columns([1, 1.5])
    with col1:
        st.markdown("**🏆 运营业绩排名**")
        display_df = op_summary[['operator', 'entry_date', 'total_sales', 'net_sales', 'order_count', 'refund_rate']].copy()
        display_df['entry_date'] = display_df['entry_date'].dt.strftime('%Y-%m-%d')
        display_df.columns = ['运营', '入职日期', '销售额', '净销售额', '订单数', '退款率(%)']
        display_df['销售额'] = display_df['销售额'].apply(lambda x: f"¥{x:,.0f}")
        display_df['净销售额'] = display_df['净销售额'].apply(lambda x: f"¥{x:,.0f}")
        display_df['退款率(%)'] = display_df['退款率(%)'].apply(lambda x: f"{x:.1f}%")
        st.dataframe(display_df[['运营', '入职日期', '销售额', '净销售额', '订单数', '退款率(%)']],
                     use_container_width=True, height=400)
    with col2:
        st.markdown("**📊 运营销售额对比**")
        fig = px.bar(op_summary.head(20), x='total_sales', y='operator', orientation='h',
                     color='total_sales', color_continuous_scale='Blues',
                     title='TOP20 运营销售额',
                     labels={'total_sales': '销售额', 'operator': '运营'})
        fig.update_layout(height=400, yaxis={'categoryorder': 'total ascending'},
                          margin=dict(l=10, r=10, t=40, b=10), xaxis_tickformat=',.0f')
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("**📈 运营成长波动对比**")
    operators = sorted(df['operator'].dropna().unique().tolist())
    default_ops = operators[:min(5, len(operators))]
    selected_ops = st.multiselect("选择运营对比（最多8人）", operators, default=default_ops,
                                  max_selections=8, key="op_trend_multiselect")
    if selected_ops:
        freq_map = {"按日": "D", "按周": "W", "按月": "ME"}
        freq = freq_map.get(granularity, "W")
        df_op = df[df['operator'].isin(selected_ops)].copy()
        df_op_agg = df_op.groupby([pd.Grouper(key='stat_date', freq=freq), 'operator'])['total_sales'].sum().reset_index()
        fig = px.line(df_op_agg, x='stat_date', y='total_sales', color='operator', markers=True,
                      title=f'运营销售额成长对比（{granularity}）',
                      labels={'total_sales': '销售额', 'stat_date': '日期', 'operator': '运营'})
        fig.update_layout(height=400, hovermode='x unified',
                          legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                          margin=dict(l=10, r=10, t=60, b=10), yaxis_tickformat=',.0f')
        st.plotly_chart(fig, use_container_width=True)
# ============================================================
# 组长维度成长分析
# ============================================================
def render_team_leader_growth(df, granularity):
    st.markdown('<div class="section-title">👥 组长团队成长分析</div>', unsafe_allow_html=True)
    if df.empty or df['team_leader'].isna().all():
        st.warning("无组长数据")
        return
    tl_summary = df.groupby('team_leader').agg(
        total_sales=('total_sales', 'sum'),
        net_sales=('net_sales', 'sum'),
        order_count=('order_count', 'sum'),
        operator=('operator', 'nunique'),
    ).reset_index()
    tl_summary.columns = ['组长', '销售额', '净销售额', '订单数', '运营人数']
    tl_summary = tl_summary.sort_values('销售额', ascending=False).reset_index(drop=True)
    tl_summary.index = tl_summary.index + 1
    tl_summary.index.name = '排名'
    col1, col2 = st.columns([1, 1.5])
    with col1:
        st.markdown("**🏆 组长团队业绩排名**")
        display_df = tl_summary.copy()
        display_df['销售额'] = display_df['销售额'].apply(lambda x: f"¥{x:,.0f}")
        display_df['净销售额'] = display_df['净销售额'].apply(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_df, use_container_width=True, height=350)
    with col2:
        st.markdown("**📊 组长团队销售额对比**")
        fig = px.bar(tl_summary, x='销售额', y='组长', orientation='h',
                     color='销售额', color_continuous_scale='Purples',
                     title='各组长团队销售额')
        fig.update_layout(height=350, yaxis={'categoryorder': 'total ascending'},
                          margin=dict(l=10, r=10, t=40, b=10), xaxis_tickformat=',.0f')
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("**📈 组长团队成长波动对比**")
    team_leaders = sorted(df['team_leader'].dropna().unique().tolist())
    default_tls = team_leaders[:min(5, len(team_leaders))]
    selected_tls = st.multiselect("选择组长对比（最多8人）", team_leaders, default=default_tls,
                                  max_selections=8, key="tl_multiselect")
    if selected_tls:
        freq_map = {"按日": "D", "按周": "W", "按月": "ME"}
        freq = freq_map.get(granularity, "W")
        df_tl = df[df['team_leader'].isin(selected_tls)].copy()
        df_tl_agg = df_tl.groupby([pd.Grouper(key='stat_date', freq=freq), 'team_leader'])['total_sales'].sum().reset_index()
        fig = px.line(df_tl_agg, x='stat_date', y='total_sales', color='team_leader', markers=True,
                      title=f'组长团队销售额成长对比（{granularity}）',
                      labels={'total_sales': '销售额', 'stat_date': '日期', 'team_leader': '组长'})
        fig.update_layout(height=400, hovermode='x unified',
                          legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                          margin=dict(l=10, r=10, t=60, b=10), yaxis_tickformat=',.0f')
        st.plotly_chart(fig, use_container_width=True)
        if len(selected_tls) == 1:
            st.markdown(f"**🔍 {selected_tls[0]} 组内运营成长对比**")
            df_one_tl = df[df['team_leader'] == selected_tls[0]].copy()
            df_one_tl_agg = df_one_tl.groupby([pd.Grouper(key='stat_date', freq=freq), 'operator'])['total_sales'].sum().reset_index()
            fig = px.line(df_one_tl_agg, x='stat_date', y='total_sales', color='operator', markers=True,
                          title=f'{selected_tls[0]} 组内各运营成长趋势',
                          labels={'total_sales': '销售额', 'stat_date': '日期', 'operator': '运营'})
            fig.update_layout(height=380, hovermode='x unified', yaxis_tickformat=',.0f',
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
            st.plotly_chart(fig, use_container_width=True)
# ============================================================
# 主管维度成长分析
# ============================================================
def render_manager_growth(df, granularity):
    st.markdown('<div class="section-title">🎯 主管部门成长分析</div>', unsafe_allow_html=True)
    if df.empty or df['manager'].isna().all():
        st.warning("无主管数据")
        return
    mgr_summary = df.groupby('manager').agg(
        total_sales=('total_sales', 'sum'),
        net_sales=('net_sales', 'sum'),
        order_count=('order_count', 'sum'),
        operator=('operator', 'nunique'),
        team_leader=('team_leader', 'nunique'),
    ).reset_index()
    mgr_summary.columns = ['主管', '销售额', '净销售额', '订单数', '运营人数', '组长人数']
    mgr_summary = mgr_summary.sort_values('销售额', ascending=False).reset_index(drop=True)
    mgr_summary.index = mgr_summary.index + 1
    mgr_summary.index.name = '排名'
    col1, col2 = st.columns([1, 1.5])
    with col1:
        st.markdown("**🏆 主管业绩排名**")
        display_df = mgr_summary.copy()
        display_df['销售额'] = display_df['销售额'].apply(lambda x: f"¥{x:,.0f}")
        display_df['净销售额'] = display_df['净销售额'].apply(lambda x: f"¥{x:,.0f}")
        st.dataframe(display_df, use_container_width=True, height=300)
    with col2:
        st.markdown("**📊 主管销售额对比**")
        fig = px.bar(mgr_summary, x='销售额', y='主管', orientation='h',
                     color='销售额', color_continuous_scale='RdPu',
                     title='各主管销售额对比')
        fig.update_layout(height=300, yaxis={'categoryorder': 'total ascending'},
                          margin=dict(l=10, r=10, t=40, b=10), xaxis_tickformat=',.0f')
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("**📈 主管团队成长波动对比**")
    freq_map = {"按日": "D", "按周": "W", "按月": "ME"}
    freq = freq_map.get(granularity, "W")
    df_mgr_agg = df.groupby([pd.Grouper(key='stat_date', freq=freq), 'manager'])['total_sales'].sum().reset_index()
    fig = px.line(df_mgr_agg, x='stat_date', y='total_sales', color='manager', markers=True,
                  title=f'主管团队销售额成长对比（{granularity}）',
                  labels={'total_sales': '销售额', 'stat_date': '日期', 'manager': '主管'})
    fig.update_layout(height=400, hovermode='x unified',
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
                      margin=dict(l=10, r=10, t=60, b=10), yaxis_tickformat=',.0f')
    st.plotly_chart(fig, use_container_width=True)
    managers = sorted(df['manager'].dropna().unique().tolist())
    if managers:
        selected_mgr = st.selectbox("查看主管下属运营成长", managers, key="mgr_detail_select")
        if selected_mgr:
            df_mgr_op = df[df['manager'] == selected_mgr].copy()
            df_mgr_op_agg = df_mgr_op.groupby([pd.Grouper(key='stat_date', freq=freq), 'operator'])['total_sales'].sum().reset_index()
            fig = px.line(df_mgr_op_agg, x='stat_date', y='total_sales', color='operator', markers=True,
                          title=f'{selected_mgr} 下属各运营成长趋势',
                          labels={'total_sales': '销售额', 'stat_date': '日期', 'operator': '运营'})
            fig.update_layout(height=400, hovermode='x unified', yaxis_tickformat=',.0f',
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
            st.plotly_chart(fig, use_container_width=True)
# ============================================================
# 主页面
# ============================================================
def main():
    st.markdown('<div class="main-header">📊 WB运营人员成长分析看板</div>', unsafe_allow_html=True)
    st.caption("业绩统计规则：运营业绩从接手店铺日期起算，支持店铺交接（换店后订单归新运营）")
    dim_df = load_dimensions()
    filters = render_sidebar(dim_df)
    render_filter_bar(filters, dim_df)
    st.markdown("---")
    with st.spinner("数据加载中..."):
        df = load_performance_data(
            filters['start_date'], filters['end_date'],
            filters['dept'], filters['manager'], filters['team_leader'],
        )
        entry_info_df = load_operator_entry_info()
    render_kpi_cards(df)
    st.markdown("---")
    render_growth_trend(df, filters['granularity'])
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🚀 成长曲线",
        "📅 周度成长汇总",
        "🏆 新人成长排名",
        "👤 运营成长",
        "👥 组长成长",
        "🎯 主管成长",
    ])
    with tab1:
        render_entry_growth(df, entry_info_df)
    with tab2:
        render_weekly_growth_summary(df)
    with tab3:
        render_newcomer_ranking(df, entry_info_df)
    with tab4:
        render_operator_growth(df, entry_info_df, filters['granularity'])
    with tab5:
        render_team_leader_growth(df, filters['granularity'])
    with tab6:
        render_manager_growth(df, filters['granularity'])
    st.markdown("---")
    st.markdown(
        f"<div style='text-align: center; color: #999; font-size: 12px;'>"
        f"WB运营人员成长分析系统 | 业绩从入职日起算 | 数据更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        f"</div>", unsafe_allow_html=True,
    )
if __name__ == "__main__":
    main()
