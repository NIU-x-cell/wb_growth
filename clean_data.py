"""
WB运营人员成长分析系统 - 数据清洗与导入脚本
功能：读取Excel → 清洗标准化 → 按店铺+时间段关联运营（支持交接换店）→ 批量导入MySQL
核心规则：
  1. 运营业绩从接手店铺日期（entry_date）起算
  2. 支持店铺交接：同一店铺不同时间段归属不同运营
  3. bind_end_date = NULL 表示至今仍在负责
使用：python clean_data.py
"""
import re
import pandas as pd
import pymysql
from sqlalchemy import create_engine, text
from datetime import datetime
from config import get_db_config, PERSON_FILE, ORDER_FILE


# ============================================================
# 工具函数
# ============================================================

def standardize_shop_name(name):
    """店铺名标准化：去WB前缀、去空格、数字结尾补店字"""
    if pd.isna(name) or str(name).strip() == "":
        return ""
    s = str(name).strip()
    s = re.sub(r'^WB\s*', '', s, flags=re.IGNORECASE)
    s = s.replace(' ', '').replace('\u3000', '')
    if re.search(r'\d+$', s) and '店' not in s:
        s = s + '店'
    return s


def build_shop_mapping(person_df, order_df):
    """构建店铺名映射：订单表标准化名 → 人员表标准化名（模糊匹配）"""
    person_shops = set(person_df['shop_name_std'].unique())
    order_shops = set(order_df['shop_name_std'].unique())
    direct_match = person_shops & order_shops
    mapping = {s: s for s in direct_match}
    unmatched_orders = order_shops - direct_match
    unmatched_persons = person_shops - direct_match
    for o_shop in unmatched_orders:
        if not o_shop:
            continue
        best_match = None
        for p_shop in unmatched_persons:
            if not p_shop:
                continue
            if o_shop in p_shop or p_shop in o_shop:
                if best_match is None or abs(len(p_shop) - len(o_shop)) < abs(len(best_match) - len(o_shop)):
                    best_match = p_shop
        if best_match:
            mapping[o_shop] = best_match
    return mapping


def excel_date_to_date(val):
    """Excel日期序列号转date"""
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, (int, float)):
        try:
            return (pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(val))).date()
        except:
            return None
    return None


def safe_str(val, max_len=None):
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    if max_len and len(s) > max_len:
        s = s[:max_len]
    return s


def safe_float(val):
    if pd.isna(val):
        return 0.0
    try:
        return float(val)
    except:
        return 0.0


# ============================================================
# 数据读取与清洗
# ============================================================

