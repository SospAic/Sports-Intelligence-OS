# Postgres 17 (alpine) + pgvector
#
# 为什么不用官方 pgvector/pgvector:pg17 镜像：
#   现有数据卷是用 postgres:17-alpine（musl）初始化的，datcollate = en_US.utf8。
#   切到 debian/glibc 基础镜像后同名 locale 的排序规则不同，会让 617 个既有
#   btree 文本索引逻辑失效，必须 REINDEX 整库（2.6 GB）。在 alpine 上自编译
#   pgvector 可以完全规避这一风险。
#
# 为什么不用 apk 的 postgresql-pgvector：
#   Alpine 3.24 社区源里的包是针对 PostgreSQL 18 编译的
#   （usr/lib/postgresql18/vector.so），无法加载进官方镜像自带的 PG 17。
#
# 编译参数说明：
#   with_llvm=no  —— 官方 alpine 镜像用 llvm21 构建，但仓库里没有对应的 clang-21，
#                    bitcode 步骤必然失败。JIT inlining 对 pgvector 非必需。
#   OPTFLAGS=''   —— 关掉 pgvector 默认的 -march=native，保证镜像可在异构 CPU 复用。

FROM postgres:17-alpine

ARG PGVECTOR_VERSION=0.8.0

RUN set -eux; \
    apk add --no-cache --virtual .pgvector-build build-base; \
    wget -q -O /tmp/pgvector.tar.gz \
        "https://codeload.github.com/pgvector/pgvector/tar.gz/refs/tags/v${PGVECTOR_VERSION}"; \
    mkdir -p /tmp/pgvector; \
    tar xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1; \
    cd /tmp/pgvector; \
    make with_llvm=no OPTFLAGS=''; \
    make with_llvm=no OPTFLAGS='' install; \
    cd /; \
    rm -rf /tmp/pgvector /tmp/pgvector.tar.gz; \
    apk del --no-network .pgvector-build; \
    test -f /usr/local/lib/postgresql/vector.so

# 仅在首次 initdb（空数据卷）时执行；已初始化的数据卷需手动 CREATE EXTENSION。
COPY deploy/postgres-init/ /docker-entrypoint-initdb.d/
