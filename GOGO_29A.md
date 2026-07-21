# GOGO — 29号 A组（认证+存储+权益+隐私）2026-07-20

前置必读: ../AnimaCodex_执行任务书/29_M3账号与支付系统_两模型任务书.md
收款主体已定: Paddle

## 已完成的依赖（不用你做）
- ✅ 30号全局互动引擎: bazi_engine/global_interaction.py 已就位
- ✅ 31号六爻+大六壬: liuyao.py/daliuren.py/oracle_fusion.py 已就位
- ✅ API: /api/v1/oracle/cast 已在 main.py
- ✅ Git: commit 3945efd 待push

## 执行顺序

### A5: SQLite→PostgreSQL迁移（先做）
- 创建迁移脚本 `backend/migrations/001_init.sql`
- 表: users/sessions/entitlements/purchases + chart表加user_id列
- 可复现可回滚，pytest≥5条迁移测试

### A1: JWT认证
`api/auth.py` 新增:
- POST /auth/register (email+password→JWT)
- POST /auth/login (email+password→JWT)
- POST /auth/magic-link (发mock邮件, Resend后接)
- GET /auth/verify?token=xxx
- POST /auth/refresh / DELETE /auth/session
- JWT 不含chart_id/出生资料

### A2: 命盘库
- POST /chart/{id}/claim (owner_secret+JWT→认领)
- GET /user/charts (列表)
- PATCH/DELETE /user/charts/{id}

### A3: 权益管理
- GET /user/entitlements
- POST /user/entitlements/redeem

### A4: 隐私四件套
- POST /user/export (JSON导出)
- DELETE /user/account (7天冷静期)
- GET /user/privacy-policy
- GET /user/access-log

## 验收
pytest≥40条新增。红线: 响应不泄露email原文/hash、匿名模式不因JWT泄露出生数据。

## 环境
- Neon PostgreSQL: Owner提供连接字符串
- 当前可先用SQLite开发，结构对齐PG
