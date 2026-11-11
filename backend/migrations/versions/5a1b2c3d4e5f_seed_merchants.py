"""seed merchant catalog

Revision ID: 5a1b2c3d4e5f
Revises: 4f5a6a60bd89
Create Date: 2026-11-11
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

revision = "5a1b2c3d4e5f"
down_revision = "4f5a6a60bd89"
branch_labels = None
depends_on = None

MERCHANTS = [
    ("星巴克", "星巴克,starbucks,星巴克咖啡,starbucks coffee", "餐饮", "0.950"),
    ("瑞幸咖啡", "瑞幸,瑞幸咖啡,luckin,luckin coffee", "餐饮", "0.950"),
    ("麦当劳", "麦当劳,mcdonalds,mcdonald's,金拱门", "餐饮", "0.950"),
    ("肯德基", "肯德基,kfc,kentucky fried chicken", "餐饮", "0.950"),
    ("汉堡王", "汉堡王,burger king", "餐饮", "0.900"),
    ("海底捞", "海底捞,haidilao,海底捞火锅", "餐饮", "0.930"),
    ("喜茶", "喜茶,heytea,喜茶go", "餐饮", "0.920"),
    ("蜜雪冰城", "蜜雪冰城,mixue,蜜雪", "餐饮", "0.920"),
    ("美团外卖", "美团,美团外卖,meituan", "餐饮", "0.900"),
    ("饿了么", "饿了么,eleme,饿了吗", "餐饮", "0.900"),
    ("全家便利店", "全家,全家便利店,family mart,familymart", "购物", "0.900"),
    ("罗森便利店", "罗森,罗森便利店,lawson", "购物", "0.900"),
    ("盒马鲜生", "盒马,盒马鲜生,hema,盒马超市", "购物", "0.920"),
    ("沃尔玛", "沃尔玛,walmart", "购物", "0.900"),
    ("永辉超市", "永辉,永辉超市,yonghui", "购物", "0.900"),
    ("京东", "京东,jd,jd.com,京东商城", "购物", "0.930"),
    ("淘宝", "淘宝,taobao,天猫,tmall", "购物", "0.930"),
    ("拼多多", "拼多多,pdd,pinduoduo", "购物", "0.920"),
    ("滴滴出行", "滴滴,滴滴出行,didi,滴滴打车", "交通", "0.950"),
    ("高德打车", "高德,高德打车,amap", "交通", "0.900"),
    ("中国石化", "中国石化,中石化,sinopec,石化加油", "交通", "0.930"),
    ("中国移动", "中国移动,移动,china mobile", "通讯", "0.930"),
    ("中国联通", "中国联通,联通,china unicom", "通讯", "0.930"),
    ("国家电网", "国家电网,电网,电费,国网", "生活缴费", "0.930"),
    ("猫眼电影", "猫眼,猫眼电影,maoyan", "娱乐", "0.900"),
    ("腾讯视频", "腾讯视频,tencent video", "娱乐", "0.900"),
    ("美团单车", "美团单车,摩拜,mobike", "交通", "0.880"),
    ("携程旅行", "携程,携程旅行,ctrip", "旅行", "0.920"),
    ("链家", "链家,lianjia,链家地产", "住房", "0.900"),
    ("老百姓大药房", "老百姓,老百姓大药房,药房", "医疗", "0.880"),
]

merchants_table = sa.table(
    "merchants",
    sa.column("id", sa.Uuid),
    sa.column("name", sa.String),
    sa.column("normalized", sa.String),
    sa.column("aliases", sa.Text),
    sa.column("category", sa.String),
    sa.column("confidence", sa.Numeric),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    from app.services.parsing import normalize_merchant

    op.bulk_insert(
        merchants_table,
        [
            {
                "id": uuid.uuid4(),
                "name": name,
                "normalized": normalize_merchant(name),
                "aliases": aliases,
                "category": category,
                "confidence": Decimal(confidence),
                "created_at": datetime.now(UTC),
            }
            for name, aliases, category, confidence in MERCHANTS
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM merchants")
