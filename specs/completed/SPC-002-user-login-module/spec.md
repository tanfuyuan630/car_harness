# SPC-002 用户登录与注册功能模块

## 背景
当前汽车销售助手系统无用户体系，任何人均可直接访问所有功能。需要增加用户注册与登录鉴权，仅登录用户可使用系统。

## 需求

### 1. 后端登录功能模块
- 提供用户登录接口，校验用户ID + 密码
- 登录成功后返回访问凭证（Token）
- 提供登出接口

### 2. 后端注册功能模块
- 提供用户注册接口，字段：`user_id`、`user_name`、`user_pwd`、`age`（可选）
- 密码使用 bcrypt 加盐哈希存储，不存明文（盐由 bcrypt 自动生成并嵌入哈希值）
- `user_id` 全局唯一，冲突时返回 409
- 后端字段级校验（Pydantic）：必填、长度、密码强度
- `state` 默认 1（有效），`create_date`/`update_date` 由后端填充

### 2.1 登录密码校验
- 登录时调用 `bcrypt.verify(明文密码, DB中的哈希)` 校验
- bcrypt 从存储的哈希值中提取注册时使用的盐，用同一盐重算输入密码的哈希后比较
- 注册与登录使用完全相同的 bcrypt 算法与参数，保证一致性

### 3. 用户数据存储
- 使用 MySQL 数据库存储用户信息
- 连接配置写入配置文件（`.env`）
- MySQL 连接：`127.0.0.1:3306@root/123456`

### 4. 用户表结构
```sql
CREATE TABLE `t_users` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_name` varchar(200) NOT NULL COMMENT '用户名称',
  `user_id` varchar(200) NOT NULL COMMENT '用户id',
  `user_pwd` varchar(200) NOT NULL COMMENT '密码',
  `age` int DEFAULT NULL COMMENT '年龄',
  `create_date` datetime NOT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '创建时间',
  `create_by` varchar(200) DEFAULT NULL COMMENT '创建人',
  `update_date` datetime NOT NULL COMMENT '修改时间',
  `update_by` varchar(200) DEFAULT NULL COMMENT '修改人',
  `state` tinyint DEFAULT '1' COMMENT '状态:0失效,1有效',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_id` (`user_id`)
)
```

### 5. 前端改造
- 增加登录页面，未登录用户跳转登录页
- 增加注册页面（可从登录页跳转），含表单校验与冲突提示
- 登录成功后进入主页面
- 所有受保护接口请求携带 Token
- 提供登出入口

### 6. 鉴权保护
- 后端受保护接口需校验 Token，未登录返回 401
- 前端路由守卫拦截未登录访问

## 验收标准
- 未登录访问主页面 → 跳转登录页
- 新用户可成功注册，密码以哈希存入数据库
- 注册重复 `user_id` → 提示冲突（409）
- 使用正确账号密码登录 → 进入主页面，可正常使用功能
- 使用错误密码登录 → 提示错误
- 登出后 → 回到登录页
- Token 校验通过/不通过的接口行为符合预期