def load_and_clean_personnel():
    """读取并清洗人员名单（支持 bind_end_date 解绑日期）"""
    print("[1/4] 读取人员名单...")
    df = pd.read_excel(PERSON_FILE)

    # 兼容列名：入职时间/入职日期/接手日期；更换该负责人名下日期/更换日期/解绑日期/交接日期/bind_end_date
    valid_cols = ['部门', '主管', '组长', '运营', '性别', '职位', '店铺', '店铺 id',
                  '手机号', '入职时间', '入职日期',
                  '接手日期', '接手店铺日期', '更换该负责人名下日期', '更换负责人日期', '更换日期',
                  '年龄', '籍贯', '学历', '是否有工作经验']
    existing_cols = [c for c in valid_cols if c in df.columns]
    df = df[existing_cols].copy()

    df = df.dropna(subset=['运营', '店铺'], how='all')
    df = df[df['运营'].notna() & (df['运营'].astype(str).str.strip() != '')]

    df.columns = [c.strip() for c in df.columns]

    # 入职日期：优先用"入职日期"，其次"入职时间"（固定不变）
    entry_col = None
    for c in ['入职日期', '入职时间']:
        if c in df.columns:
            entry_col = c
            break

    # 接手店铺日期（可选，有则按此日期算业绩，无则用入职日期）
    take_col = None
    for c in ['接手日期', '接手店铺日期', '更换该负责人名下日期', '更换负责人日期', '更换日期']:
        if c in df.columns:
            take_col = c
            break

    col_map = {
        '部门': 'department', '主管': 'manager', '组长': 'team_leader', '运营': 'operator',
        '性别': 'gender', '职位': 'position', '店铺': 'shop_name', '店铺 id': 'shop_id',
        '手机号': 'phone', '年龄': 'age_group',
        '籍贯': 'hometown', '学历': 'education', '是否有工作经验': 'experience',
    }
    col_map[entry_col] = 'entry_date'
    if take_col:
        col_map[take_col] = 'take_shop_date'

    df = df.rename(columns=col_map)

    # 补全可选列
    if 'take_shop_date' not in df.columns:
        df['take_shop_date'] = None

    df['shop_name_std'] = df['shop_name'].apply(standardize_shop_name)

    df['department'] = df['department'].apply(lambda x: safe_str(x, 50))
    df['manager'] = df['manager'].apply(lambda x: safe_str(x, 50))
    df['team_leader'] = df['team_leader'].apply(lambda x: safe_str(x, 50))
    df['operator'] = df['operator'].apply(lambda x: safe_str(x, 50))
    df['gender'] = df['gender'].apply(lambda x: safe_str(x, 10))
    df['position'] = df['position'].apply(lambda x: safe_str(x, 50))
    df['shop_name'] = df['shop_name'].apply(lambda x: safe_str(x, 100))
    df['shop_id'] = df['shop_id'].apply(lambda x: safe_str(str(int(x)) if pd.notna(x) and isinstance(x, (int, float)) else x, 50))
    df['phone'] = df['phone'].apply(lambda x: safe_str(str(int(x)) if pd.notna(x) and isinstance(x, (int, float)) else x, 20))
    df['entry_date'] = df['entry_date'].apply(excel_date_to_date)
    df['take_shop_date'] = df['take_shop_date'].apply(excel_date_to_date)
    df['age_group'] = df['age_group'].apply(lambda x: safe_str(x, 20))
    df['hometown'] = df['hometown'].apply(lambda x: safe_str(x, 100))
    df['education'] = df['education'].apply(lambda x: safe_str(x, 50))
    df['experience'] = df['experience'].apply(lambda x: safe_str(x, 200))

    # 组长为空时，用运营名填充
    df['team_leader'] = df['team_leader'].fillna(df['operator'])

    # 修复部门/主管为空的行（主管自己的店铺行）
    mgr_dept_map = df.dropna(subset=['department', 'manager']).drop_duplicates('manager').set_index('manager')['department'].to_dict()
    mask = df['department'].isna() & df['operator'].isin(mgr_dept_map.keys())
    df.loc[mask, 'department'] = df.loc[mask, 'operator'].map(mgr_dept_map)
    df.loc[mask, 'manager'] = df.loc[mask, 'operator']

    # 统计
    shop_counts = df.groupby('shop_name_std')['operator'].nunique()
    transfer_shops = shop_counts[shop_counts > 1]
    has_take = df['take_shop_date'].notna().sum()

    print(f"  人员记录数: {len(df)}")
    print(f"  有入职日期的记录: {df['entry_date'].notna().sum()}")
    print(f"  有接手店铺日期的记录: {has_take}（有则按此日期算，无则用入职日期）")
    print(f"  部门: {df['department'].unique()}")

    return df


def load_and_clean_orders():
    """读取并清洗订单数据"""
    print("[2/4] 读取订单数据...")
    df = pd.read_excel(ORDER_FILE)

    col_map = {
        '订单编号': 'order_no', '交易编号': 'trade_no', '平台状态': 'platform_status',
        '付款时间': 'pay_time', '店铺名': 'shop_name', '发货时间': 'ship_time',
        '订单状态': 'order_status', '退货标识': 'return_flag', '作废时间': 'cancel_time',
        '作废前状态': 'cancel_before_status', '退款时间': 'refund_time',
        '是否退款订单': 'is_refund', '商品总金额': 'goods_amount',
        '支出运费': 'shipping_fee', '包材费': 'packaging_fee',
        '商品总成本': 'goods_cost', '广告费(人民币)': 'ad_fee',
        '原始运费金额': 'original_shipping', 'SKU': 'sku', '订单商品名称': 'product_name',
    }
    df = df.rename(columns=col_map)
    df['shop_name_std'] = df['shop_name'].apply(standardize_shop_name)

    for col in ['pay_time', 'ship_time', 'cancel_time', 'refund_time']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    for col in ['goods_amount', 'shipping_fee', 'packaging_fee', 'goods_cost', 'ad_fee', 'original_shipping']:
        if col in df.columns:
            df[col] = df[col].apply(safe_float)

    for col in ['order_no', 'trade_no', 'platform_status', 'shop_name', 'order_status',
                'return_flag', 'cancel_before_status', 'is_refund']:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: safe_str(x, 100))
    df['sku'] = df['sku'].apply(lambda x: safe_str(x, 200))
    df['product_name'] = df['product_name'].apply(lambda x: safe_str(x, 1000))

    print(f"  订单记录数: {len(df)}")
    print(f"  时间范围: {df['pay_time'].min()} ~ {df['pay_time'].max()}")

    return df


