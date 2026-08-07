## 项目规范

AI 不得擅自修改./spec
AI 不得擅自更改 Agent 提示词，修改前需征求主人同意
test 接口向backend 适配，backend 接口不得向 test 适配

## api 规范

## 数据库规范

### 数据库列表
```
app-# \dt
             List of relations
 Schema |     Name      | Type  |  Owner   
--------+---------------+-------+----------
 public | app_users     | table | postgres
 public | conversations | table | postgres
(2 rows)
```

### app_users表结构
```
app=# \d app_users;
                                   Table "public.app_users"
    Column     |           Type           | Collation | Nullable |          Default           
---------------+--------------------------+-----------+----------+----------------------------
 id            | character varying(190)   |           | not null | 
 username      | character varying(100)   |           | not null | 
 password_hash | character varying(128)   |           |          | 
 display_name  | character varying(100)   |           | not null | 
 provider      | character varying(30)    |           | not null | 'local'::character varying
 avatar        | text                     |           |          | 
 created_at    | timestamp with time zone |           | not null | now()
Indexes:
    "app_users_pkey" PRIMARY KEY, btree (id)
    "app_users_username_key" UNIQUE CONSTRAINT, btree (username)
Referenced by:
    TABLE "conversations" CONSTRAINT "conversations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
```

### conversation表结构
```
app=# \d conversations;
                               Table "public.conversations"
   Column   |           Type           | Collation | Nullable |          Default           
------------+--------------------------+-----------+----------+----------------------------
 id         | character varying(100)   |           | not null | 
 user_id    | character varying(190)   |           | not null | 
 title      | character varying(255)   |           | not null | 
 provider   | character varying(30)    |           | not null | 'local'::character varying
 payload    | jsonb                    |           | not null | 
 created_at | timestamp with time zone |           | not null | now()
 updated_at | timestamp with time zone |           | not null | now()
Indexes:
    "conversations_pkey" PRIMARY KEY, btree (id)
Foreign-key constraints:
    "conversations_user_id_fkey" FOREIGN KEY (user_id) REFERENCES app_users(id) ON DELETE CASCADE
```