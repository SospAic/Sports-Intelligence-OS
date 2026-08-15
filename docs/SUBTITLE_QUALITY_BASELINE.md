# 字幕 ASR / 翻译质量基线

字幕任务会保留 ASR 模型、翻译 Provider、来源类型、时间轴和 Artifact Registry 校验状态；它不会把机器翻译成功当成质量通过。质量基线需要运营者提供经过人工确认的参考集，仓库不内置体育事实或翻译“标准答案”。

使用方式：

```text
python scripts/evaluate_subtitle_quality.py path/to/reference-set.json \
  --output reports/subtitle-quality.json
```

输入样例字段为 `id`、`reference`、`hypothesis`、`translation_reference` 和 `translation_hypothesis`。工具输出转写 token error rate、句级 BLEU 诊断、缺少参考答案的数量，并在缺少参考答案时将 `quality_claim_allowed` 设为 `false`。BLEU 仅用于回归报警，生产发布仍要结合 COMET 或人工抽检、语言覆盖率、失败率、队列延迟和模型版本。

首期不把“没有参考集”显示为 0 分；ASR/翻译质量、GPU/CPU 预算和模型缓存容量仍需在目标部署环境用代表性样本完成验收。