def link_personnel_to_orders(person_df, order_df):
    """
    将人员信息关联到订单表（支持店铺交接）
    匹配规则：店铺名匹配 AND 付款时间在 [entry_date, bind_end_date] 区间内
    多个匹配时取 entry_date 最大的（最近接手的运营）
    """
    print("[3/4] 关联人员与订单（支持店铺交接，按时间段匹配）...")

    # 构建店铺映射
    shop_mapping = build_shop_mapping(person_df, order_df)
    order_df['shop_name_std_mapped'] = order_df['shop_name_std'].map(shop_mapping)

    # 按店铺分组，每个店铺可能有多个运营（不同时间段）
    person_by_shop = {}
    for _, row in person_df.iterrows():
        shop = row['shop_name_std']
        if shop not in person_by_shop:
            person_by_shop[shop] = []
        # 实际业绩起算日期：接手店铺日期优先，没有则用入职日期
        if pd.notna(row['take_shop_date']):
            effective_start = row['take_shop_date']
        elif pd.notna(row['entry_date']):
            effective_start = row['entry_date']
        else:
            effective_start = None
        # 统一把 NaN/NaT 转成 None
        entry = row['entry_date'] if pd.notna(row['entry_date']) else None
        take = row['take_shop_date'] if pd.notna(row['take_shop_date']) else None
        person_by_shop[shop].append({
            'department': row['department'],
            'manager': row['manager'],
            'team_leader': row['team_leader'],
            'operator': row['operator'],
            'entry_date': entry,          # 入职日期（固定）
            'take_shop_date': take,       # 接手店铺日期（可选）
            'effective_start': effective_start,  # 实际起算日期
        })

    # 每个店铺的运营按实际起算日期排序（方便取最近接手的）
    for shop in person_by_shop:
        person_by_shop[shop].sort(
            key=lambda x: x['effective_start'] if x['effective_start'] else datetime.min.date()
        )

    def get_person_info(row):
        shop = row['shop_name_std_mapped']
        pay_time = row['pay_time']
        if pd.isna(shop) or shop not in person_by_shop:
            return pd.Series([None, None, None, None, None, None])

        pay_date = pay_time.date() if pd.notna(pay_time) else None
        candidates = person_by_shop[shop]
        matched = None

        for p in candidates:
            # 运营姓名为空/NaN = 店铺暂时无人，不匹配
            if p['operator'] is None or pd.isna(p['operator']) or str(p['operator']).strip() == '':
                continue

            start = p['effective_start']  # 实际起算日期=接手日期优先，否则入职日期

            # 没有起算日期：默认匹配（取第一个遇到的）
            if start is None:
                if matched is None:
                    matched = p
                continue

            # 没有付款时间：无法判断时间段，跳过
            if pay_date is None:
                continue

            # 核心匹配：付款时间 >= 实际起算日期
            if pay_date >= start:
                matched = p  # 循环结束后 matched 是最近接手的

        if matched is None:
            return pd.Series([None, None, None, None, None, None])

        # 订单表的 entry_date 存实际起算日期（接手日期优先，否则入职日期）
        effective_start = matched['effective_start']
        days = (pay_date - effective_start).days if (effective_start and pay_date) else None
        return pd.Series([
            matched['department'], matched['manager'], matched['team_leader'],
            matched['operator'], effective_start, days
        ])

    order_df[['department', 'manager', 'team_leader', 'operator', 'entry_date', 'days_since_entry']] = \
        order_df.apply(get_person_info, axis=1)

    # 保存店铺匹配标记
    order_df['_shop_matched'] = order_df['shop_name_std_mapped'].notna()
    order_df = order_df.drop(columns=['shop_name_std_mapped'])

    # 统计
    matched = order_df['operator'].notna().sum()
    total = len(order_df)
    shop_matched_count = order_df['_shop_matched'].sum()
    filtered = int(shop_matched_count - matched)

    print(f"  订单匹配率: {matched}/{total} ({matched/total*100:.1f}%)")
    print(f"  店铺匹配但未关联（接手前/无匹配时间段）: {filtered} 条")

    return order_df


