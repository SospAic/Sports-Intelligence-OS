-- 在 template1 里装 vector，使后续 CREATE DATABASE（默认以 template1 为模板）
-- 自动继承该扩展——测试库 sports_intelligence_test 每次 DROP/CREATE 后也能直接用。
\connect template1
CREATE EXTENSION IF NOT EXISTS vector;

-- 业务库本身
\connect :"POSTGRES_DB"
CREATE EXTENSION IF NOT EXISTS vector;
