# 导入 V7.9 规则原文

本目录用于保存用户拥有且获准使用的 7.9 规则源文件。项目不会在源文件缺失时虚构完整原文，也不会把结构化摘要冒充完整规则。

推荐文件名：

`ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt`

完成数据库迁移并创建管理员后执行：

```bash
make import-rules FILE=data/rules/ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt
```

导入器按原始字节计算 SHA-256，保留完整原文，并生成带原文行号引用的章节和规则。相同哈希重复导入是幂等操作。