# ============================================================
# 数据库导入
# ============================================================

def get_engine():
    cfg = get_db_config()
    ssl_params = ""
    if cfg.get("ssl_verify_cert"):
        ssl_params = "?ssl_verify_cert=true&ssl_verify_identity=true"
    url = f"mysql+pymysql://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['database']}?charset={cfg['charset']}{ssl_params}"
    return create_engine(url, pool_recycle=3600, pool_pre_ping=True)


def import_to_db(person_df, order_df):
    """批量导入数据库"""
    print("[4/4] 导入数据库...")
    engine = get_engine()

    with engine.connect() as conn:
        conn.execute(text("TRUNCATE TABLE wb_orders"))
        conn.execute(text("TRUNCATE TABLE wb_personnel"))
        conn.commit()

    # 导入人员表（含 bind_end_date）
    person_cols = ['department', 'manager', 'team_leader', 'operator', 'gender', 'position',
                   'shop_name', 'shop_name_std', 'shop_id', 'phone', 'entry_date', 'take_shop_date',
                   'age_group', 'hometown', 'education', 'experience']
    person_to_import = person_df[person_cols].copy()
    person_to_import.to_sql('wb_personnel', engine, if_exists='append', index=False, chunksize=1000)
    print(f"  人员表导入: {len(person_to_import)} 行")

    # 导入订单表
    order_cols = ['order_no', 'trade_no', 'platform_status', 'pay_time', 'shop_name',
                  'shop_name_std', 'ship_time', 'order_status', 'return_flag', 'cancel_time',
                  'cancel_before_status', 'refund_time', 'is_refund', 'goods_amount',
                  'shipping_fee', 'packaging_fee', 'goods_cost', 'ad_fee', 'original_shipping',
                  'sku', 'product_name', 'department', 'manager', 'team_leader', 'operator',
                  'entry_date', 'days_since_entry']
    order_to_import = order_df[order_cols].copy()

    batch_size = 5000
    total = len(order_to_import)
    for i in range(0, total, batch_size):
        batch = order_to_import.iloc[i:i+batch_size]
        batch.to_sql('wb_orders', engine, if_exists='append', index=False, chunksize=1000)
        print(f"  订单表导入: {min(i+batch_size, total)}/{total} 行")

    print("  导入完成！")


def verify_import():
    """验证导入结果"""
    engine = get_engine()
    with engine.connect() as conn:
        person_count = pd.read_sql("SELECT COUNT(*) as cnt FROM wb_personnel", conn).iloc[0]['cnt']
        order_count = pd.read_sql("SELECT COUNT(*) as cnt FROM wb_orders", conn).iloc[0]['cnt']
        matched_orders = pd.read_sql(
            "SELECT COUNT(*) as cnt FROM wb_orders WHERE operator IS NOT NULL", conn
        ).iloc[0]['cnt']
        has_take = pd.read_sql(
            "SELECT COUNT(*) as cnt FROM wb_personnel WHERE take_shop_date IS NOT NULL", conn
        ).iloc[0]['cnt']
        no_operator = pd.read_sql(
            "SELECT COUNT(*) as cnt FROM wb_personnel WHERE operator IS NULL OR operator = ''", conn
        ).iloc[0]['cnt']
    print(f"\n=== 导入验证 ===")
    print(f"  人员表: {person_count} 行")
    print(f"  有接手店铺日期的人员: {has_take} 行")
    print(f"  运营姓名为空（店铺暂时无人）: {no_operator} 行")
    print(f"  订单表: {order_count} 行")
    print(f"  已关联运营的订单: {matched_orders} 行 ({matched_orders/order_count*100:.1f}%)")


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 60)
    print("WB运营人员成长分析 - 数据清洗与导入（支持店铺交接）")
    print("=" * 60)

    person_df = load_and_clean_personnel()
    order_df = load_and_clean_orders()
    order_df = link_personnel_to_orders(person_df, order_df)
    import_to_db(person_df, order_df)
    verify_import()

    print("\n全部完成！可以运行 streamlit run growth_dashboard.py 启动看板。")


if __name__ == "__main__":
    main()
